"""Normalize Mono bank feed lines for reconciliation."""

from __future__ import annotations

from typing import Any

from app.database import get_supabase, run_db
from app.services.mono_money import normalize_mono_balance
from app.services.qb_party_service import txn_doc_number

BANK_PROVIDERS = ("plaid", "mono")


def _mono_direction(transaction_type: str | None) -> str:
    return "out" if (transaction_type or "").lower() == "debit" else "in"


def _mono_payee(row: dict[str, Any]) -> str:
    return (row.get("merchant_name") or row.get("description") or "").strip()


async def load_mono_bank_activity(
    user_id: str,
    *,
    mono_account_id: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select(
            "id, transaction_date, amount, currency, transaction_type, "
            "merchant_name, description, qb_entity_id, qb_entity_type, qb_sync_status, "
            "qb_posted_at, posting_lag_days, discovered_date"
        )
        .eq("user_id", user_id)
        .eq("account_id", mono_account_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .gte("transaction_date", period_start)
        .lte("transaction_date", period_end)
        .order("transaction_date")
        .execute()
    )
    normalized: list[dict[str, Any]] = []
    for row in res.data or []:
        amount = abs(float(row.get("amount") or 0))
        normalized.append(
            {
                "source": "MONO",
                "mono_transaction_id": row.get("id"),
                "transaction_date": str(row.get("transaction_date")),
                "amount": amount,
                "signed_amount": -amount if _mono_direction(row.get("transaction_type")) == "out" else amount,
                "currency": row.get("currency") or "NGN",
                "direction": _mono_direction(row.get("transaction_type")),
                "payee": _mono_payee(row),
                "narration": row.get("description") or "",
                "reference": txn_doc_number(row) or "",
                "qb_entity_id": row.get("qb_entity_id"),
                "qb_entity_type": row.get("qb_entity_type"),
                "qb_sync_status": row.get("qb_sync_status"),
                "posted_date": row.get("qb_posted_at"),
                "posting_lag_days": row.get("posting_lag_days"),
                "discovered_date": row.get("discovered_date"),
            }
        )
    return normalized


async def mono_closing_balance(
    user_id: str,
    mono_account_id: str,
    period_end: str,
) -> tuple[float, str, str]:
    """Return (balance, currency, source: metadata|computed)."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("raw_metadata, currency, transaction_date, amount, transaction_type")
        .eq("user_id", user_id)
        .eq("account_id", mono_account_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .lte("transaction_date", period_end)
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        row = res.data[0]
        raw = row.get("raw_metadata") or {}
        bal = raw.get("balance")
        if bal is not None:
            return normalize_mono_balance(bal), row.get("currency") or "NGN", "metadata"

    all_res = await run_db(
        lambda: sb.table("transactions")
        .select("amount, transaction_type, currency")
        .eq("user_id", user_id)
        .eq("account_id", mono_account_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .lte("transaction_date", period_end)
        .execute()
    )
    net = 0.0
    currency = "NGN"
    for row in all_res.data or []:
        amt = abs(float(row.get("amount") or 0))
        currency = row.get("currency") or currency
        if _mono_direction(row.get("transaction_type")) == "out":
            net -= amt
        else:
            net += amt
    return net, currency, "computed"
