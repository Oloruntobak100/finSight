"""Opening balance onboarding for bank account mappings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.books_service import _mapping_lookup, get_mappings, list_coa
from app.services.mono_money import normalize_mono_balance
from app.services.quickbooks_service import qb_company_post_json, qb_query


OPENING_EQUITY_NAMES = (
    "Opening Balance Equity",
    "Opening balance equity",
    "Owner's Equity",
)


async def _find_opening_equity_account(user_id: str) -> dict[str, Any] | None:
    coa = await list_coa(user_id)
    for name in OPENING_EQUITY_NAMES:
        for row in coa:
            if (row.get("name") or "").strip().lower() == name.lower():
                return row
    for row in coa:
        if (row.get("account_type") or "").lower() == "equity":
            if "opening" in (row.get("name") or "").lower():
                return row
    return None


async def _mono_suggested_balance(user_id: str, account_id: str) -> tuple[float, str, str]:
    """Return (balance_naira, currency, source)."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("raw_metadata, currency, transaction_date, created_at")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
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
    return 0.0, "NGN", "none"


async def get_opening_balance_preview(user_id: str, account_id: str) -> dict[str, Any]:
    mappings = await get_mappings(user_id)
    bank_map = _mapping_lookup(mappings, "bank_account", account_id)
    qb_bank_id = bank_map.get("qb_account_id") if bank_map else None

    mono_bal, currency, mono_source = await _mono_suggested_balance(user_id, account_id)
    qbo_current = None
    if qb_bank_id:
        from app.services.reconciliation.qbo_bank_activity import qbo_bank_account_balance

        qbo_current = await qbo_bank_account_balance(user_id, qb_bank_id)

    opening = {
        "opening_balance_amount": bank_map.get("opening_balance_amount") if bank_map else None,
        "opening_balance_as_of": bank_map.get("opening_balance_as_of") if bank_map else None,
        "opening_balance_qb_journal_id": bank_map.get("opening_balance_qb_journal_id") if bank_map else None,
        "opening_balance_posted_at": bank_map.get("opening_balance_posted_at") if bank_map else None,
    }

    return {
        "account_id": account_id,
        "qb_account_id": qb_bank_id,
        "qb_account_name": bank_map.get("qb_account_name") if bank_map else None,
        "suggested_mono_balance": mono_bal,
        "mono_balance_source": mono_source,
        "qbo_current_balance": qbo_current,
        "currency": currency,
        "already_posted": bool(opening.get("opening_balance_qb_journal_id")),
        **opening,
    }


async def post_opening_balance(
    user_id: str,
    account_id: str,
    *,
    amount: float,
    as_of_date: str,
    qb_bank_account_id: str | None = None,
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Opening balance amount must be positive")

    mappings = await get_mappings(user_id)
    bank_map = _mapping_lookup(mappings, "bank_account", account_id)
    bank_id = qb_bank_account_id or (bank_map.get("qb_account_id") if bank_map else None)
    if not bank_id:
        raise ValueError("Map this bank to a QuickBooks bank account first")

    if bank_map and bank_map.get("opening_balance_qb_journal_id"):
        raise ValueError("Opening balance already posted for this bank mapping")

    equity = await _find_opening_equity_account(user_id)
    if not equity:
        raise ValueError("Opening Balance Equity account not found in QuickBooks COA")

    equity_id = str(equity["qb_account_id"])
    txn_date = as_of_date[:10]
    payload = {
        "TxnDate": txn_date,
        "PrivateNote": f"FinSight opening balance {account_id}",
        "Line": [
            {
                "Amount": round(amount, 2),
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Debit",
                    "AccountRef": {"value": str(bank_id)},
                },
            },
            {
                "Amount": round(amount, 2),
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Credit",
                    "AccountRef": {"value": equity_id},
                },
            },
        ],
    }

    data = await qb_company_post_json(user_id, "/journalentry?minorversion=75", payload)
    entry = data.get("JournalEntry") or {}
    entry_id = str(entry.get("Id") or "")
    now = datetime.now(timezone.utc).isoformat()

    sb = get_supabase()
    mapping_row = {
        "user_id": user_id,
        "mapping_type": "bank_account",
        "finsight_key": account_id,
        "qb_account_id": str(bank_id),
        "qb_account_name": bank_map.get("qb_account_name") if bank_map else None,
        "opening_balance_amount": round(amount, 2),
        "opening_balance_as_of": txn_date,
        "opening_balance_qb_journal_id": entry_id,
        "opening_balance_posted_at": now,
        "updated_at": now,
    }
    await run_db(
        lambda: sb.table("qb_account_mappings")
        .upsert(mapping_row, on_conflict="user_id,mapping_type,finsight_key")
        .execute()
    )

    return {
        "posted": True,
        "journal_entry_id": entry_id,
        "amount": round(amount, 2),
        "as_of_date": txn_date,
        "qb_bank_account_id": str(bank_id),
    }
