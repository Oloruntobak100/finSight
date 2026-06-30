from datetime import datetime, timezone
from typing import Any

from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

from app.database import get_supabase, run_db
from app.services.bank_account_lifecycle import maybe_auto_restore_bank_data
from app.services.bank_transaction_scope import count_scoped_transactions, get_active_bank_accounts
from app.services.mono_money import normalize_mono_balance
from app.models.analysis_filters import AnalysisFilters
from app.services.plaid_service import _get_plaid_client, _plaid_to_dict
from app.services.token_service import decrypt_token


async def _mono_balance_from_transactions(sb: Any, user_id: str, account_id: str) -> tuple[float, str]:
    res = await run_db(
        lambda: sb.table("transactions")
        .select("raw_metadata, currency, transaction_date, created_at")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .is_("archived_at", "null")
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return 0.0, "NGN"
    row = res.data[0]
    raw = row.get("raw_metadata") or {}
    balance = normalize_mono_balance(raw.get("balance"))
    currency = row.get("currency") or "NGN"
    return balance, currency


async def get_user_balances(
    user_id: str,
    filters: AnalysisFilters | None = None,
) -> dict[str, Any]:
    bank_accounts, active_bank_ids = await get_active_bank_accounts(user_id)
    if active_bank_ids:
        visible = await count_scoped_transactions(user_id, active_bank_ids)
        await maybe_auto_restore_bank_data(user_id, bank_accounts, visible_count=visible)

    sb = get_supabase()
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name, provider, access_token_encrypted")
        .eq("user_id", user_id)
        .eq("status", "active")
        .execute()
    )

    items: list[dict[str, Any]] = []
    totals_by_currency: dict[str, float] = {}
    errors: list[str] = []

    for conn in accounts_res.data or []:
        conn_id = conn["id"]
        provider = conn.get("provider") or "unknown"

        if filters:
            if filters.providers and provider not in filters.providers:
                continue
            if filters.account_ids and conn_id not in filters.account_ids:
                continue

        if provider == "plaid":
            if not conn.get("access_token_encrypted"):
                continue
            try:
                access_token = decrypt_token(conn["access_token_encrypted"])
                client = _get_plaid_client()
                res = _plaid_to_dict(
                    await run_db(
                        client.accounts_balance_get,
                        AccountsBalanceGetRequest(access_token=access_token),
                    )
                )
                for acct in res.get("accounts", []):
                    balances = acct.get("balances") or {}
                    current = float(balances.get("current") or 0)
                    available = balances.get("available")
                    currency = balances.get("iso_currency_code") or "USD"
                    totals_by_currency[currency] = totals_by_currency.get(currency, 0) + current
                    items.append(
                        {
                            "connected_account_id": conn_id,
                            "institution_name": conn.get("account_name") or "Bank",
                            "provider": "plaid",
                            "account_id": acct.get("account_id"),
                            "name": acct.get("name") or "Account",
                            "type": acct.get("type"),
                            "subtype": acct.get("subtype"),
                            "mask": acct.get("mask"),
                            "current": current,
                            "available": float(available) if available is not None else None,
                            "currency": currency,
                        }
                    )
            except Exception as exc:
                errors.append(f"{conn.get('account_name', 'Account')}: {exc}")

        elif provider == "mono":
            try:
                balance, currency = await _mono_balance_from_transactions(sb, user_id, conn_id)
                totals_by_currency[currency] = totals_by_currency.get(currency, 0) + balance
                items.append(
                    {
                        "connected_account_id": conn_id,
                        "institution_name": conn.get("account_name") or "Bank",
                        "provider": "mono",
                        "account_id": conn_id,
                        "name": conn.get("account_name") or "Account",
                        "type": "depository",
                        "subtype": None,
                        "mask": None,
                        "current": balance,
                        "available": balance,
                        "currency": currency,
                    }
                )
            except Exception as exc:
                errors.append(f"{conn.get('account_name', 'Account')}: {exc}")

    primary_currency = max(totals_by_currency, key=totals_by_currency.get) if totals_by_currency else "USD"
    total_balance = totals_by_currency.get(primary_currency, 0.0)

    return {
        "total_balance": round(total_balance, 2),
        "totals_by_currency": {k: round(v, 2) for k, v in totals_by_currency.items()},
        "primary_currency": primary_currency,
        "accounts": items,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }
