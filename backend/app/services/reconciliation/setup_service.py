"""Bank reconciliation module — setup, matching, balance proof, workflow."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from app.services.bank_transaction_scope import get_active_bank_accounts
from app.services.books_service import _mapping_lookup, get_mappings, list_coa
from app.services.reconciliation.mono_bank_activity import mono_closing_balance
from app.services.reconciliation.qbo_bank_activity import qbo_bank_account_balance


def _last_full_month() -> tuple[str, str]:
    today = date.today()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    last_day = monthrange(y, m)[1]
    return f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last_day:02d}"


async def get_setup(user_id: str) -> dict[str, Any]:
    bank_accounts, _ = await get_active_bank_accounts(user_id)
    mappings = await get_mappings(user_id)
    coa = await list_coa(user_id)
    qb_banks = [row for row in coa if row.get("account_type") == "Bank"]

    banks: list[dict[str, Any]] = []
    for account in bank_accounts:
        bank_map = _mapping_lookup(mappings, "bank_account", account["id"])
        banks.append(
            {
                "id": account["id"],
                "account_name": account.get("account_name"),
                "provider": account.get("provider"),
                "qb_account_id": bank_map.get("qb_account_id") if bank_map else None,
                "qb_account_name": bank_map.get("qb_account_name") if bank_map else None,
            }
        )

    period_start, period_end = _last_full_month()
    return {
        "bank_accounts": banks,
        "qb_bank_accounts": [
            {"qb_account_id": row["qb_account_id"], "name": row.get("name") or "Unknown"}
            for row in qb_banks
        ],
        "default_period_start": period_start,
        "default_period_end": period_end,
    }


async def preview_balances(
    user_id: str,
    *,
    mono_account_id: str,
    qb_bank_account_id: str,
    period_end: str,
) -> dict[str, Any]:
    mono_bal, currency, source = await mono_closing_balance(user_id, mono_account_id, period_end)
    qbo_bal = await qbo_bank_account_balance(user_id, qb_bank_account_id)
    qbo_val = float(qbo_bal) if qbo_bal is not None else 0.0
    variance = round(mono_bal - qbo_val, 2)
    return {
        "mono_closing_balance": mono_bal,
        "mono_balance_source": source,
        "qbo_book_balance": qbo_val,
        "currency": currency,
        "raw_variance": variance,
    }
