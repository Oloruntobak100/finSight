"""QuickBooks Books Pipeline: classify, approve, learn, and post to QBO."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal

from app.database import get_supabase, run_db
from app.services.categorization_service import load_user_category_rules, resolve_mono_transaction_category
from app.services.fingerprint_service import (
    FINGERPRINT_MATCH_MIN,
    _decisions_for_fingerprint,
    extract_fingerprint,
    fingerprint_confidence_reason,
    fingerprint_is_trained,
    fingerprint_match_confidence,
    fingerprint_propagation_confidence,
    lookup_fingerprint,
    lookup_fingerprint_by_payee,
    payee_pattern_for_row,
    recalculate_fingerprint_confidence,
    touch_fingerprint_seen,
    upsert_fingerprint_from_decision,
)
from app.services.qb_party_service import (
    entity_ref_for_txn,
    txn_doc_number,
    validate_party,
)
from app.services.posting_rag_service import (
    rag_classify_hint,
    store_posting_memory,
    user_has_posting_memory,
)
from app.services.quickbooks_service import qb_company_post_json, sync_chart_of_accounts
from app.services.transaction_posting_utils import (
    BALANCE_SHEET_ACCOUNT_TYPES,
    PostingKind,
    default_fee_account_names,
    detect_posting_kind,
    is_bank_fee,
    posting_kind_for_coa_account,
    posting_kind_to_intent,
    posting_type_for_approval,
    posting_type_for_kind,
    resolve_posting_entity,
)
from app.services.bank_transaction_scope import (
    BANK_PROVIDERS,
    apply_active_bank_scope,
    count_scoped_transactions,
    get_active_bank_accounts,
    iter_scoped_transactions,
)

logger = logging.getLogger(__name__)

QbSyncStatus = Literal[
    "pending",
    "needs_review",
    "posted",
    "excluded",
    "failed",
    "skipped",
    "auto_approved",
]
SuggestionMethod = Literal[
    "rule", "fingerprint", "rag", "llm", "auto", "manual", "auto_detect", "category"
]
CONFIDENCE_AUTO = 0.92
CONFIDENCE_LLM_MIN = 0.85
CONFIDENCE_FINGERPRINT_MIN = FINGERPRINT_MATCH_MIN
CLASSIFY_BATCH_SIZE = 500
CLASSIFY_MAX_ROWS = 5000

SUMMARY_STATUSES = (
    "pending",
    "needs_review",
    "auto_approved",
    "posted",
    "skipped",
)

# Legacy excluded rows appear in the Review tab; legacy failed rows appear in Failed.
_LEGACY_REVIEW_STATUSES = ("excluded", "failed")

_FAILED_QUEUE_OR = "qb_sync_status.eq.failed,qb_error.not.is.null"
_NEEDS_REVIEW_QUEUE_OR = (
    "and(qb_sync_status.eq.needs_review,qb_error.is.null),qb_sync_status.eq.excluded"
)


def _decision_method(method: str | None) -> str:
    """Map classify suggestion methods to posting_decisions.method allowed values."""
    m = (method or "manual").lower()
    legacy = frozenset({"rule", "fingerprint", "rag", "llm", "auto", "manual"})
    if m in legacy:
        return m
    if m == "category":
        return "rule"
    if m == "auto_detect":
        return "manual"
    return "manual"


def _apply_books_account_filter(query: Any, active_bank_ids: set[str]) -> Any:
    return apply_active_bank_scope(query, active_bank_ids)


async def _active_bank_accounts(user_id: str) -> tuple[list[dict[str, Any]], set[str]]:
    return await get_active_bank_accounts(user_id)


def _refreshed_category(txn: dict[str, Any], user_rules: dict[str, str]) -> str | None:
    raw = txn.get("raw_metadata") or {}
    if not isinstance(raw, dict):
        raw = {}
    meta_txn: dict[str, Any] = {**raw, "metadata": dict(raw.get("metadata") or {})}
    narration = txn.get("description") or raw.get("narration") or meta_txn.get("narration")
    if narration:
        meta_txn["narration"] = narration
    cat = resolve_mono_transaction_category(meta_txn, user_rules, txn.get("transaction_type"))
    return cat if cat != "Uncategorized" else None


def _auto_detect_reason(txn: dict[str, Any], kind: PostingKind) -> str:
    category = (txn.get("category") or "").strip()
    txn_type = txn.get("transaction_type") or ""
    cat_lower = category.lower()
    if cat_lower in ("transfer in", "transfer out"):
        direction = category
    elif txn_type == "credit":
        direction = "Transfer In"
    else:
        direction = "Transfer Out"

    fp = extract_fingerprint(txn)
    channel = fp.get("channel") or "OTHER"
    channel_label = channel if channel and channel != "OTHER" else "NIP"
    bank = fp.get("bank_code")
    bank_suffix = f" via {bank}" if bank else ""

    if kind == "balance_sheet":
        label = category or "Balance sheet movement"
        return f"{direction} — {label}{bank_suffix}; map to loan, equity, or asset account"
    if kind == "transfer":
        return (
            f"{direction} — inter-account transfer{bank_suffix}; "
            "select the other QuickBooks bank account"
        )
    if kind == "reversal":
        return f"Reversal — {category or 'bank reversal'}; match to the original category"
    return (
        f"{direction} — {channel_label}{bank_suffix}; "
        f"map to income or expense to train the system"
    )


async def get_user_automation(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("users")
        .select("auto_approve_enabled, auto_approve_threshold, digest_enabled")
        .eq("id", user_id)
        .single()
        .execute()
    )
    row = res.data or {}
    return {
        "auto_approve_enabled": bool(row.get("auto_approve_enabled", False)),
        "auto_approve_threshold": float(row.get("auto_approve_threshold") or 0.90),
        "digest_enabled": bool(row.get("digest_enabled", True)),
    }


async def update_user_automation(
    user_id: str,
    *,
    auto_approve_enabled: bool | None = None,
    auto_approve_threshold: float | None = None,
    digest_enabled: bool | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    patch: dict[str, Any] = {}
    if auto_approve_enabled is not None:
        patch["auto_approve_enabled"] = auto_approve_enabled
    if auto_approve_threshold is not None:
        patch["auto_approve_threshold"] = auto_approve_threshold
    if digest_enabled is not None:
        patch["digest_enabled"] = digest_enabled
    if patch:
        await run_db(lambda: sb.table("users").update(patch).eq("id", user_id).execute())
    return await get_user_automation(user_id)


async def list_coa(user_id: str, account_type: str | None = None) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("qb_chart_of_accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("active", True)
    )
    if account_type:
        query = query.eq("account_type", account_type)
    res = await run_db(lambda: query.order("name").execute())
    return res.data or []


def _account_ids_set(coa: list[dict[str, Any]]) -> set[str]:
    return _coa_ids(coa)


def _require_accounts_in_coa(
    coa: list[dict[str, Any]],
    *account_ids: str | None,
    label: str = "QuickBooks account",
) -> None:
    valid = _account_ids_set(coa)
    for account_id in account_ids:
        if account_id and not _account_valid(valid, account_id):
            raise ValueError(
                f"{label} is no longer valid in QuickBooks. Sync Chart of Accounts and update mappings."
            )


async def get_mappings(user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("qb_account_mappings")
        .select("*")
        .eq("user_id", user_id)
        .order("mapping_type")
        .execute()
    )
    return res.data or []


async def upsert_mapping(
    user_id: str,
    mapping_type: Literal["bank_account", "category"],
    finsight_key: str,
    qb_account_id: str,
    qb_account_name: str | None = None,
) -> dict[str, Any]:
    await ensure_coa_synced(user_id)
    coa = await list_coa(user_id)
    coa_row = next((r for r in coa if r.get("qb_account_id") == qb_account_id), None)
    if not coa_row:
        raise ValueError(
            "QuickBooks account not found. Sync Chart of Accounts and choose a current account."
        )
    acct_type = coa_row.get("account_type") or ""
    if mapping_type == "bank_account" and acct_type != "Bank":
        raise ValueError("Bank mapping must use a QuickBooks Bank account.")
    if mapping_type == "category" and acct_type not in (
        "Expense",
        "Income",
        "Other Expense",
        "Cost of Goods Sold",
    ):
        raise ValueError("Category mapping must use a QuickBooks income or expense account.")

    resolved_name = qb_account_name or coa_row.get("name")
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "mapping_type": mapping_type,
        "finsight_key": finsight_key,
        "qb_account_id": qb_account_id,
        "qb_account_name": resolved_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await run_db(
        lambda: sb.table("qb_account_mappings")
        .upsert(row, on_conflict="user_id,mapping_type,finsight_key")
        .execute()
    )
    return (res.data or [row])[0]


def _mapping_lookup(mappings: list[dict[str, Any]], mapping_type: str, key: str) -> dict[str, Any] | None:
    for m in mappings:
        if m.get("mapping_type") == mapping_type and m.get("finsight_key") == key:
            return m
    return None


def _accounts_for_kind(coa: list[dict[str, Any]], kind: PostingKind) -> list[dict[str, Any]]:
    def _type(row: dict[str, Any]) -> str:
        return (row.get("account_type") or "").strip().lower()

    if kind == "income":
        return [a for a in coa if _type(a) in ("income", "other income")]
    if kind in ("expense", "fee", "refund"):
        return [a for a in coa if _type(a) in ("expense", "other expense", "cost of goods sold")]
    if kind == "balance_sheet":
        return [a for a in coa if _type(a) in BALANCE_SHEET_ACCOUNT_TYPES]
    if kind == "transfer":
        return [a for a in coa if _type(a) == "bank"]
    return []


def _default_fee_account(coa: list[dict[str, Any]]) -> dict[str, Any] | None:
    for name in default_fee_account_names():
        for row in coa:
            if (row.get("name") or "").lower() == name.lower():
                return row
    for row in coa:
        if row.get("account_type") == "Expense" and "bank" in (row.get("name") or "").lower():
            return row
    return None


def _coa_name(coa: list[dict[str, Any]], qb_account_id: str) -> str | None:
    return _coa_name_from_list(coa, qb_account_id)


def _coa_name_from_list(accounts: list[dict[str, Any]], qb_account_id: str) -> str | None:
    for row in accounts:
        if row.get("qb_account_id") == qb_account_id:
            return row.get("name")
    return None


def _coa_ids(coa: list[dict[str, Any]]) -> set[str]:
    return {str(r["qb_account_id"]) for r in coa if r.get("qb_account_id")}


def _account_valid(coa_ids: set[str], account_id: str | None) -> bool:
    return bool(account_id and account_id in coa_ids)


async def log_posting_decision(
    user_id: str,
    transaction_id: str,
    *,
    suggested_account_id: str | None,
    suggested_account_name: str | None,
    final_account_id: str | None,
    final_account_name: str | None,
    was_accepted: bool,
    edit_made: bool,
    confidence_at_time: float | None,
    method: str,
    reason_text: str | None = None,
    fingerprint_id: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "transaction_id": transaction_id,
        "fingerprint_id": fingerprint_id,
        "suggested_account_id": suggested_account_id,
        "suggested_account_name": suggested_account_name,
        "final_account_id": final_account_id,
        "final_account_name": final_account_name,
        "was_accepted": was_accepted,
        "edit_made": edit_made,
        "confidence_at_time": confidence_at_time,
        "method": _decision_method(method),
        "reason_text": reason_text,
    }
    res = await run_db(lambda: sb.table("posting_decisions").insert(row).execute())
    return (res.data or [row])[0]


def _resolve_status(
    *,
    qb_account_id: str | None,
    payment_account_id: str | None,
    confidence: float,
    method: str | None,
    automation: dict[str, Any] | None,
) -> QbSyncStatus:
    auto_enabled = automation and automation.get("auto_approve_enabled")
    threshold = float((automation or {}).get("auto_approve_threshold") or 0.90)

    status: QbSyncStatus = "needs_review"
    if confidence >= CONFIDENCE_AUTO and payment_account_id and qb_account_id:
        status = "pending"
    elif qb_account_id and payment_account_id and confidence >= CONFIDENCE_LLM_MIN:
        status = "pending"

    if (
        auto_enabled
        and qb_account_id
        and payment_account_id
        and confidence >= threshold
        and method in ("fingerprint", "rag", "rule")
    ):
        status = "auto_approved"
    return status


def classify_transaction(
    txn: dict[str, Any],
    mappings: list[dict[str, Any]],
    user_rules: dict[str, str],
    coa: list[dict[str, Any]],
    coa_ids: set[str],
    *,
    fingerprint_row: dict[str, Any] | None = None,
    learned_kind: PostingKind | None = None,
    rag_result: tuple[str | None, str | None, float, str | None] | None = None,
    automation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account_id = txn.get("account_id")
    category = txn.get("category") or "Uncategorized"
    merchant = txn.get("merchant_name")
    description = txn.get("description")
    kind = detect_posting_kind(txn, learned_kind=learned_kind)
    posting_type = posting_type_for_kind(kind)

    bank_map = _mapping_lookup(mappings, "bank_account", str(account_id)) if account_id else None
    payment_account_id = bank_map.get("qb_account_id") if bank_map else None

    target_accounts = _accounts_for_kind(coa, kind)
    qb_account_id: str | None = None
    qb_account_name: str | None = None
    confidence = 0.5
    method: str | None = None
    reason: str | None = None

    if kind == "fee":
        fee_row = _default_fee_account(coa)
        fee_map = _mapping_lookup(mappings, "category", "Bank Charges")
        if fee_map:
            qb_account_id = fee_map.get("qb_account_id")
            qb_account_name = fee_map.get("qb_account_name")
            confidence = 0.9
            method = "rule"
            reason = "Bank fee — mapped to Bank Charges"
        elif fee_row:
            qb_account_id = str(fee_row["qb_account_id"])
            qb_account_name = fee_row.get("name")
            confidence = 0.88
            method = "rule"
            reason = f"Bank fee — {fee_row.get('name')}"

    cat_map = _mapping_lookup(mappings, "category", category)
    if not qb_account_id and cat_map:
        qb_account_id = cat_map.get("qb_account_id")
        qb_account_name = cat_map.get("qb_account_name")
        confidence = 0.92
        method = "rule"
        reason = f"Category mapping: {category}"
    elif not qb_account_id:
        rule_category: str | None = None
        text = " ".join(filter(None, [merchant, description])).lower()
        for pattern, assigned in user_rules.items():
            if pattern and pattern in text:
                rule_category = assigned
                break
        if rule_category:
            rule_map = _mapping_lookup(mappings, "category", rule_category)
            if rule_map:
                qb_account_id = rule_map.get("qb_account_id")
                qb_account_name = rule_map.get("qb_account_name")
                confidence = 0.88
                method = "rule"
                reason = f"Merchant rule matched '{rule_category}'"
            elif not reason:
                reason = f"Merchant rule matched '{rule_category}' — add category mapping"
                method = "category"
                confidence = min(confidence, 0.55)

    if not qb_account_id and fingerprint_row:
        fp_conf = fingerprint_match_confidence(txn, fingerprint_row)
        fp_acct = fingerprint_row.get("qb_account_id")
        if fp_conf >= CONFIDENCE_FINGERPRINT_MIN and _account_valid(coa_ids, str(fp_acct or "")):
            qb_account_id = str(fp_acct)
            qb_account_name = fingerprint_row.get("qb_account_name")
            confidence = fp_conf
            method = "fingerprint"
            reason = fingerprint_confidence_reason(fingerprint_row)

    if not qb_account_id and rag_result:
        rag_id, rag_name, rag_conf, rag_reason = rag_result
        if rag_id and _account_valid(coa_ids, rag_id):
            qb_account_id = rag_id
            qb_account_name = rag_name
            confidence = rag_conf
            method = "rag"
            reason = rag_reason

    if kind == "income" and not reason:
        reason = "Income / deposit — map to a QuickBooks income account"
    elif kind == "refund" and not reason:
        reason = "Vendor refund — map to the original expense category"

    if kind in ("transfer", "reversal", "balance_sheet"):
        if not reason:
            reason = _auto_detect_reason(txn, kind)
        if not method:
            method = "auto_detect"
        if not qb_account_id:
            confidence = min(confidence, 0.55)
    elif not qb_account_id and category and category != "Uncategorized" and not method:
        reason = f"Category: {category} — map to QuickBooks account"
        method = "category"
        confidence = min(confidence, 0.58)

    if qb_account_id and not payment_account_id:
        confidence = min(confidence, 0.84)

    status = _resolve_status(
        qb_account_id=qb_account_id,
        payment_account_id=payment_account_id,
        confidence=confidence,
        method=method,
        automation=automation,
    )

    fingerprint_id = fingerprint_row.get("id") if fingerprint_row else None

    return {
        "qb_sync_status": status,
        "qb_posting_type": posting_type,
        "qb_confidence": round(confidence, 2),
        "qb_account_id": qb_account_id,
        "qb_account_name": qb_account_name,
        "qb_payment_account_id": payment_account_id,
        "qb_suggestion_method": method,
        "qb_confidence_reason": reason,
        "fingerprint_id": fingerprint_id,
        "payee_pattern": payee_pattern_for_row(txn),
    }


async def _count_unclassified_transactions(user_id: str, active_bank_ids: set[str]) -> int:
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .is_("qb_sync_status", "null")
    )
    query = _apply_books_account_filter(query, active_bank_ids)
    res = await run_db(lambda: query.execute())
    return res.count or 0


async def _fetch_unclassified_batch(
    user_id: str,
    active_bank_ids: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .is_("qb_sync_status", "null")
    )
    query = _apply_books_account_filter(query, active_bank_ids)
    res = await run_db(lambda: query.limit(limit).execute())
    return res.data or []


async def _fetch_legacy_queue_batch(
    user_id: str,
    active_bank_ids: set[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Legacy excluded/failed rows to reclassify into the training queue."""
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .in_("qb_sync_status", list(_LEGACY_REVIEW_STATUSES))
    )
    query = _apply_books_account_filter(query, active_bank_ids)
    res = await run_db(lambda: query.limit(limit).execute())
    return res.data or []


