import asyncio
import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.sandbox_item_fire_webhook_request import SandboxItemFireWebhookRequest
from plaid.model.transactions_recurring_get_request import TransactionsRecurringGetRequest
from plaid.model.transactions_refresh_request import TransactionsRefreshRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions
from plaid.model.webhook_type import WebhookType

from app.config import settings
from app.database import get_supabase, run_db
from app.services.bank_transaction_scope import archive_detached_bank_transactions, archive_transactions_for_account
from app.services.token_service import decrypt_token, encrypt_token
from app.services.transaction_enrichment import build_plaid_transaction_row, load_user_category_rules


def _plaid_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "to_dict"):
        return response.to_dict()
    return dict(response)


def _txn_field(txn: Any, key: str, default: Any = None) -> Any:
    if isinstance(txn, dict):
        return txn.get(key, default)
    return getattr(txn, key, default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())
    return value


def _parse_products(names: list[str]) -> list[Products]:
    return [Products(name) for name in names]


def _parse_country_codes(codes: list[str]) -> list[CountryCode]:
    return [CountryCode(code) for code in codes]


def _plaid_api_host() -> str:
    if settings.plaid_environment == "production":
        return "https://production.plaid.com"
    if settings.plaid_environment == "development":
        return "https://development.plaid.com"
    return "https://sandbox.plaid.com"


def _get_plaid_client() -> plaid_api.PlaidApi:
    host = plaid.Environment.Sandbox
    if settings.plaid_environment == "production":
        host = plaid.Environment.Production
    elif settings.plaid_environment == "development":
        host = plaid.Environment.Development

    configuration = plaid.Configuration(
        host=host,
        api_key={"clientId": settings.plaid_client_id, "secret": settings.plaid_secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


async def _upsert_plaid_transaction(
    sb: Any, user_id: str, account_id: str, txn: Any, user_rules: dict[str, str] | None = None
) -> None:
    amount = float(_txn_field(txn, "amount", 0))
    txn_type = "debit" if amount > 0 else "credit"
    raw = _json_safe(_plaid_to_dict(txn) if not isinstance(txn, dict) else txn)
    row = build_plaid_transaction_row(
        txn,
        user_id=user_id,
        account_id=account_id,
        amount=amount,
        txn_type=txn_type,
        currency=_txn_field(txn, "iso_currency_code") or "USD",
        external_id=_txn_field(txn, "transaction_id"),
        raw_metadata=raw,
        user_rules=user_rules,
    )
    await run_db(
        lambda r=row: sb.table("transactions")
        .upsert(r, on_conflict="source_provider,external_id,user_id")
        .execute()
    )


async def _get_institution_name(access_token: str) -> str | None:
    client = _get_plaid_client()
    try:
        item_res = _plaid_to_dict(
            await run_db(client.item_get, ItemGetRequest(access_token=access_token))
        )
        institution_id = (item_res.get("item") or {}).get("institution_id")
        if not institution_id:
            return None

        inst_res = _plaid_to_dict(
            await run_db(
                client.institutions_get_by_id,
                InstitutionsGetByIdRequest(
                    institution_id=institution_id,
                    country_codes=_parse_country_codes(settings.plaid_country_code_list),
                ),
            )
        )
        return (inst_res.get("institution") or {}).get("name")
    except Exception:
        return None


async def _resolve_account_name(access_token: str, account_name: str | None) -> str:
    if account_name and account_name.strip().lower() != "plaid account":
        return account_name.strip()
    resolved = await _get_institution_name(access_token)
    return resolved or "Plaid Account"


async def _backfill_account_name(sb: Any, account_id: str, access_token: str, current_name: str | None) -> None:
    if current_name and current_name.strip().lower() != "plaid account":
        return
    resolved = await _get_institution_name(access_token)
    if not resolved:
        return
    await run_db(
        lambda: sb.table("connected_accounts")
        .update({"account_name": resolved})
        .eq("id", account_id)
        .execute()
    )


async def create_link_token(user_id: str) -> str:
    client = _get_plaid_client()
    request_kwargs: dict[str, Any] = {
        "products": _parse_products(settings.plaid_product_list),
        "client_name": "FinSight AI",
        "country_codes": _parse_country_codes(settings.plaid_country_code_list),
        "language": "en",
        "user": LinkTokenCreateRequestUser(client_user_id=user_id),
    }
    optional_products = settings.plaid_optional_product_list
    if optional_products:
        request_kwargs["optional_products"] = _parse_products(optional_products)
    if settings.plaid_redirect_uri:
        request_kwargs["redirect_uri"] = settings.plaid_redirect_uri
    if settings.plaid_webhook_url:
        request_kwargs["webhook"] = settings.plaid_webhook_url

    request = LinkTokenCreateRequest(**request_kwargs)
    response = _plaid_to_dict(await run_db(client.link_token_create, request))
    return response["link_token"]


async def exchange_public_token(
    user_id: str, public_token: str, account_name: str | None = None
) -> dict[str, Any]:
    client = _get_plaid_client()
    exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
    exchange = _plaid_to_dict(await run_db(client.item_public_token_exchange, exchange_request))
    access_token = exchange["access_token"]
    item_id = exchange["item_id"]
    display_name = await _resolve_account_name(access_token, account_name)

    sb = get_supabase()
    row = {
        "user_id": user_id,
        "provider": "plaid",
        "account_name": display_name,
        "account_type": "bank",
        "access_token_encrypted": encrypt_token(access_token),
        "external_account_id": item_id,
        "status": "active",
    }
    result = await run_db(lambda: sb.table("connected_accounts").insert(row).execute())
    return result.data[0]


async def sync_plaid_transactions(user_id: str, account_id: str) -> int:
    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    account = account_res.data
    access_token = decrypt_token(account["access_token_encrypted"])
    client = _get_plaid_client()

    await _backfill_account_name(sb, account_id, access_token, account.get("account_name"))

    user_rules = await load_user_category_rules(user_id, sb)
    sync_options = TransactionsSyncRequestOptions(
        include_personal_finance_category=True,
        include_original_description=True,
        include_logo_and_counterparty_beta=True,
    )

    cursor = account.get("plaid_sync_cursor")
    count = 0
    while True:
        sync_kwargs: dict[str, Any] = {
            "access_token": access_token,
            "count": 500,
            "options": sync_options,
        }
        if cursor:
            sync_kwargs["cursor"] = cursor
        request = TransactionsSyncRequest(**sync_kwargs)
        sync_res = _plaid_to_dict(await run_db(client.transactions_sync, request))

        for txn in sync_res.get("added", []):
            await _upsert_plaid_transaction(sb, user_id, account_id, txn, user_rules)
            count += 1
        for txn in sync_res.get("modified", []):
            await _upsert_plaid_transaction(sb, user_id, account_id, txn, user_rules)
            count += 1
        for removed in sync_res.get("removed", []):
            removed_id = removed.get("transaction_id") if isinstance(removed, dict) else getattr(removed, "transaction_id", None)
            if removed_id:
                await run_db(
                    lambda rid=removed_id: sb.table("transactions")
                    .delete()
                    .eq("user_id", user_id)
                    .eq("source_provider", "plaid")
                    .eq("external_id", rid)
                    .execute()
                )

        cursor = sync_res.get("next_cursor")
        if not sync_res.get("has_more"):
            break

    update_fields: dict[str, Any] = {
        "last_synced_at": date.today().isoformat(),
        "status": "active",
    }
    if cursor:
        update_fields["plaid_sync_cursor"] = cursor

    try:
        await run_db(
            lambda: sb.table("connected_accounts").update(update_fields).eq("id", account_id).execute()
        )
    except Exception:
        update_fields.pop("plaid_sync_cursor", None)
        await run_db(
            lambda: sb.table("connected_accounts").update(update_fields).eq("id", account_id).execute()
        )
    return count


async def sync_plaid_item_by_external_id(item_id: str) -> dict[str, Any]:
    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, user_id")
        .eq("external_account_id", item_id)
        .eq("provider", "plaid")
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if not account_res.data:
        return {"handled": False, "reason": "connected account not found"}

    account = account_res.data[0]
    synced = await sync_plaid_transactions(account["user_id"], account["id"])
    recurring = await mark_recurring_transactions(account["user_id"], account["id"])
    return {
        "handled": True,
        "account_id": account["id"],
        "synced_transactions": synced,
        "recurring_marked": recurring,
    }


async def handle_plaid_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    webhook_code = payload.get("webhook_code", "")
    item_id = payload.get("item_id")

    sync_codes = {
        "SYNC_UPDATES_AVAILABLE",
        "DEFAULT_UPDATE",
        "INITIAL_UPDATE",
        "HISTORICAL_UPDATE",
        "RECURRING_TRANSACTIONS_UPDATE",
    }
    if webhook_code not in sync_codes:
        return {"handled": False, "reason": f"ignored webhook_code={webhook_code}"}
    if not item_id:
        return {"handled": False, "reason": "missing item_id"}

    return await sync_plaid_item_by_external_id(item_id)


def _sandbox_transaction_date() -> str:
    # Plaid rejects future dates; use UTC to avoid local clock drift.
    return datetime.now(timezone.utc).date().isoformat()


async def _upsert_local_sandbox_transaction(
    user_id: str,
    account_id: str,
    description: str,
    amount: float,
    transaction_type: str,
    txn_date: str,
) -> None:
    """Write injected sandbox txn locally when Plaid /transactions/sync has not caught up yet."""
    sb = get_supabase()
    external_id = _sandbox_fallback_external_id(
        account_id, description, amount, transaction_type, txn_date
    )
    row = {
        "user_id": user_id,
        "account_id": account_id,
        "transaction_date": txn_date,
        "description": description,
        "merchant_name": description,
        "category": "INCOME" if transaction_type == "income" else "GENERAL_MERCHANDISE",
        "amount": abs(amount),
        "currency": "USD",
        "transaction_type": "credit" if transaction_type == "income" else "debit",
        "source_provider": "plaid",
        "external_id": external_id,
        "raw_metadata": {"source": "sandbox_inject_fallback"},
    }
    await run_db(
        lambda r=row: sb.table("transactions")
        .upsert(r, on_conflict="source_provider,external_id,user_id")
        .execute()
    )


async def _poll_sync_after_injection(
    user_id: str,
    account_id: str,
    *,
    max_attempts: int = 6,
    delay_seconds: float = 2.0,
) -> int:
    """transactions_refresh is async; poll /transactions/sync until new rows appear."""
    total = 0
    for attempt in range(max_attempts):
        if attempt > 0:
            await asyncio.sleep(delay_seconds)
        try:
            count = await sync_plaid_transactions(user_id, account_id)
            total += count
            if count > 0:
                return total
        except Exception:
            continue
    return total


def _sandbox_fallback_external_id(
    account_id: str,
    description: str,
    amount: float,
    transaction_type: str,
    txn_date: str,
) -> str:
    digest = hashlib.sha256(
        f"{account_id}:{txn_date}:{description}:{amount}:{transaction_type}".encode()
    ).hexdigest()[:16]
    return f"sandbox-{digest}"


async def _reconcile_sandbox_injection(
    user_id: str,
    account_id: str,
    description: str,
    amount: float,
    transaction_type: str,
    txn_date: str,
) -> None:
    """Background: wait for Plaid sync, then drop the temporary local row."""
    try:
        if await _poll_sync_after_injection(user_id, account_id) <= 0:
            return
        sb = get_supabase()
        fallback_id = _sandbox_fallback_external_id(
            account_id, description, amount, transaction_type, txn_date
        )
        await run_db(
            lambda: sb.table("transactions")
            .delete()
            .eq("user_id", user_id)
            .eq("source_provider", "plaid")
            .eq("external_id", fallback_id)
            .execute()
        )
    except Exception:
        pass


async def _background_plaid_reconcile(
    access_token: str,
    user_id: str,
    account_id: str,
    description: str,
    amount: float,
    transaction_type: str,
    txn_date: str,
) -> None:
    """Non-blocking Plaid refresh + sync after sandbox inject."""
    try:
        client = _get_plaid_client()
        await asyncio.wait_for(
            run_db(
                client.transactions_refresh,
                TransactionsRefreshRequest(access_token=access_token),
            ),
            timeout=15,
        )
    except Exception:
        pass
    await _reconcile_sandbox_injection(
        user_id, account_id, description, amount, transaction_type, txn_date
    )


async def inject_sandbox_transaction(
    access_token: str, description: str, amount: float
) -> tuple[dict[str, Any], str]:
    txn_date = _sandbox_transaction_date()
    payload = {
        "client_id": settings.plaid_client_id,
        "secret": settings.plaid_secret,
        "access_token": access_token,
        "transactions": [
            {
                "amount": amount,
                "date_posted": txn_date,
                "date_transacted": txn_date,
                "description": description,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{_plaid_api_host()}/sandbox/transactions/create",
            json=payload,
        )
        if response.status_code >= 400:
            detail = response.json() if response.content else {"error": response.text}
            error_msg = detail.get("error_message") or detail.get("display_message") or str(detail)
            if "future" in error_msg.lower():
                yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
                payload["transactions"][0]["date_posted"] = yesterday
                payload["transactions"][0]["date_transacted"] = yesterday
                txn_date = yesterday
                retry = await client.post(
                    f"{_plaid_api_host()}/sandbox/transactions/create",
                    json=payload,
                )
                if retry.status_code < 400:
                    return retry.json(), txn_date
            raise ValueError(error_msg)
        return response.json(), txn_date


async def fire_sandbox_sync_webhook(access_token: str) -> dict[str, Any]:
    client = _get_plaid_client()
    request = SandboxItemFireWebhookRequest(
        access_token=access_token,
        webhook_code="SYNC_UPDATES_AVAILABLE",
        webhook_type=WebhookType("TRANSACTIONS"),
    )
    return _plaid_to_dict(await run_db(client.sandbox_item_fire_webhook, request))


async def simulate_sandbox_purchase(
    user_id: str,
    account_id: str,
    description: str = "FinSight Sandbox Coffee",
    amount: float = 4.75,
    transaction_type: str = "expense",
) -> dict[str, Any]:
    if settings.plaid_environment != "sandbox":
        raise ValueError("Sandbox simulation is only available in Plaid sandbox")

    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .eq("provider", "plaid")
        .single()
        .execute()
    )
    account = account_res.data
    access_token = decrypt_token(account["access_token_encrypted"])

    signed_amount = abs(amount) if transaction_type == "expense" else -abs(amount)
    txn_date = _sandbox_transaction_date()

    inject_error = None
    try:
        _, txn_date = await inject_sandbox_transaction(access_token, description, signed_amount)
        injected = True
    except Exception as exc:
        injected = False
        inject_error = str(exc)

    webhook_fired = False
    webhook_error = None
    if settings.plaid_webhook_url:
        try:
            await fire_sandbox_sync_webhook(access_token)
            webhook_fired = True
        except Exception as exc:
            webhook_error = str(exc)

    sync_error = None
    synced = 0
    used_local_fallback = False
    try:
        if injected:
            # Write locally immediately; Plaid refresh/sync runs in background.
            await _upsert_local_sandbox_transaction(
                user_id, account_id, description, amount, transaction_type, txn_date
            )
            synced = 1
            used_local_fallback = True
            asyncio.create_task(
                _background_plaid_reconcile(
                    access_token, user_id, account_id, description, amount, transaction_type, txn_date
                )
            )
        else:
            synced = await sync_plaid_transactions(user_id, account_id)
    except Exception as exc:
        sync_error = str(exc)

    if injected and synced > 0:
        note = (
            "Mock transaction added to FinSight."
            if used_local_fallback
            else "Mock transaction created and synced into FinSight."
        )
    elif injected:
        note = "Mock transaction created in Plaid but could not sync yet."
    elif inject_error and "user_transactions_dynamic" in inject_error.lower():
        note = (
            "This bank was not linked with user_transactions_dynamic. "
            "Disconnect, reconnect using that test username with pass_good, then try again."
        )
    elif inject_error:
        note = "Injection failed, but sync still ran for any pending Plaid updates."
    else:
        note = "Sync completed."

    return {
        "injected": injected,
        "inject_error": inject_error,
        "sync_error": sync_error,
        "webhook_fired": webhook_fired,
        "webhook_error": webhook_error,
        "synced_transactions": synced,
        "used_local_fallback": used_local_fallback,
        "note": note,
    }


async def mark_recurring_transactions(user_id: str, account_id: str) -> int:
    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    account = account_res.data
    access_token = decrypt_token(account["access_token_encrypted"])
    client = _get_plaid_client()

    try:
        request = TransactionsRecurringGetRequest(access_token=access_token)
        recurring_res = _plaid_to_dict(await run_db(client.transactions_recurring_get, request))
    except Exception:
        # Plaid sandbox can return malformed recurring streams; don't fail the whole sync.
        return 0

    recurring_ids: set[str] = set()
    for stream_key in ("inflow_streams", "outflow_streams"):
        for stream in recurring_res.get(stream_key, []):
            if isinstance(stream, dict):
                recurring_ids.update(stream.get("transaction_ids", []))
            else:
                recurring_ids.update(getattr(stream, "transaction_ids", []) or [])

    if not recurring_ids:
        return 0

    await run_db(
        lambda: sb.table("transactions")
        .update({"is_recurring": True})
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .eq("source_provider", "plaid")
        .in_("external_id", list(recurring_ids))
        .execute()
    )
    return len(recurring_ids)


async def disconnect_plaid_account(user_id: str, account_id: str) -> None:
    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .eq("provider", "plaid")
        .single()
        .execute()
    )
    account = account_res.data
    access_token = decrypt_token(account["access_token_encrypted"])
    client = _get_plaid_client()

    try:
        request = ItemRemoveRequest(access_token=access_token)
        await run_db(client.item_remove, request)
    except Exception:
        # Item may already be removed on Plaid's side; still clean up locally.
        pass

    await archive_transactions_for_account(user_id, account_id)

    await run_db(lambda: sb.table("connected_accounts").delete().eq("id", account_id).execute())
    await archive_detached_bank_transactions(user_id)
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert({"user_id": user_id, "provider": "plaid", "event": "revoked", "metadata": {"account_id": account_id}})
        .execute()
    )
