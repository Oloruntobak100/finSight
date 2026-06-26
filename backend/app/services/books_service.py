"""QuickBooks Books Pipeline: classify, approve, learn, and post to QBO."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic
from openai import AsyncOpenAI

from app.config import settings
from app.database import get_supabase, run_db
from app.services.categorization_service import load_user_category_rules
from app.services.fingerprint_service import (
    FINGERPRINT_MATCH_MIN,
    _decisions_for_fingerprint,
    extract_fingerprint,
    fingerprint_confidence_reason,
    lookup_fingerprint,
    recalculate_fingerprint_confidence,
    touch_fingerprint_seen,
    upsert_fingerprint_from_decision,
)
from app.services.posting_rag_service import (
    rag_classify_hint,
    recent_decisions_context,
    search_similar_memories,
    store_posting_memory,
)
from app.services.quickbooks_service import qb_company_post_json, sync_chart_of_accounts
from app.services.transaction_posting_utils import (
    PostingKind,
    default_fee_account_names,
    detect_posting_kind,
    is_bank_fee,
    posting_type_for_kind,
)
from app.services.transfer_utils import is_transfer

logger = logging.getLogger(__name__)

BANK_PROVIDERS = ("plaid", "mono")
QbSyncStatus = Literal[
    "pending",
    "needs_review",
    "posted",
    "excluded",
    "failed",
    "skipped",
    "auto_approved",
]
SuggestionMethod = Literal["rule", "fingerprint", "rag", "llm", "auto", "manual"]
CONFIDENCE_AUTO = 0.92
CONFIDENCE_LLM_MIN = 0.85
CONFIDENCE_FINGERPRINT_MIN = FINGERPRINT_MATCH_MIN


def _resolve_llm_provider() -> str:
    if settings.llm_provider in ("openai", "anthropic"):
        return settings.llm_provider
    if settings.openai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    return "none"


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
    query = sb.table("qb_chart_of_accounts").select("*").eq("user_id", user_id)
    if account_type:
        query = query.eq("account_type", account_type)
    res = await run_db(lambda: query.order("name").execute())
    return res.data or []


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
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "mapping_type": mapping_type,
        "finsight_key": finsight_key,
        "qb_account_id": qb_account_id,
        "qb_account_name": qb_account_name,
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
    if kind == "income":
        return [a for a in coa if a.get("account_type") == "Income"]
    return [a for a in coa if a.get("account_type") == "Expense"]


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
        "method": method,
        "reason_text": reason_text,
    }
    res = await run_db(lambda: sb.table("posting_decisions").insert(row).execute())
    return (res.data or [row])[0]


async def _llm_classify(
    txn: dict[str, Any],
    target_accounts: list[dict[str, Any]],
    user_id: str,
    *,
    posting_label: str = "expense",
) -> tuple[str | None, str | None, float, str | None]:
    if not target_accounts:
        return None, None, 0.0, None

    provider = _resolve_llm_provider()
    if provider == "none":
        return None, None, 0.0, None

    accounts_text = "\n".join(
        f"- id={a['qb_account_id']}: {a['name']} ({a.get('account_sub_type') or a.get('account_type')})"
        for a in target_accounts[:80]
    )
    history = await recent_decisions_context(user_id)
    rag_hits = await search_similar_memories(user_id, txn, threshold=0.70)
    rag_block = ""
    if rag_hits:
        rag_block = "Similar approved transactions:\n" + "\n".join(
            f"- {h.get('content_text')} (similarity {float(h.get('similarity', 0)):.0%})"
            for h in rag_hits[:5]
        )

    prompt = f"""You are a bookkeeping assistant for a Nigerian SME using QuickBooks.
{history}

{rag_block}

Pick the best QuickBooks {posting_label} account for this bank transaction.
Return ONLY valid JSON: {{"account_id": "<qb_account_id>", "confidence": 0.0-1.0, "reason": "one line"}}

Transaction:
- date: {txn.get('transaction_date')}
- merchant: {txn.get('merchant_name')}
- description: {txn.get('description')}
- payee_pattern: {txn.get('payee_pattern')}
- category: {txn.get('category')}
- amount: {txn.get('amount')}
- direction: {txn.get('transaction_type')}