async def _classify_transactions_batch(
    user_id: str,
    txns: list[dict[str, Any]],
    *,
    mappings: list[dict[str, Any]],
    user_rules: dict[str, str],
    coa: list[dict[str, Any]],
    coa_ids: set[str],
    automation: dict[str, Any],
    active_bank_ids: set[str],
    rag_enabled: bool = False,
    allow_reclassify: bool = False,
) -> int:
    sb = get_supabase()
    classified = 0

    for txn in txns:
        if txn.get("archived_at"):
            continue
        if txn.get("account_id") and txn.get("account_id") not in active_bank_ids:
            continue
        if txn.get("qb_sync_status") == "posted":
            continue
        if not allow_reclassify and txn.get("qb_sync_status") in (
            "excluded",
            "skipped",
            "failed",
            "posted",
        ):
            continue

        fp = extract_fingerprint(txn)
        fingerprint_row = await lookup_fingerprint(user_id, fp)
        learned_kind: PostingKind | None = None
        if fingerprint_row:
            await touch_fingerprint_seen(user_id, txn)
            fp_conf = fingerprint_match_confidence(txn, fingerprint_row)
            stored_kind = fingerprint_row.get("posting_kind")
            if fp_conf >= CONFIDENCE_FINGERPRINT_MIN and stored_kind:
                if not (allow_reclassify and stored_kind == "transfer"):
                    learned_kind = stored_kind  # type: ignore[assignment]

        kind = detect_posting_kind(txn, learned_kind=learned_kind)

        rag_result = None
        has_rule = bool(_mapping_lookup(mappings, "category", txn.get("category") or ""))
        if kind == "fee" and _default_fee_account(coa):
            has_rule = True

        fp_hit = (
            fingerprint_row
            and fingerprint_match_confidence(txn, fingerprint_row) >= CONFIDENCE_FINGERPRINT_MIN
        )
        if rag_enabled and not has_rule and not fp_hit:
            rag_result = await rag_classify_hint(user_id, txn, coa_ids)

        update = classify_transaction(
            txn,
            mappings,
            user_rules,
            coa,
            coa_ids,
            fingerprint_row=fingerprint_row,
            learned_kind=learned_kind,
            rag_result=rag_result,
            automation=automation,
        )
        if allow_reclassify:
            new_cat = _refreshed_category(txn, user_rules)
            if new_cat:
                update["category"] = new_cat
            if txn.get("qb_sync_status") in _LEGACY_REVIEW_STATUSES:
                update["qb_error"] = None
        await run_db(
            lambda t=txn["id"], u=update: sb.table("transactions")
            .update(u)
            .eq("id", t)
            .eq("user_id", user_id)
            .execute()
        )
        classified += 1

    return classified


