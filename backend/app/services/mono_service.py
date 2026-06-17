import asyncio

from datetime import date

from typing import Any



import httpx



from app.config import settings

from app.database import get_supabase, run_db

from app.services.token_service import encrypt_token

from app.services.transaction_enrichment import (

    build_mono_transaction_row,

    load_user_category_rules,

)





MONO_BASE = "https://api.withmono.com"

ENRICHMENT_POLL_DELAYS = (3, 5, 8)





def _mono_headers() -> dict[str, str]:

    return {

        "mono-sec-key": settings.mono_secret_key,

        "Content-Type": "application/json",

        "accept": "application/json",

    }





def _unwrap_data(payload: dict[str, Any]) -> dict[str, Any]:

    data = payload.get("data")

    if isinstance(data, dict):

        return data

    return payload





async def _exchange_code(code: str) -> str:

    async with httpx.AsyncClient() as client:

        auth_res = await client.post(

            f"{MONO_BASE}/v2/accounts/auth",

            headers=_mono_headers(),

            json={"code": code},

            timeout=30.0,

        )

        auth_res.raise_for_status()

        body = auth_res.json()

        data = _unwrap_data(body)

        account_id = data.get("id")

        if not account_id:

            raise ValueError("Mono did not return an account ID")

        return account_id





async def _fetch_account_details(mono_account_id: str) -> dict[str, Any]:

    async with httpx.AsyncClient() as client:

        res = await client.get(

            f"{MONO_BASE}/v2/accounts/{mono_account_id}",

            headers=_mono_headers(),

            timeout=30.0,

        )

        res.raise_for_status()

        return _unwrap_data(res.json())





def _account_display_name(details: dict[str, Any], fallback: str) -> str:

    account = details.get("account") or {}

    institution = (account.get("institution") or {}).get("name")

    if institution:

        return institution

    if account.get("name"):

        return str(account["name"])

    return fallback





async def _wait_for_transaction_data(mono_account_id: str, attempts: int = 8) -> bool:

    for attempt in range(attempts):

        details = await _fetch_account_details(mono_account_id)

        meta = details.get("meta") or {}

        status = str(meta.get("data_status", "")).upper()

        retrieved = meta.get("retrieved_data") or []

        if status == "AVAILABLE":

            return True

        if status == "PARTIAL" and "transactions" in retrieved:

            return True

        if status in {"UNAVAILABLE", "FAILED"}:

            return False

        if attempt < attempts - 1:

            await asyncio.sleep(2)

    return False





async def _trigger_mono_enrichment(

    client: httpx.AsyncClient,

    mono_account_id: str,

    endpoint: str,

) -> bool:

    try:

        res = await client.post(

            f"{MONO_BASE}/v2/accounts/{mono_account_id}/transactions/{endpoint}",

            headers=_mono_headers(),

            timeout=30.0,

        )

        res.raise_for_status()

        return True

    except Exception:

        return False





def _mono_txn_has_enrichment(txn: dict[str, Any]) -> bool:

    metadata = txn.get("metadata") or {}

    category = metadata.get("category") or txn.get("category")

    has_category = bool(category) and str(category).lower() not in {"unknown", "null", "none", "n/a"}

    has_metadata = any(

        metadata.get(key) not in (None, "", "N/A")

        for key in ("payee", "reason", "channel", "payment_method", "payment_processor", "location", "ref_num")

    )

    return has_category or has_metadata





def _mono_enrichment_ratio(transactions: list[dict[str, Any]]) -> float:

    if not transactions:

        return 0.0

    enriched = sum(1 for txn in transactions if _mono_txn_has_enrichment(txn))

    return enriched / len(transactions)





async def _fetch_mono_transaction_pages(

    client: httpx.AsyncClient,

    mono_account_id: str,

) -> list[dict[str, Any]]:

    transactions: list[dict[str, Any]] = []

    page = 1

    while True:

        txn_res = await client.get(

            f"{MONO_BASE}/v2/accounts/{mono_account_id}/transactions",

            headers=_mono_headers(),

            params={"paginate": "true", "limit": 100, "page": page},

            timeout=30.0,

        )

        txn_res.raise_for_status()

        body = txn_res.json()

        batch = body.get("data") or []

        if not batch:

            break

        transactions.extend(batch)

        meta = body.get("meta") or {}

        if not meta.get("next"):

            break

        page += 1

    return transactions





