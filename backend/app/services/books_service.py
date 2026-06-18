"""QuickBooks Books Pipeline: classify bank transactions and post to QBO."""

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
from app.services.quickbooks_service import qb_company_post_json, sync_chart_of_accounts
from app.services.transfer_utils import is_transfer

logger = logging.getLogger(__name__)

BANK_PROVIDERS = ("plaid", "mono")
QbSyncStatus = Literal["pending", "needs_review", "posted", "excluded", "failed", "skipped"]
CONFIDENCE_AUTO = 0.92
CONFIDENCE_LLM_MIN = 0.85


def _resolve_llm_provider() -> str:
    if settings.llm_provider in ("openai", "anthropic"):
        return settings.llm_provider
    if settings.openai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    return "none"


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


def _coa_name(coa: list[dict[str, Any]], qb_account_id: str) -> str | None:
    for row in coa:
        if row.get("qb_account_id") == qb_account_id:
            return row.get("name")
    return None


async def _llm_classify(
    txn: dict[str, Any],
    expense_accounts: list[dict[str, Any]],
) -> tuple[str | None, str | None, float]:
    if not expense_accounts:
        return None, None, 0.0

    provider = _resolve_llm_provider()
    if provider == "none":
        return None, None, 0.0

    accounts_text = "\n".join(
        f"- id={a['qb_account_id']}: {a['name']} ({a.get('account_sub_type') or a.get('account_type')})"
        for a in expense_accounts[:80]
    )
    prompt = f"""Pick the best QuickBooks expense account for this bank transaction.
Return ONLY valid JSON: {{"account_id": "<qb_account_id>", "confidence": 0.0-1.0}}

Transaction:
- date: {txn.get('transaction_date')}
- merchant: {txn.get('merchant_name')}
- description: {txn.get('description')}
- category: {txn.get('category')}
- amount: {txn.get('amount')}
- type: {txn.get('transaction_type')}

Expense accounts:
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
        name = _coa_name(expense_accounts, account_id) if account_id else None
        return account_id, name, confidence
    except Exception:
        logger.exception("LLM classify failed for txn %s", txn.get("id"))
        return None, None, 0.0


def classify_transaction(
    txn: dict[str, Any],
    mappings: list[dict[str, Any]],
    user_rules: dict[str, str],
    expense_accounts: list[dict[str, Any]],
    llm_result: tuple[str | None, str | None, float] | None = None,
) -> dict[str, Any]:
    account_id = txn.get("account_id")
    category = txn.get("category") or "Uncategorized"
    merchant = txn.get("merchant_name")
    description = txn.get("description")
    txn_type = txn.get("transaction_type")

    if is_transfer(category, merchant, description):
        return {
            "qb_sync_status": "excluded",
            "qb_posting_type": "skip",
            "qb_confidence": 1.0,
            "qb_account_id": None,
            "qb_account_name": None,
            "qb_payment_account_id": None,
        }

    if txn_type == "credit":
        return {
            "qb_sync_status": "skipped",
            "qb_posting_type": "deposit",
            "qb_confidence": 1.0,
            "qb_account_id": None,
            "qb_account_name": None,
            "qb_payment_account_id": None,
        }

    bank_map = _mapping_lookup(mappings, "bank_account", str(account_id)) if account_id else None
    payment_account_id = bank_map.get("qb_account_id") if bank_map else None

    qb_account_id: str | None = None
    qb_account_name: str | None = None
    confidence = 0.5

    cat_map = _mapping_lookup(mappings, "category", category)
    if cat_map:
        qb_account_id = cat_map.get("qb_account_id")
        qb_account_name = cat_map.get("qb_account_name")
        confidence = 0.92
    else:
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

    if not qb_account_id and llm_result:
        llm_id, llm_name, llm_conf = llm_result
        if llm_id:
            qb_account_id = llm_id
            qb_account_name = llm_name
            confidence = llm_conf

    if confidence >= CONFIDENCE_AUTO and payment_account_id and qb_account_id:
        status: QbSyncStatus = "pending"
    elif qb_account_id and payment_account_id and confidence >= CONFIDENCE_LLM_MIN:
        status = "pending"
    else:
        status = "needs_review"
        if qb_account_id and not payment_account_id:
            confidence = min(confidence, 0.84)

    return {
        "qb_sync_status": status,
        "qb_posting_type": "expense",
        "qb_confidence": round(confidence, 2),
        "qb_account_id": qb_account_id,
        "qb_account_name": qb_account_name,
        "qb_payment_account_id": payment_account_id,
    }


async def classify_user_transactions(
    user_id: str,
    transaction_ids: list[str] | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    mappings = await get_mappings(user_id)
    user_rules = await load_user_category_rules(user_id, sb)
    coa = await list_coa(user_id)
    expense_accounts = [a for a in coa if a.get("account_type") == "Expense"]

    query = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .eq("transaction_type", "debit")
    )
    if transaction_ids:
        res = await run_db(lambda: query.in_("id", transaction_ids).limit(500).execute())
        txns = res.data or []
    else:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .eq("transaction_type", "debit")
            .in_("qb_sync_status", ["pending", "needs_review"])
            .limit(500)
            .execute()
        )
        null_res = await run_db(
            lambda: sb.table("transactions")
            .select("*")
            .eq("user_id", user_id)
            .in_("source_provider", list(BANK_PROVIDERS))
            .eq("transaction_type", "debit")
            .is_("qb_sync_status", "null")
            .limit(500)
            .execute()
        )
        txns = (res.data or []) + (null_res.data or [])

    provider = _resolve_llm_provider()
    classified = 0
    for txn in txns:
        if txn.get("qb_sync_status") == "posted":
            continue

        llm_result = None
        if provider != "none" and not _mapping_lookup(mappings, "category", txn.get("category") or ""):
            llm_result = await _llm_classify(txn, expense_accounts)

        update = classify_transaction(txn, mappings, user_rules, expense_accounts, llm_result)
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
    query = (
        sb.table("transactions")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
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

    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name")
        .eq("user_id", user_id)
        .execute()
    )
    bank_map = {r["id"]: r.get("account_name") for r in (accounts_res.data or [])}

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


async def get_summary(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("qb_sync_status")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .not_.is_("qb_sync_status", "null")
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data or []:
        st = row.get("qb_sync_status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
    return {"counts": counts}


async def exclude_transaction(user_id: str, transaction_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .update({"qb_sync_status": "excluded", "qb_posting_type": "skip"})
        .eq("id", transaction_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise ValueError("Transaction not found")
    return res.data[0]


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


async def post_transaction(user_id: str, transaction_id: str) -> dict[str, Any]:
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

    if txn.get("qb_sync_status") in ("excluded", "skipped"):
        return {"skipped": True, "reason": txn.get("qb_sync_status"), "transaction": txn}

    if not txn.get("qb_account_id") or not txn.get("qb_payment_account_id"):
        mappings = await get_mappings(user_id)
        user_rules = await load_user_category_rules(user_id, sb)
        coa = await list_coa(user_id)
        expense_accounts = [a for a in coa if a.get("account_type") == "Expense"]
        llm_result = None
        if _resolve_llm_provider() != "none":
            llm_result = await _llm_classify(txn, expense_accounts)
        update = classify_transaction(txn, mappings, user_rules, expense_accounts, llm_result)
        txn = {**txn, **update}
        await run_db(
            lambda: sb.table("transactions")
            .update(update)
            .eq("id", transaction_id)
            .execute()
        )

    if not txn.get("qb_account_id") or not txn.get("qb_payment_account_id"):
        raise ValueError("Missing QB account mapping. Configure mappings first.")

    payload = _build_purchase_payload(txn)
    try:
        data = await qb_company_post_json(user_id, "/purchase?minorversion=75", payload)
        purchase = data.get("Purchase") or {}
        entity_id = str(purchase.get("Id", ""))
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "qb_sync_status": "posted",
            "qb_entity_type": "Purchase",
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
        return {"posted": True, "qb_entity_id": entity_id, "transaction": (res.data or [txn])[0]}
    except Exception as exc:
        err = str(exc)
        await run_db(
            lambda: sb.table("transactions")
            .update({"qb_sync_status": "failed", "qb_error": err[:2000]})
            .eq("id", transaction_id)
            .eq("user_id", user_id)
            .execute()
        )
        raise ValueError(err) from exc


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


async def ensure_coa_synced(user_id: str) -> dict[str, Any]:
    coa = await list_coa(user_id)
    if coa:
        return {"synced": len(coa), "cached": True}
    return await sync_chart_of_accounts(user_id)