Accounts:
{accounts_text}"""

    try:
        if provider == "openai":
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            res = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw = res.choices[0].message.content or "{}"
        else:
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            res = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = res.content[0].text if res.content else "{}"

        parsed = json.loads(raw)
        account_id = str(parsed.get("account_id", "")) or None
        confidence = float(parsed.get("confidence", 0.7))
        reason = parsed.get("reason")
        name = _coa_name_from_list(target_accounts, account_id) if account_id else None
        return account_id, name, confidence, reason
    except Exception:
        logger.exception("LLM classify failed for txn %s", txn.get("id"))
        return None, None, 0.0, None


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
    rag_result: tuple[str | None, str | None, float, str | None] | None = None,
    llm_result: tuple[str | None, str | None, float, str | None] | None = None,
    automation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account_id = txn.get("account_id")
    category = txn.get("category") or "Uncategorized"
    merchant = txn.get("merchant_name")
    description = txn.get("description")
    kind = detect_posting_kind(txn)
    posting_type = posting_type_for_kind(kind)

    base_skip = {
        "qb_posting_type": posting_type,
        "qb_account_id": None,
        "qb_account_name": None,
        "qb_payment_account_id": None,
        "qb_suggestion_method": None,
        "qb_confidence_reason": None,
    }

    if kind == "transfer":
        return {
            **base_skip,
            "qb_sync_status": "excluded",
            "qb_posting_type": "transfer",
            "qb_confidence": None,
            "qb_confidence_reason": "Bank transfer — not posted to P&L (use Teach as expense/income if misclassified)",
        }

    if kind == "reversal":
        return {
            **base_skip,
            "qb_sync_status": "excluded",
            "qb_posting_type": "skip",
            "qb_confidence": None,
            "qb_confidence_reason": "Reversal — net against original transaction, not posted separately",
        }

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

    if not qb_account_id and fingerprint_row:
        fp_conf = float(fingerprint_row.get("confidence") or 0)
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

    if not qb_account_id and llm_result:
        llm_id, llm_name, llm_conf, llm_reason = llm_result
        if llm_id and _account_valid(coa_ids, llm_id):
            qb_account_id = llm_id
            qb_account_name = llm_name
            confidence = llm_conf
            method = "llm"
            reason = llm_reason

    if kind == "income" and not reason:
        reason = "Income / deposit — map to a QuickBooks income account"

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
        "payee_pattern": txn.get("payee_pattern") or extract_fingerprint(txn).get("payee_pattern"),
    }


async def classify_user_transactions(
    user_id: str,
    transaction_ids: list[str] | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    _, active_bank_ids = await _active_bank_accounts(user_id)
    if not active_bank_ids:
        return {"classified": 0}

    mappings = await get_mappings(user_id)
    user_rules = await load_user_category_rules(user_id, sb)
    coa = await list_coa(user_id)
    coa_ids = _coa_ids(coa)
    automation = await get_user_automation(user_id)

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
        txns = [t for t in txns if t.get("account_id") in active_bank_ids]
    else:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .in_("account_id", list(active_bank_ids))
            .is_("qb_sync_status", "null")
            .limit(200)
            .execute()
        )
        txns = res.data or []

    provider = _resolve_llm_provider()
    classified = 0
    for txn in txns:
        if txn.get("qb_sync_status") == "posted":
            continue
        if not transaction_ids and txn.get("qb_sync_status") in (
            "excluded",
            "skipped",
            "failed",
            "posted",
        ):
            continue

        kind = detect_posting_kind(txn)
        if kind in ("transfer", "reversal"):
            update = classify_transaction(
                txn, mappings, user_rules, coa, coa_ids, automation=automation
            )
            await run_db(
                lambda t=txn["id"], u=update: sb.table("transactions")
                .update(u)
                .eq("id", t)
                .eq("user_id", user_id)
                .execute()
            )
            classified += 1
            continue

        fp = extract_fingerprint(txn)
        fingerprint_row = await lookup_fingerprint(user_id, fp)
        if fingerprint_row:
            await touch_fingerprint_seen(user_id, txn)

        rag_result = None
        llm_result = None
        has_rule = bool(_mapping_lookup(mappings, "category", txn.get("category") or ""))
        target_accounts = _accounts_for_kind(coa, kind)
        posting_label = "income" if kind == "income" else "expense"

        if kind == "fee" and _default_fee_account(coa):
            has_rule = True

        if not has_rule and not (
            fingerprint_row and float(fingerprint_row.get("confidence") or 0) >= CONFIDENCE_FINGERPRINT_MIN
        ):
            rag_result = await rag_classify_hint(user_id, txn, coa_ids)

        if (
            not has_rule
            and not (fingerprint_row and float(fingerprint_row.get("confidence") or 0) >= CONFIDENCE_FINGERPRINT_MIN)
            and not (rag_result and rag_result[0])
            and provider != "none"
            and target_accounts
        ):
            llm_result = await _llm_classify(
                txn, target_accounts, user_id, posting_label=posting_label
            )

        update = classify_transaction(
            txn,
            mappings,
            user_rules,
            coa,
            coa_ids,
            fingerprint_row=fingerprint_row,
            rag_result=rag_result,
            llm_result=llm_result,
            automation=automation,
        )
        await run_db(
            lambda t=txn["id"], u=update: sb.table("transactions")
            .update(u)
            .eq("id", t)
            .eq("user_id", user_id)
            .execute()
        )
        classified += 1

    return {"classified": classified}


async def get_queue(
    user_id: str,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
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
        .in_("account_id", list(active_bank_ids))
        .not_.is_("qb_sync_status", "null")
    )
    if status:
        query = query.eq("qb_sync_status", status)

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
        items.append({**row, "account_name": bank_map.get(aid) if aid else None})

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
    sb = get_supabase()
    _, active_bank_ids = await _active_bank_accounts(user_id)
    if not active_bank_ids:
        return []

    res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .in_("account_id", list(active_bank_ids))
        .eq("qb_sync_status", status)
        .execute()
    )
    groups: dict[str, dict[str, Any]] = {}
    for row in res.data or []:
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


async def _active_bank_accounts(user_id: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Connected Plaid/Mono accounts only — Books uses realtime linked banks."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, provider, account_name, status, last_synced_at")
        .eq("user_id", user_id)
        .execute()
    )
    accounts = [
        a
        for a in (res.data or [])
        if a.get("provider") in BANK_PROVIDERS and a.get("status") != "disconnected"
    ]
    return accounts, {a["id"] for a in accounts}


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


async def get_summary(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    _, active_bank_ids = await _active_bank_accounts(user_id)
    counts: dict[str, int] = {}
    if active_bank_ids:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("qb_sync_status")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .in_("account_id", list(active_bank_ids))
            .not_.is_("qb_sync_status", "null")
            .execute()
        )
        for row in res.data or []:
            st = row.get("qb_sync_status") or "unknown"
            counts[st] = counts.get(st, 0) + 1
    automation = await get_user_automation(user_id)
    readiness = await get_books_readiness(user_id)
    return {"counts": counts, "automation": automation, "readiness": readiness}


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


async def approve_transaction(
    user_id: str,
    transaction_id: str,
    final_account_id: str,
    *,
    post: bool = False,
    payment_account_id: str | None = None,
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

    coa = await list_coa(user_id)
    coa_ids = _coa_ids(coa)
    if not _account_valid(coa_ids, final_account_id):
        raise ValueError("Invalid QuickBooks expense account")

    suggested_id = txn.get("qb_account_id")
    suggested_name = txn.get("qb_account_name")
    edit_made = bool(suggested_id and suggested_id != final_account_id)
    final_name = _coa_name(coa, final_account_id)

    if not payment_account_id:
        account_id = txn.get("account_id")
        mappings = await get_mappings(user_id)
        bank_map = _mapping_lookup(mappings, "bank_account", str(account_id)) if account_id else None
        payment_account_id = bank_map.get("qb_account_id") if bank_map else txn.get("qb_payment_account_id")

    fp_row = await upsert_fingerprint_from_decision(user_id, txn, final_account_id, final_name)

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

    await store_posting_memory(
        user_id,
        txn,
        final_account_id,
        final_name,
        fingerprint_id=fp_row.get("id"),
        posting_decision_id=decision.get("id"),
        method="manual",
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
        "qb_sync_status": "pending",
    }
    await run_db(
        lambda: sb.table("transactions").update(update).eq("id", transaction_id).execute()
    )

    result: dict[str, Any] = {"approved": True, "transaction_id": transaction_id, "decision": decision}
    if post:
        result["post"] = await post_transaction(user_id, transaction_id)
    else:
        result["transaction"] = {**txn, **update}
    return result


async def approve_transactions_bulk(
    user_id: str,
    transaction_ids: list[str] | None = None,
    payee_pattern: str | None = None,
    *,
    post: bool = False,
    final_account_id: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    if payee_pattern:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("id, qb_account_id")
            .eq("user_id", user_id)
            .eq("payee_pattern", payee_pattern)
            .in_("qb_sync_status", ["pending", "needs_review"])
            .execute()
        )
        transaction_ids = [r["id"] for r in (res.data or [])]
        if not final_account_id and res.data:
            final_account_id = res.data[0].get("qb_account_id")

    if not transaction_ids:
        return {"approved": 0, "errors": []}
    if not final_account_id:
        raise ValueError("final_account_id required for bulk approve")

    approved = 0
    errors: list[dict[str, str]] = []
    for tid in transaction_ids:
        try:
            await approve_transaction(user_id, tid, final_account_id, post=post)
            approved += 1
        except ValueError as exc:
            errors.append({"transaction_id": tid, "error": str(exc)})
    return {"approved": approved, "errors": errors}


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


def _build_deposit_payload(txn: dict[str, Any]) -> dict[str, Any]:
    amount = abs(float(txn.get("amount") or 0))
    txn_date = str(txn.get("transaction_date"))
    merchant = txn.get("merchant_name") or txn.get("description") or "Deposit"
    return {
        "DepositToAccountRef": {"value": str(txn["qb_payment_account_id"])},
        "TxnDate": txn_date,
        "PrivateNote": f"FinSight:{txn['id']}",
        "Line": [
            {
                "Amount": amount,
                "Description": merchant[:4000] if merchant else None,
                "DetailType": "DepositLineDetail",
                "DepositLineDetail": {
                    "AccountRef": {"value": str(txn["qb_account_id"])},
                },
            }
        ],
    }


def _build_purchase_payload(txn: dict[str, Any]) -> dict[str, Any]:
    amount = abs(float(txn.get("amount") or 0))
    txn_date = str(txn.get("transaction_date"))
    merchant = txn.get("merchant_name") or txn.get("description") or "Expense"
    return {
        "PaymentType": "Cash",
        "AccountRef": {"value": str(txn["qb_payment_account_id"])},
        "TxnDate": txn_date,
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


async def post_transaction(user_id: str, transaction_id: str, *, is_auto: bool = False) -> dict[str, Any]:
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

    if txn.get("qb_sync_status") in ("excluded",) and not is_auto:
        return {"skipped": True, "reason": txn.get("qb_sync_status"), "transaction": txn}

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

    posting_type = txn.get("qb_posting_type") or "expense"
    if posting_type == "deposit":
        payload = _build_deposit_payload(txn)
        api_path = "/deposit?minorversion=75"
        entity_type = "Deposit"
    else:
        payload = _build_purchase_payload(txn)
        api_path = "/purchase?minorversion=75"
        entity_type = "Purchase"

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
            return {"posted": True, "qb_entity_id": entity_id, "transaction": (res.data or [txn])[0]}
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0 and "401" in last_error:
                continue
            break

    err = last_error or "Post failed"
    await run_db(
        lambda: sb.table("transactions")
        .update({"qb_sync_status": "failed", "qb_error": err[:2000]})
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
    coa = await list_coa(user_id)
    if coa:
        return {"synced": len(coa), "cached": True}
    return await sync_chart_of_accounts(user_id)


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