async def _run_mono_enrichment_jobs(
    client: httpx.AsyncClient,
    mono_account_id: str,
) -> tuple[bool, bool]:
    return await asyncio.gather(
        _trigger_mono_enrichment(client, mono_account_id, "categorise"),
        _trigger_mono_enrichment(client, mono_account_id, "metadata"),
    )





async def _fetch_enriched_mono_transactions(

    client: httpx.AsyncClient,

    mono_account_id: str,

) -> list[dict[str, Any]]:

    transactions = await _fetch_mono_transaction_pages(client, mono_account_id)

    if not transactions:

        return transactions



    if _mono_enrichment_ratio(transactions) >= 0.35:

        return transactions



    triggered = await _run_mono_enrichment_jobs(client, mono_account_id)
    if not any(triggered):
        return transactions



    latest = transactions

    for delay in ENRICHMENT_POLL_DELAYS:

        await asyncio.sleep(delay)

        latest = await _fetch_mono_transaction_pages(client, mono_account_id)

        if _mono_enrichment_ratio(latest) >= 0.35:

            return latest



    return latest





async def _upsert_mono_transactions(

    sb: Any,

    user_id: str,

    account_id: str,

    transactions: list[dict[str, Any]],

    user_rules: dict[str, str],

) -> int:

    count = 0

    for txn in transactions:

        amount = float(txn.get("amount", 0)) / 100

        txn_type = "debit" if txn.get("type") == "debit" else "credit"

        row = build_mono_transaction_row(

            txn,

            user_id=user_id,

            account_id=account_id,

            amount=amount,

            txn_type=txn_type,

            currency=txn.get("currency") or "NGN",

            external_id=txn.get("id") or txn.get("_id"),

            user_rules=user_rules,

        )

        if not row["transaction_date"]:

            row["transaction_date"] = str(date.today())

        await run_db(

            lambda r=row: sb.table("transactions")

            .upsert(r, on_conflict="source_provider,external_id,user_id")

            .execute()

        )

        count += 1

    return count





async def connect_mono_account(user_id: str, code: str, account_name: str) -> dict[str, Any]:

    if not settings.mono_secret_key:

        raise ValueError("Mono secret key is not configured")



    mono_account_id = await _exchange_code(code)

    details = await _fetch_account_details(mono_account_id)

    resolved_name = _account_display_name(details, account_name or "Mono Account")



    sb = get_supabase()

    row = {

        "user_id": user_id,

        "provider": "mono",

        "account_name": resolved_name,

        "account_type": "bank",

        "access_token_encrypted": encrypt_token(mono_account_id),

        "external_account_id": mono_account_id,

        "status": "active",

    }

    result = await run_db(lambda: sb.table("connected_accounts").insert(row).execute())

    return result.data[0]





async def sync_mono_transactions(user_id: str, account_id: str) -> int:

    sb = get_supabase()

    account_res = await run_db(

        lambda: sb.table("connected_accounts")

        .select("*")

        .eq("id", account_id)

        .eq("user_id", user_id)

        .single()

        .execute()

    )

    mono_account_id = account_res.data["external_account_id"]



    if not await _wait_for_transaction_data(mono_account_id):

        raise ValueError(

            "Mono account data is not ready yet. Wait a moment and try Sync All again."

        )



    user_rules = await load_user_category_rules(user_id, sb)

    async with httpx.AsyncClient() as client:

        transactions = await _fetch_enriched_mono_transactions(client, mono_account_id)

        count = await _upsert_mono_transactions(sb, user_id, account_id, transactions, user_rules)



    await run_db(

        lambda: sb.table("connected_accounts")

        .update({"last_synced_at": date.today().isoformat()})

        .eq("id", account_id)

        .execute()

    )

    return count





async def disconnect_mono_account(user_id: str, account_id: str) -> None:

    sb = get_supabase()

    await run_db(

        lambda: sb.table("connected_accounts")

        .delete()

        .eq("id", account_id)

        .eq("user_id", user_id)

        .eq("provider", "mono")

        .execute()

    )

    await run_db(

        lambda: sb.table("oauth_audit_log")

        .insert({"user_id": user_id, "provider": "mono", "event": "revoked", "metadata": {"account_id": account_id}})

        .execute()

    )