async def classify_user_transactions(
    user_id: str,
    transaction_ids: list[str] | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    _, active_bank_ids = await _active_bank_accounts(user_id)
    if not active_bank_ids:
        return {"classified": 0, "remaining_unclassified": 0}

    mappings = await get_mappings(user_id)
    user_rules = await load_user_category_rules(user_id, sb)
    coa = await list_coa(user_id)
    coa_ids = _coa_ids(coa)
    automation = await get_user_automation(user_id)
    rag_enabled = await user_has_posting_memory(user_id)

    total_classified = 0

    if transaction_ids:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .in_("id", transaction_ids)
            .limit(500)
            .execute()
        )
        txns = res.data or []
        total_classified = await _classify_transactions_batch(
            user_id,
            txns,
            mappings=mappings,
            user_rules=user_rules,
            coa=coa,
            coa_ids=coa_ids,
            automation=automation,
            active_bank_ids=active_bank_ids,
            rag_enabled=rag_enabled,
            allow_reclassify=True,
        )
    else:
        while total_classified < CLASSIFY_MAX_ROWS:
            txns = await _fetch_unclassified_batch(
                user_id, active_bank_ids, limit=CLASSIFY_BATCH_SIZE
            )
            if not txns:
                break
            batch_count = await _classify_transactions_batch(
                user_id,
                txns,
                mappings=mappings,
                user_rules=user_rules,
                coa=coa,
                coa_ids=coa_ids,
                automation=automation,
                active_bank_ids=active_bank_ids,
                rag_enabled=rag_enabled,
            )
            total_classified += batch_count
            if len(txns) < CLASSIFY_BATCH_SIZE:
                break

        while total_classified < CLASSIFY_MAX_ROWS:
            txns = await _fetch_legacy_queue_batch(
                user_id, active_bank_ids, limit=CLASSIFY_BATCH_SIZE
            )
            if not txns:
                break
            batch_count = await _classify_transactions_batch(
                user_id,
                txns,
                mappings=mappings,
                user_rules=user_rules,
                coa=coa,
                coa_ids=coa_ids,
                automation=automation,
                active_bank_ids=active_bank_ids,
                rag_enabled=rag_enabled,
                allow_reclassify=True,
            )
            total_classified += batch_count
            if batch_count == 0 or len(txns) < CLASSIFY_BATCH_SIZE:
                break

    remaining = await _count_unclassified_transactions(user_id, active_bank_ids)
    return {"classified": total_classified, "remaining_unclassified": remaining}


def _apply_books_queue_status_filter(query: Any, status: str | None) -> Any:
    if status == "unclassified":
        return query.is_("qb_sync_status", "null")
    if status == "failed":
        return query.or_(_FAILED_QUEUE_OR)
    if status == "needs_review":
        return query.or_(_NEEDS_REVIEW_QUEUE_OR)
    if status:
        return query.eq("qb_sync_status", status)
    return query.not_.is_("qb_sync_status", "null")


async def _count_books_queue_status(
    user_id: str,
    active_bank_ids: set[str],
    status: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
    )
    query = _apply_books_account_filter(query, active_bank_ids)
    query = _apply_books_queue_status_filter(query, status)
    query = _apply_books_queue_date_filter(query, date_from=date_from, date_to=date_to)
    res = await run_db(lambda: query.execute())
    return res.count or 0


def _apply_books_queue_date_filter(
    query: Any,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Any:
    if date_from:
        query = query.gte("transaction_date", date_from[:10])
    if date_to:
        query = query.lte("transaction_date", date_to[:10])
    return query


async def get_queue(
    user_id: str,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    bank_accounts, active_bank_ids = await _active_bank_accounts(user_id)
    if not active_bank_ids:
        return {"items": [], "total": 0, "page": page, "limit": limit, "total_pages": 1}

    query = (
        sb.table("transactions")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
    )
    query = _apply_books_account_filter(query, active_bank_ids)
    query = _apply_books_queue_status_filter(query, status)
    query = _apply_books_queue_date_filter(query, date_from=date_from, date_to=date_to)

    offset = (page - 1) * limit
    res = await run_db(
        lambda: query.order("transaction_date", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    bank_map = {r["id"]: r.get("account_name") for r in bank_accounts}

    items = []
    for row in res.data or []:
        aid = row.get("account_id")
        enriched = {**row, "account_name": bank_map.get(aid) if aid else None}
        enriched["posted_date"] = row.get("qb_posted_at")
        items.append(enriched)

    total = res.count or 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, math.ceil(total / limit)) if total else 1,
    }


async def get_queue_groups(
    user_id: str,
    status: str = "pending",
) -> list[dict[str, Any]]:
    _, active_bank_ids = await _active_bank_accounts(user_id)
    if not active_bank_ids:
        return []

    def _status_filter(q: Any) -> Any:
        if status == "unclassified":
            return q.is_("qb_sync_status", "null")
        return q.eq("qb_sync_status", status)

    rows = await iter_scoped_transactions(
        user_id, active_bank_ids, extra_filter=_status_filter
    )
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("payee_pattern") or row.get("merchant_name") or "unknown"
        if key not in groups:
            groups[key] = {
                "payee_pattern": key,
                "count": 0,
                "total_amount": 0.0,
                "qb_account_id": row.get("qb_account_id"),
                "qb_account_name": row.get("qb_account_name"),
                "qb_confidence": row.get("qb_confidence"),
                "qb_suggestion_method": row.get("qb_suggestion_method"),
                "transaction_ids": [],
            }
        g = groups[key]
        g["count"] += 1
        g["total_amount"] += abs(float(row.get("amount") or 0))
        g["transaction_ids"].append(row["id"])
        if row.get("qb_confidence") and (g.get("qb_confidence") or 0) < row.get("qb_confidence"):
            g["qb_confidence"] = row.get("qb_confidence")
            g["qb_account_id"] = row.get("qb_account_id")
            g["qb_account_name"] = row.get("qb_account_name")
    return sorted(groups.values(), key=lambda x: -x["count"])


async def get_books_readiness(user_id: str) -> dict[str, Any]:
    from app.services.quickbooks_service import get_connection_status

    bank_accounts, _ = await _active_bank_accounts(user_id)
    qb_status = await get_connection_status(user_id)

    return {
        "qb_connected": bool(qb_status.get("connected")),
        "qb_environment": qb_status.get("environment"),
        "qb_account_name": qb_status.get("account_name"),
        "bank_connected": len(bank_accounts) > 0,
        "bank_accounts": [
            {
                "id": a["id"],
                "account_name": a.get("account_name"),
                "provider": a.get("provider"),
                "last_synced_at": a.get("last_synced_at"),
            }
            for a in bank_accounts
        ],
    }


async def get_summary(
    user_id: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    _, active_bank_ids = await _active_bank_accounts(user_id)
    counts: dict[str, int] = {}
    coverage = {
        "total_bank_transactions": 0,
        "classified": 0,
        "unclassified": 0,
    }
    if active_bank_ids:
        count_tasks = [
            count_scoped_transactions(
                user_id, active_bank_ids, unclassified=True, date_from=date_from, date_to=date_to
            ),
            *[
                count_scoped_transactions(
                    user_id,
                    active_bank_ids,
                    qb_sync_status=st,
                    date_from=date_from,
                    date_to=date_to,
                )
                for st in SUMMARY_STATUSES
            ],
            _count_books_queue_status(
                user_id, active_bank_ids, "needs_review", date_from=date_from, date_to=date_to
            ),
            _count_books_queue_status(
                user_id, active_bank_ids, "failed", date_from=date_from, date_to=date_to
            ),
        ]
        results = await asyncio.gather(*count_tasks)
        unclassified = results[0]
        counts["unclassified"] = unclassified
        coverage["unclassified"] = unclassified

        for st, n in zip(SUMMARY_STATUSES, results[1 : 1 + len(SUMMARY_STATUSES)], strict=True):
            if n:
                counts[st] = n

        needs_review = results[1 + len(SUMMARY_STATUSES)]
        failed = results[2 + len(SUMMARY_STATUSES)]
        if needs_review:
            counts["needs_review"] = needs_review
        if failed:
            counts["failed"] = failed

        coverage["total_bank_transactions"] = sum(counts.values())
        coverage["classified"] = coverage["total_bank_transactions"] - unclassified

    automation = await get_user_automation(user_id)
    readiness = await get_books_readiness(user_id)
    return {"counts": counts, "coverage": coverage, "automation": automation, "readiness": readiness}


async def exclude_transaction(user_id: str, transaction_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .update({"qb_sync_status": "excluded", "qb_posting_type": "transfer"})
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise ValueError("Transaction not found")
    return res.data[0]


RevertTarget = Literal["needs_review", "unclassified"]

_REVERT_TARGETS: dict[str, set[str]] = {
    "needs_review": {"unclassified"},
    "pending": {"needs_review", "unclassified"},
    "auto_approved": {"needs_review", "unclassified"},
    "failed": {"needs_review", "unclassified"},
    "excluded": {"needs_review", "unclassified"},
}

_QB_RESET_FIELDS = {
    "qb_sync_status": None,
    "qb_account_id": None,
    "qb_account_name": None,
    "qb_payment_account_id": None,
    "qb_confidence": None,
    "qb_suggestion_method": None,
    "qb_confidence_reason": None,
    "qb_posting_type": None,
    "qb_entity_id": None,
    "qb_posted_at": None,
    "qb_error": None,
    "posting_intent": None,
}


async def revert_transaction(
    user_id: str,
    transaction_id: str,
    target: RevertTarget,
) -> dict[str, Any]:
    sb = get_supabase()
    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    txn = txn_res.data
    if not txn:
        raise ValueError("Transaction not found")

    current = txn.get("qb_sync_status")
    if current == "posted":
        raise ValueError("Posted transactions cannot be moved back")
    if not current:
        raise ValueError("Transaction is not in the books queue")

    allowed = set(_REVERT_TARGETS.get(current, set()))
    if current == "needs_review" and txn.get("qb_error") and target == "needs_review":
        allowed.add("needs_review")
    if target not in allowed:
        raise ValueError(f"Cannot move from {current} to {target}")

    if target == "needs_review":
        if current == "pending":
            await reject_suggestion(user_id, transaction_id)
        else:
            await run_db(
                lambda: sb.table("transactions")
                .update(
                    {
                        "qb_sync_status": "needs_review",
                        "qb_error": None,
                    }
                )
                .eq("id", transaction_id)
                .eq("user_id", user_id)
                .execute()
            )
    else:
        await run_db(
            lambda: sb.table("transactions")
            .update(_QB_RESET_FIELDS)
            .eq("id", transaction_id)
            .eq("user_id", user_id)
            .execute()
        )

    refreshed = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return {
        "transaction_id": transaction_id,
        "previous_status": current,
        "target": target,
        "transaction": refreshed.data,
    }


async def set_posting_intent(
    user_id: str,
    transaction_id: str,
    intent: Literal["expense", "income", "transfer", "personal", "fee"],
) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .update({"posting_intent": intent, "qb_sync_status": None})
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise ValueError("Transaction not found")
    await classify_user_transactions(user_id, [transaction_id])
    refreshed = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .single()
        .execute()
    )
    return refreshed.data


async def propagate_payee_suggestions(
    user_id: str,
    txn: dict[str, Any],
    fp_row: dict[str, Any],
    *,
    exclude_transaction_id: str | None = None,
    exclude_transaction_ids: set[str] | None = None,
) -> int:
    """Apply a trained payee fingerprint to similar rows still in New/Review."""
    if not fingerprint_is_trained(fp_row):
        return 0

    payee = fp_row.get("payee_pattern") or payee_pattern_for_row(txn)
    if not payee or payee == "unknown":
        return 0

    exclude_ids = set(exclude_transaction_ids or [])
    if exclude_transaction_id:
        exclude_ids.add(exclude_transaction_id)

    sb = get_supabase()
    mappings = await get_mappings(user_id)
    coa = await list_coa(user_id)
    coa_ids = _coa_ids(coa)
    automation = await get_user_automation(user_id)

    candidates = await _payee_propagation_candidates(
        user_id,
        payee,
        exclude_ids=exclude_ids,
    )

    updates: list[tuple[str, dict[str, Any]]] = []
    for row in candidates.values():
        patch = _fingerprint_prefill_patch(
            row,
            fp_row,
            mappings,
            coa_ids,
            automation,
            propagation=True,
        )
        if patch:
            updates.append((row["id"], patch))

    updated = 0
    for i in range(0, len(updates), PROPAGATE_BATCH_SIZE):
        batch = updates[i : i + PROPAGATE_BATCH_SIZE]

        async def _apply(txn_id: str, patch: dict[str, Any]) -> None:
            await run_db(
                lambda t=txn_id, u=patch: sb.table("transactions")
                .update(u)
                .eq("id", t)
                .eq("user_id", user_id)
                .execute()
            )

        await asyncio.gather(*[_apply(txn_id, patch) for txn_id, patch in batch])
        updated += len(batch)
    return updated


async def approve_transaction(
    user_id: str,
    transaction_id: str,
    final_account_id: str,
    *,
    post: bool = False,
    payment_account_id: str | None = None,
    propagate_similar: bool = True,
    final_party_id: str | None = None,
    final_party_type: str | None = None,
    closed_period_path: str | None = None,
    closed_period_reason: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    txn = txn_res.data
    if not txn:
        raise ValueError("Transaction not found")

    coa, coa_ids = await _coa_validated_for_accounts(
        user_id, final_account_id, txn.get("qb_payment_account_id")
    )
    if not _account_valid(coa_ids, final_account_id):
        raise ValueError("Invalid QuickBooks account")

    coa_row = next((r for r in coa if r.get("qb_account_id") == final_account_id), None)
    if not coa_row:
        raise ValueError("Invalid QuickBooks account")

    suggested_id = txn.get("qb_account_id")
    suggested_name = txn.get("qb_account_name")
    edit_made = bool(suggested_id and suggested_id != final_account_id)
    final_name = _coa_name(coa, final_account_id)
    approved_kind = posting_kind_for_coa_account(
        coa_row.get("account_type"),
        transaction_type=txn.get("transaction_type"),
    )
    detected_kind = detect_posting_kind(txn)

    if not payment_account_id:
        account_id = txn.get("account_id")
        mappings = await get_mappings(user_id)
        bank_map = _mapping_lookup(mappings, "bank_account", str(account_id)) if account_id else None
        payment_account_id = bank_map.get("qb_account_id") if bank_map else txn.get("qb_payment_account_id")

    if approved_kind == "transfer":
        if str(final_account_id) == str(payment_account_id or ""):
            raise ValueError("Transfer requires a different QuickBooks bank account")

    if payment_account_id and not _account_valid(coa_ids, payment_account_id):
        coa, coa_ids = await _coa_validated_for_accounts(user_id, final_account_id, payment_account_id)

    _require_accounts_in_coa(
        coa,
        payment_account_id,
        label="Payment bank account",
    )

    party_id: str | None = None
    party_name: str | None = None
    party_type: str | None = None
    if final_party_id and final_party_type:
        party_id, party_name = await validate_party(user_id, final_party_id, final_party_type)  # type: ignore[arg-type]
        party_type = final_party_type

    fp_row = await upsert_fingerprint_from_decision(
        user_id,
        txn,
        final_account_id,
        final_name,
        posting_kind=approved_kind,
        qb_party_id=party_id,
        qb_party_type=party_type,
        qb_party_name=party_name,
    )

    decision = await log_posting_decision(
        user_id,
        transaction_id,
        suggested_account_id=suggested_id,
        suggested_account_name=suggested_name,
        final_account_id=final_account_id,
        final_account_name=final_name,
        was_accepted=True,
        edit_made=edit_made,
        confidence_at_time=float(txn.get("qb_confidence") or 0),
        method=txn.get("qb_suggestion_method") or "manual",
        reason_text=txn.get("qb_confidence_reason"),
        fingerprint_id=fp_row.get("id"),
    )

    asyncio.create_task(
        _schedule_posting_memory(
            user_id,
            txn,
            final_account_id,
            final_name,
            fp_row.get("id"),
            decision.get("id"),
        )
    )

    recurrence = int(fp_row.get("recurrence_count") or 0)
    if recurrence >= 3 and txn.get("category"):
        await upsert_mapping(
            user_id,
            "category",
            txn["category"],
            final_account_id,
            final_name,
        )

    update = {
        "qb_account_id": final_account_id,
        "qb_account_name": final_name,
        "qb_payment_account_id": payment_account_id,
        "fingerprint_id": fp_row.get("id"),
        "posting_intent": posting_kind_to_intent(approved_kind),
        "qb_posting_type": posting_type_for_approval(
            transaction_type=txn.get("transaction_type"),
            offset_account_type=coa_row.get("account_type"),
            detected_kind=detected_kind,
        ),
        "qb_suggestion_method": "manual",
        "qb_sync_status": "pending",
        "qb_doc_number": txn_doc_number(txn),
    }
    if final_party_id is not None or final_party_type is not None:
        update["qb_party_id"] = party_id
        update["qb_party_type"] = party_type
        update["qb_party_name"] = party_name
    await run_db(
        lambda: sb.table("transactions").update(update).eq("id", transaction_id).execute()
    )

    similar_updated = 0
    if propagate_similar:
        similar_updated = await propagate_payee_suggestions(
            user_id,
            txn,
            fp_row,
            exclude_transaction_id=transaction_id,
        )

    result: dict[str, Any] = {
        "approved": True,
        "transaction_id": transaction_id,
        "decision": decision,
        "similar_updated": similar_updated,
    }
    if post:
        result["post"] = await post_transaction(
            user_id,
            transaction_id,
            closed_period_path=closed_period_path,
            closed_period_reason=closed_period_reason,
        )
    else:
        result["transaction"] = {**txn, **update}
    return result


async def approve_transactions_bulk(
    user_id: str,
    transaction_ids: list[str] | None = None,
    payee_pattern: str | None = None,
    *,
    items: list[dict[str, str]] | None = None,
    post: bool = False,
    final_account_id: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    work: list[dict[str, str | None]] = []

    if items:
        work = [
            {
                "transaction_id": str(i["transaction_id"]),
                "final_account_id": str(i["final_account_id"]),
                "final_party_id": i.get("final_party_id"),
                "final_party_type": i.get("final_party_type"),
            }
            for i in items
        ]
    elif payee_pattern:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("id, qb_account_id")
            .eq("user_id", user_id)
            .eq("payee_pattern", payee_pattern)
            .in_("qb_sync_status", ["pending", "needs_review"])
            .execute()
        )
        if not final_account_id and res.data:
            final_account_id = res.data[0].get("qb_account_id")
        if not final_account_id:
            raise ValueError("final_account_id required for bulk approve")
        work = [
            {"transaction_id": r["id"], "final_account_id": final_account_id, "final_party_id": None, "final_party_type": None}
            for r in (res.data or [])
        ]
    elif transaction_ids and final_account_id:
        work = [
            {"transaction_id": tid, "final_account_id": final_account_id, "final_party_id": None, "final_party_type": None}
            for tid in transaction_ids
        ]

    if not work:
        return {"approved": 0, "failed": 0, "similar_updated": 0, "errors": []}

    account_ids = {str(item["final_account_id"]) for item in work}
    await _coa_validated_for_accounts(user_id, *account_ids)

    approved = 0
    similar_updated = 0
    errors: list[dict[str, str]] = []
    propagated_payees: set[str] = set()
    approved_ids: set[str] = set()

    for item in work:
        tid = str(item["transaction_id"])
        acct_id = str(item["final_account_id"])
        try:
            await approve_transaction(
                user_id,
                tid,
                acct_id,
                post=post,
                propagate_similar=False,
                final_party_id=item.get("final_party_id"),
                final_party_type=item.get("final_party_type"),
            )
            approved += 1
            approved_ids.add(tid)
        except ValueError as exc:
            errors.append({"transaction_id": tid, "error": str(exc)})

    failed_ids = {e["transaction_id"] for e in errors}
    for item in work:
        tid = str(item["transaction_id"])
        if tid in failed_ids:
            continue
        txn_res = await run_db(
            lambda t=tid: sb.table("transactions")
            .select("*")
            .eq("id", t)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        txn = txn_res.data
        if not txn:
            continue
        payee = payee_pattern_for_row(txn)
        if not payee or payee == "unknown" or payee in propagated_payees:
            continue
        fp_row = await lookup_fingerprint_by_payee(user_id, payee)
        if fp_row:
            similar_updated += await propagate_payee_suggestions(
                user_id,
                txn,
                fp_row,
                exclude_transaction_ids=approved_ids,
            )
            propagated_payees.add(payee)

    return {
        "approved": approved,
        "failed": len(errors),
        "similar_updated": similar_updated,
        "errors": errors,
    }


async def reject_suggestion(user_id: str, transaction_id: str) -> dict[str, Any]:
    sb = get_supabase()
    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    txn = txn_res.data
    if not txn:
        raise ValueError("Transaction not found")

    fp = extract_fingerprint(txn)
    fp_row = await lookup_fingerprint(user_id, fp)

    await log_posting_decision(
        user_id,
        transaction_id,
        suggested_account_id=txn.get("qb_account_id"),
        suggested_account_name=txn.get("qb_account_name"),
        final_account_id=None,
        final_account_name=None,
        was_accepted=False,
        edit_made=False,
        confidence_at_time=float(txn.get("qb_confidence") or 0),
        method=txn.get("qb_suggestion_method") or "manual",
        fingerprint_id=fp_row.get("id") if fp_row else None,
    )

    if fp_row:
        await recalculate_fingerprint_confidence(user_id, fp_row["id"])

    await run_db(
        lambda: sb.table("transactions")
        .update(
            {
                "qb_sync_status": "needs_review",
                "qb_account_id": None,
                "qb_account_name": None,
                "qb_suggestion_method": None,
                "qb_confidence_reason": "User rejected suggestion",
            }
        )
        .eq("id", transaction_id)
        .execute()
    )
    return {"rejected": True, "transaction_id": transaction_id}


def _apply_entity_and_doc(payload: dict[str, Any], txn: dict[str, Any]) -> dict[str, Any]:
    entity = entity_ref_for_txn(txn)
    if entity:
        payload["EntityRef"] = entity
    doc = txn.get("qb_doc_number") or txn_doc_number(txn)
    if doc:
        payload["DocNumber"] = doc
    return payload


def _deposit_line_entity(txn: dict[str, Any]) -> dict[str, str] | None:
    """QuickBooks expects customer/vendor on DepositLineDetail.Entity, not header EntityRef."""
    party_id = txn.get("qb_party_id")
    party_type = txn.get("qb_party_type")
    if not party_id or party_type not in ("Vendor", "Customer"):
        return None
    type_map = {"Vendor": "VENDOR", "Customer": "CUSTOMER"}
    return {"value": str(party_id), "type": type_map[party_type]}


def _apply_doc_number(payload: dict[str, Any], txn: dict[str, Any]) -> dict[str, Any]:
    doc = txn.get("qb_doc_number") or txn_doc_number(txn)
    if doc:
        payload["DocNumber"] = doc
    return payload


def _effective_txn_date(txn: dict[str, Any], *, override_date: str | None = None) -> str:
    if override_date:
        return override_date[:10]
    return str(txn.get("transaction_date") or "")[:10]


def _assert_qbo_txn_date(txn: dict[str, Any], payload: dict[str, Any], *, allow_override: bool = False) -> None:
    expected = _effective_txn_date(txn)
    actual = str(payload.get("TxnDate") or "")[:10]
    if allow_override:
        return
    if actual != expected:
        raise ValueError(
            f"QBO TxnDate must equal transaction_date ({expected}); got {actual or 'missing'}"
        )


def is_closed_period_error(error: str) -> bool:
    lowered = error.lower()
    needles = ("closed", "books closed", "account period", "invalid date", "period has closed")
    return any(n in lowered for n in needles)


async def _log_posting_adjustment(
    user_id: str,
    transaction_id: str,
    *,
    path: str,
    requested_txn_date: str,
    actual_txn_date: str,
    reason: str | None = None,
) -> None:
    sb = get_supabase()
    await run_db(
        lambda: sb.table("posting_adjustments")
        .insert(
            {
                "user_id": user_id,
                "transaction_id": transaction_id,
                "path": path,
                "requested_txn_date": requested_txn_date[:10],
                "actual_txn_date": actual_txn_date[:10],
                "reason": reason,
            }
        )
        .execute()
    )


def _build_deposit_payload(txn: dict[str, Any], *, txn_date: str | None = None) -> dict[str, Any]:
    amount = abs(float(txn.get("amount") or 0))
    txn_date_val = _effective_txn_date(txn, override_date=txn_date)
    merchant = txn.get("merchant_name") or txn.get("description") or "Deposit"
    deposit_line_detail: dict[str, Any] = {
        "AccountRef": {"value": str(txn["qb_account_id"])},
    }
    line_entity = _deposit_line_entity(txn)
    if line_entity:
        deposit_line_detail["Entity"] = line_entity
    line: dict[str, Any] = {
        "Amount": amount,
        "DetailType": "DepositLineDetail",
        "DepositLineDetail": deposit_line_detail,
    }
    if merchant:
        line["Description"] = merchant[:4000]
    payload = {
        "DepositToAccountRef": {"value": str(txn["qb_payment_account_id"])},
        "TxnDate": txn_date_val,
        "PrivateNote": f"FinSight:{txn['id']}",
        "Line": [line],
    }
    return _apply_doc_number(payload, txn)


def _build_purchase_payload(txn: dict[str, Any], *, txn_date: str | None = None) -> dict[str, Any]:
    amount = abs(float(txn.get("amount") or 0))
    txn_date_val = _effective_txn_date(txn, override_date=txn_date)
    merchant = txn.get("merchant_name") or txn.get("description") or "Expense"
    payload = {
        "PaymentType": "Cash",
        "AccountRef": {"value": str(txn["qb_payment_account_id"])},
        "TxnDate": txn_date_val,
        "PrivateNote": f"FinSight:{txn['id']}",
        "Line": [
            {
                "Amount": amount,
                "Description": merchant[:4000] if merchant else None,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": str(txn["qb_account_id"])},
                },
            }
        ],
    }
    return _apply_entity_and_doc(payload, txn)


def _build_transfer_payload(txn: dict[str, Any], *, txn_date: str | None = None) -> dict[str, Any]:
    amount = abs(float(txn.get("amount") or 0))
    txn_date_val = _effective_txn_date(txn, override_date=txn_date)
    feed_bank = str(txn["qb_payment_account_id"])
    other_bank = str(txn["qb_account_id"])
    if (txn.get("transaction_type") or "").lower() == "credit":
        from_ref, to_ref = other_bank, feed_bank
    else:
        from_ref, to_ref = feed_bank, other_bank
    return {
        "TxnDate": txn_date_val,
        "Amount": amount,
        "PrivateNote": f"FinSight:{txn['id']}",
        "FromAccountRef": {"value": from_ref},
        "ToAccountRef": {"value": to_ref},
    }


async def post_transaction(
    user_id: str,
    transaction_id: str,
    *,
    is_auto: bool = False,
    closed_period_path: str | None = None,
    closed_period_reason: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()

    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    txn = txn_res.data
    if not txn:
        raise ValueError("Transaction not found")

    if txn.get("qb_sync_status") == "posted" and txn.get("qb_entity_id"):
        return {"skipped": True, "reason": "already_posted", "transaction": txn}

    if not txn.get("qb_account_id") or not txn.get("qb_payment_account_id"):
        await classify_user_transactions(user_id, [transaction_id])
        txn_res = await run_db(
            lambda: sb.table("transactions")
            .select("*")
            .eq("id", transaction_id)
            .single()
            .execute()
        )
        txn = txn_res.data

    if not txn.get("qb_account_id") or not txn.get("qb_payment_account_id"):
        raise ValueError("Missing QB account mapping. Configure mappings first.")

    await ensure_coa_synced(user_id)
    coa = await list_coa(user_id)
    _require_accounts_in_coa(
        coa,
        txn.get("qb_account_id"),
        txn.get("qb_payment_account_id"),
        label="QuickBooks account",
    )

    coa_row = next(
        (r for r in coa if r.get("qb_account_id") == txn.get("qb_account_id")),
        None,
    )
    offset_type = (coa_row or {}).get("account_type")
    posting_type = txn.get("qb_posting_type") or "expense"
    entity = resolve_posting_entity(txn.get("transaction_type"), offset_type)
    if posting_type == "refund":
        entity = "deposit"

    requested_date = _effective_txn_date(txn)
    override_txn_date: str | None = None
    if closed_period_path == "catch_up_today":
        override_txn_date = datetime.now(timezone.utc).date().isoformat()
    elif closed_period_path == "true_date":
        override_txn_date = None

    if entity == "transfer":
        if str(txn.get("qb_account_id")) == str(txn.get("qb_payment_account_id")):
            raise ValueError("Transfer requires two different bank accounts")
        payload = _build_transfer_payload(txn, txn_date=override_txn_date)
        api_path = "/transfer?minorversion=75"
        entity_type = "Transfer"
    elif entity == "deposit":
        payload = _build_deposit_payload(txn, txn_date=override_txn_date)
        api_path = "/deposit?minorversion=75"
        entity_type = "Deposit"
    else:
        payload = _build_purchase_payload(txn, txn_date=override_txn_date)
        api_path = "/purchase?minorversion=75"
        entity_type = "Purchase"

    allow_override = closed_period_path == "catch_up_today"
    _assert_qbo_txn_date(txn, payload, allow_override=allow_override)

    last_error: str | None = None
    for attempt in range(2):
        try:
            data = await qb_company_post_json(user_id, api_path, payload)
            entity = data.get(entity_type) or {}
            entity_id = str(entity.get("Id", ""))
            now = datetime.now(timezone.utc).isoformat()
            update = {
                "qb_sync_status": "posted",
                "qb_entity_type": entity_type,
                "qb_entity_id": entity_id,
                "qb_posted_at": now,
                "qb_error": None,
            }
            res = await run_db(
                lambda: sb.table("transactions")
                .update(update)
                .eq("id", transaction_id)
                .eq("user_id", user_id)
                .execute()
            )
            if is_auto:
                await log_posting_decision(
                    user_id,
                    transaction_id,
                    suggested_account_id=txn.get("qb_account_id"),
                    suggested_account_name=txn.get("qb_account_name"),
                    final_account_id=txn.get("qb_account_id"),
                    final_account_name=txn.get("qb_account_name"),
                    was_accepted=True,
                    edit_made=False,
                    confidence_at_time=float(txn.get("qb_confidence") or 0),
                    method="auto",
                    fingerprint_id=txn.get("fingerprint_id"),
                )
            if closed_period_path:
                await _log_posting_adjustment(
                    user_id,
                    transaction_id,
                    path=closed_period_path,
                    requested_txn_date=requested_date,
                    actual_txn_date=str(payload.get("TxnDate") or "")[:10],
                    reason=closed_period_reason,
                )
            return {"posted": True, "qb_entity_id": entity_id, "transaction": (res.data or [txn])[0]}
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0 and "401" in last_error:
                continue
            break

    err = last_error or "Post failed"
    if is_closed_period_error(err) and not closed_period_path:
        raise ValueError(f"CLOSED_PERIOD:{requested_date}")
    await run_db(
        lambda: sb.table("transactions")
        .update(
            {
                "qb_sync_status": "needs_review",
                "qb_error": err[:2000],
                "qb_confidence_reason": f"Post failed: {err[:500]}",
            }
        )
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .execute()
    )
    raise ValueError(err)


async def post_transactions_bulk(user_id: str, transaction_ids: list[str]) -> dict[str, Any]:
    posted = 0
    skipped = 0
    failed = 0
    errors: list[dict[str, str]] = []

    for tid in transaction_ids:
        try:
            result = await post_transaction(user_id, tid)
            if result.get("skipped"):
                skipped += 1
            else:
                posted += 1
        except ValueError as exc:
            failed += 1
            errors.append({"transaction_id": tid, "error": str(exc)})

    return {"posted": posted, "skipped": skipped, "failed": failed, "errors": errors}


async def auto_post_approved_transactions() -> dict[str, int]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("id, user_id")
        .eq("qb_sync_status", "auto_approved")
        .is_("qb_entity_id", "null")
        .limit(200)
        .execute()
    )
    posted = 0
    failed = 0
    for row in res.data or []:
        try:
            await post_transaction(row["user_id"], row["id"], is_auto=True)
            posted += 1
        except ValueError:
            failed += 1
    return {"posted": posted, "failed": failed}


async def ensure_coa_synced(user_id: str) -> dict[str, Any]:
    """Always pull the latest Chart of Accounts from QuickBooks (with stale purge)."""
    return await sync_chart_of_accounts(user_id)


async def _coa_validated_for_accounts(
    user_id: str, *account_ids: str
) -> tuple[list[dict[str, Any]], set[str]]:
    """Use cached COA when possible; sync from QuickBooks only if an account is missing."""
    coa = await list_coa(user_id)
    coa_ids = _account_ids_set(coa)
    needed = {str(a) for a in account_ids if a}
    if needed and not needed.issubset(coa_ids):
        await sync_chart_of_accounts(user_id)
        coa = await list_coa(user_id)
        coa_ids = _account_ids_set(coa)
    return coa, coa_ids


PROPAGATE_BATCH_SIZE = 25
PROPAGATE_SCAN_BATCH = 500
PROPAGATE_SCAN_MAX = 5000


async def _payee_propagation_candidates(
    user_id: str,
    payee: str,
    *,
    exclude_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Rows in New/Review that share a payee (stored or derived from narration)."""
    if not payee or payee == "unknown":
        return {}

    sb = get_supabase()
    candidates: dict[str, dict[str, Any]] = {}
    offset = 0

    while offset < PROPAGATE_SCAN_MAX:
        res = await run_db(
            lambda off=offset: sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .in_("qb_sync_status", ["needs_review", "unclassified"])
            .order("transaction_date", desc=True)
            .range(off, off + PROPAGATE_SCAN_BATCH - 1)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            row_id = str(row.get("id") or "")
            if not row_id or row_id in exclude_ids:
                continue
            if payee_pattern_for_row(row) != payee:
                continue
            candidates[row_id] = row
        if len(rows) < PROPAGATE_SCAN_BATCH:
            break
        offset += PROPAGATE_SCAN_BATCH

    return candidates


def _fingerprint_prefill_patch(
    txn: dict[str, Any],
    fp_row: dict[str, Any],
    mappings: list[dict[str, Any]],
    coa_ids: set[str],
    automation: dict[str, Any] | None,
    *,
    propagation: bool = False,
) -> dict[str, Any] | None:
    kind = detect_posting_kind(txn)
    if kind == "reversal":
        return None
    fp_kind = fp_row.get("posting_kind")
    if kind in ("transfer", "balance_sheet") and fp_kind != kind:
        return None

    account_id = str(fp_row.get("qb_account_id") or "")
    if not account_id or not _account_valid(coa_ids, account_id):
        return None

    if propagation:
        if payee_pattern_for_row(txn) != fp_row.get("payee_pattern"):
            return None
        confidence = fingerprint_propagation_confidence(txn, fp_row)
    else:
        confidence = fingerprint_match_confidence(txn, fp_row)
    if confidence < CONFIDENCE_FINGERPRINT_MIN:
        return None

    bank_id = txn.get("account_id")
    bank_map = _mapping_lookup(mappings, "bank_account", str(bank_id)) if bank_id else None
    payment_account_id = bank_map.get("qb_account_id") if bank_map else txn.get("qb_payment_account_id")

    if propagation and account_id and payment_account_id:
        status: QbSyncStatus = "pending"
    else:
        status = _resolve_status(
            qb_account_id=account_id,
            payment_account_id=payment_account_id,
            confidence=confidence,
            method="fingerprint",
            automation=automation,
        )

    row_payee = payee_pattern_for_row(txn)

    patch: dict[str, Any] = {
        "qb_account_id": account_id,
        "qb_account_name": fp_row.get("qb_account_name"),
        "qb_payment_account_id": payment_account_id,
        "fingerprint_id": fp_row.get("id"),
        "qb_suggestion_method": "fingerprint",
        "qb_confidence": round(confidence, 2),
        "qb_confidence_reason": fingerprint_confidence_reason(fp_row),
        "qb_sync_status": status,
        "qb_posting_type": posting_type_for_kind(fp_kind or kind),
        "posting_intent": posting_kind_to_intent(fp_kind or kind),
        "payee_pattern": row_payee,
    }
    if fp_row.get("qb_party_id") and fp_row.get("qb_party_type"):
        patch["qb_party_id"] = fp_row.get("qb_party_id")
        patch["qb_party_type"] = fp_row.get("qb_party_type")
        patch["qb_party_name"] = fp_row.get("qb_party_name")
    doc = txn_doc_number(txn)
    if doc:
        patch["qb_doc_number"] = doc
    return patch


async def _schedule_posting_memory(
    user_id: str,
    txn: dict[str, Any],
    final_account_id: str,
    final_name: str | None,
    fingerprint_id: str | None,
    posting_decision_id: str | None,
) -> None:
    try:
        await store_posting_memory(
            user_id,
            txn,
            final_account_id,
            final_name,
            fingerprint_id=fingerprint_id,
            posting_decision_id=posting_decision_id,
            method="manual",
        )
    except Exception:
        logger.exception("Background posting memory failed for txn %s", txn.get("id"))


async def get_learning_progress(user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    automation = await get_user_automation(user_id)
    threshold = automation["auto_approve_threshold"]
    res = await run_db(
        lambda: sb.table("transaction_fingerprints")
        .select("*")
        .eq("user_id", user_id)
        .order("recurrence_count", desc=True)
        .execute()
    )
    items = []
    for fp in res.data or []:
        conf = float(fp.get("confidence") or 0)
        if conf >= threshold:
            status = "Auto-posting"
        elif conf >= CONFIDENCE_FINGERPRINT_MIN:
            status = "Ready"
        else:
            status = "Learning"
        items.append(
            {
                "payee_pattern": fp.get("payee_pattern"),
                "account_name": fp.get("qb_account_name"),
                "qb_account_id": fp.get("qb_account_id"),
                "transaction_count": fp.get("recurrence_count"),
                "avg_confidence": conf,
                "auto_approve_eligible": conf >= threshold,
                "status": status,
                "last_seen_at": fp.get("last_seen_at"),
            }
        )
    return items
