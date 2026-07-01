import asyncio
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import settings
from app.database import get_supabase, run_db
from app.services.token_service import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

INTUIT_OAUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
INTUIT_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
INTUIT_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
QB_SCOPE = "com.intuit.quickbooks.accounting"
ACCESS_TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


def _basic_auth_header() -> str:
    raw = f"{settings.quickbooks_client_id}:{settings.quickbooks_client_secret}"
    return base64.b64encode(raw.encode()).decode()


def get_redirect_uri() -> str:
    configured = (settings.quickbooks_redirect_uri or "").strip()
    if configured:
        return configured.rstrip("/")
    return f"{settings.frontend_url.rstrip('/')}/oauth/quickbooks/callback"


def get_oauth_config() -> dict[str, Any]:
    return {
        "client_id": settings.quickbooks_client_id,
        "redirect_uri": get_redirect_uri(),
        "scope": QB_SCOPE,
        "oauth_url": INTUIT_OAUTH_URL,
        "environment": settings.quickbooks_env,
        "configured": bool(settings.quickbooks_client_id and settings.quickbooks_client_secret),
    }


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.quickbooks_client_id,
        "response_type": "code",
        "scope": QB_SCOPE,
        "redirect_uri": get_redirect_uri(),
        "state": state,
    }
    return f"{INTUIT_OAUTH_URL}?{urlencode(params)}"


async def _exchange_tokens(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            INTUIT_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {_basic_auth_header()}",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": get_redirect_uri(),
            },
        )
        if not res.is_success:
            logger.error("QuickBooks token exchange failed: %s", res.text)
            res.raise_for_status()
        return res.json()


async def _refresh_tokens(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(
            INTUIT_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {_basic_auth_header()}",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if not res.is_success:
            logger.error("QuickBooks token refresh failed: %s", res.text)
            res.raise_for_status()
        return res.json()


def _token_expiry(tokens: dict[str, Any]) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    access_exp = now + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    refresh_seconds = int(tokens.get("x_refresh_token_expires_in", 8726400))
    refresh_exp = now + timedelta(seconds=refresh_seconds)
    return access_exp, refresh_exp


async def _fetch_company_name(access_token: str, realm_id: str) -> str | None:
    url = (
        f"{settings.quickbooks_base_url}/v3/company/{realm_id}/companyinfo/{realm_id}"
        "?minorversion=75"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
            if not res.is_success:
                return None
            body = res.json()
            company = (body.get("CompanyInfo") or {}) if isinstance(body, dict) else {}
            name = company.get("CompanyName") or company.get("LegalName")
            return str(name) if name else None
    except Exception:
        logger.exception("Failed to fetch QuickBooks company info for realm %s", realm_id)
        return None


async def _get_quickbooks_account_row(user_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("provider", "quickbooks")
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


async def find_qb_account_by_realm(user_id: str, realm_id: str) -> dict[str, Any] | None:
    """Find a QuickBooks connection row for this company (any status)."""
    if not realm_id:
        return None
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("provider", "quickbooks")
        .eq("realm_id", realm_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


async def soft_disconnect_quickbooks(user_id: str, account_id: str) -> None:
    """Revoke tokens but keep the row so reconnect by realm_id restores continuity."""
    sb = get_supabase()
    account_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .eq("provider", "quickbooks")
        .single()
        .execute()
    )
    account = account_res.data
    if not account:
        raise ValueError("QuickBooks connection not found")

    token_enc = account.get("refresh_token_encrypted") or account.get("access_token_encrypted")
    if token_enc:
        token = decrypt_token(token_enc)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    INTUIT_REVOKE_URL,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {_basic_auth_header()}",
                    },
                    data={"token": token},
                )
        except Exception:
            logger.exception("QuickBooks token revoke failed for account %s", account_id)

    await run_db(
        lambda: sb.table("connected_accounts")
        .update(
            {
                "status": "disconnected",
                "access_token_encrypted": None,
                "refresh_token_encrypted": None,
            }
        )
        .eq("id", account_id)
        .eq("user_id", user_id)
        .execute()
    )
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert(
            {
                "user_id": user_id,
                "provider": "quickbooks",
                "event": "revoked",
                "metadata": {
                    "account_id": account_id,
                    "realm_id": account.get("realm_id"),
                    "soft_disconnect": True,
                },
            }
        )
        .execute()
    )


async def exchange_code(user_id: str, code: str, realm_id: str) -> dict[str, Any]:
    if not settings.quickbooks_client_id or not settings.quickbooks_client_secret:
        raise ValueError("QuickBooks is not configured on the server")

    tokens = await _exchange_tokens(code)
    access_exp, refresh_exp = _token_expiry(tokens)
    company_name = await _fetch_company_name(tokens["access_token"], realm_id)
    account_name = company_name or f"QuickBooks ({realm_id})"

    row = {
        "user_id": user_id,
        "provider": "quickbooks",
        "account_name": account_name,
        "account_type": "accounting",
        "access_token_encrypted": encrypt_token(tokens["access_token"]),
        "refresh_token_encrypted": encrypt_token(tokens["refresh_token"]),
        "token_expires_at": access_exp.isoformat(),
        "refresh_token_expires_at": refresh_exp.isoformat(),
        "realm_id": realm_id,
        "status": "active",
    }

    sb = get_supabase()
    existing_realm = await find_qb_account_by_realm(user_id, realm_id)
    active_other = await _get_quickbooks_account_row(user_id)
    if active_other and active_other.get("id") != (existing_realm or {}).get("id"):
        if active_other.get("realm_id") != realm_id:
            await soft_disconnect_quickbooks(user_id, active_other["id"])

    reconnected = False
    if existing_realm:
        reconnected = existing_realm.get("status") == "disconnected"
        result = await run_db(
            lambda: sb.table("connected_accounts")
            .update(row)
            .eq("id", existing_realm["id"])
            .execute()
        )
        account = (result.data or [existing_realm])[0]
    else:
        result = await run_db(lambda: sb.table("connected_accounts").insert(row).execute())
        account = result.data[0]

    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert(
            {
                "user_id": user_id,
                "provider": "quickbooks",
                "event": "reauthorized" if reconnected else "authorized",
                "metadata": {
                    "realm_id": realm_id,
                    "account_name": account_name,
                    "reconnected": reconnected,
                },
            }
        )
        .execute()
    )

    try:
        await sync_chart_of_accounts(user_id)
    except Exception:
        logger.warning("COA auto-sync after QuickBooks connect failed for user %s", user_id)

    return account


async def get_connection_status(user_id: str) -> dict[str, Any]:
    account = await _get_quickbooks_account_row(user_id)
    if not account:
        return {"connected": False}

    now = datetime.now(timezone.utc)
    refresh_exp_raw = account.get("refresh_token_expires_at")
    if refresh_exp_raw:
        refresh_exp = datetime.fromisoformat(str(refresh_exp_raw).replace("Z", "+00:00"))
        if now >= refresh_exp:
            return {"connected": False, "expired": True}

    access_exp_raw = account.get("token_expires_at")
    access_expires_in_min = None
    refresh_expires_in_days = None
    if access_exp_raw:
        access_exp = datetime.fromisoformat(str(access_exp_raw).replace("Z", "+00:00"))
        access_expires_in_min = max(0, int((access_exp - now).total_seconds() // 60))
    if refresh_exp_raw:
        refresh_exp = datetime.fromisoformat(str(refresh_exp_raw).replace("Z", "+00:00"))
        refresh_expires_in_days = max(0, int((refresh_exp - now).total_seconds() // 86400))

    return {
        "connected": True,
        "account_id": account["id"],
        "realm_id": account.get("realm_id"),
        "account_name": account.get("account_name"),
        "environment": settings.quickbooks_env,
        "access_token_expires_in_min": access_expires_in_min,
        "refresh_token_expires_in_days": refresh_expires_in_days,
    }


async def get_valid_account(user_id: str) -> dict[str, Any] | None:
    account = await _get_quickbooks_account_row(user_id)
    if not account:
        return None

    now = datetime.now(timezone.utc)
    refresh_exp_raw = account.get("refresh_token_expires_at")
    if refresh_exp_raw:
        refresh_exp = datetime.fromisoformat(str(refresh_exp_raw).replace("Z", "+00:00"))
        if now >= refresh_exp:
            return None

    access_exp_raw = account.get("token_expires_at")
    if access_exp_raw:
        access_exp = datetime.fromisoformat(str(access_exp_raw).replace("Z", "+00:00"))
        if access_exp > now + ACCESS_TOKEN_REFRESH_BUFFER:
            return account

    refresh_enc = account.get("refresh_token_encrypted")
    if not refresh_enc:
        return account

    tokens = await _refresh_tokens(decrypt_token(refresh_enc))
    access_exp, refresh_exp = _token_expiry(tokens)
    update = {
        "access_token_encrypted": encrypt_token(tokens["access_token"]),
        "refresh_token_encrypted": encrypt_token(tokens.get("refresh_token", decrypt_token(refresh_enc))),
        "token_expires_at": access_exp.isoformat(),
        "refresh_token_expires_at": refresh_exp.isoformat(),
    }
    sb = get_supabase()
    await run_db(
        lambda: sb.table("connected_accounts").update(update).eq("id", account["id"]).execute()
    )
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert({"user_id": user_id, "provider": "quickbooks", "event": "refreshed"})
        .execute()
    )
    return {**account, **update}


async def qb_company_get_json(user_id: str, company_path: str) -> dict[str, Any]:
    return await _qb_company_request(user_id, "GET", company_path)


async def qb_company_post_json(user_id: str, company_path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await _qb_company_request(user_id, "POST", company_path, body=body)


async def _qb_company_request(
    user_id: str,
    method: str,
    company_path: str,
    body: dict[str, Any] | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    account = await get_valid_account(user_id)
    if not account:
        raise ValueError("QuickBooks not connected")

    realm_id = account.get("realm_id")
    if not realm_id:
        raise ValueError("QuickBooks realm_id missing")

    access_token = decrypt_token(account["access_token_encrypted"])
    path = company_path if company_path.startswith("/") else f"/{company_path}"
    url = f"{settings.quickbooks_base_url}/v3/company/{realm_id}{path}"

    last_error: Exception | None = None
    retryable = (
        httpx.RemoteProtocolError,
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.NetworkError,
    )
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=45.0, http2=False) as client:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                }
                if method.upper() == "POST":
                    headers["Content-Type"] = "application/json"
                    res = await client.post(url, headers=headers, json=body or {})
                else:
                    res = await client.get(url, headers=headers)

                if res.status_code == 429 and attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if not res.is_success:
                    raise ValueError(f"QuickBooks API error ({res.status_code}): {res.text}")
                return res.json()
        except retryable as exc:
            last_error = exc
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
                continue
            raise ValueError(f"QuickBooks API connection error: {exc}") from exc
        except ValueError as exc:
            last_error = exc
            if "429" in str(exc) and attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
    if last_error:
        raise last_error
    raise ValueError("QuickBooks API request failed")


async def qb_query(user_id: str, sql: str) -> dict[str, Any]:
    encoded = quote(sql, safe="")
    return await qb_company_get_json(user_id, f"/query?query={encoded}&minorversion=75")


async def _purge_stale_coa(
    user_id: str,
    realm_id: str,
    synced_ids: set[str],
) -> int:
    """Remove cached COA rows (and orphaned mappings) no longer present in QuickBooks."""
    sb = get_supabase()

    await run_db(
        lambda: sb.table("qb_chart_of_accounts")
        .delete()
        .eq("user_id", user_id)
        .neq("realm_id", realm_id)
        .execute()
    )

    res = await run_db(
        lambda: sb.table("qb_chart_of_accounts")
        .select("qb_account_id")
        .eq("user_id", user_id)
        .eq("realm_id", realm_id)
        .execute()
    )
    stale_ids = [
        str(row["qb_account_id"])
        for row in (res.data or [])
        if str(row["qb_account_id"]) not in synced_ids
    ]
    if not stale_ids:
        return 0

    await run_db(
        lambda ids=stale_ids: sb.table("qb_account_mappings")
        .delete()
        .eq("user_id", user_id)
        .in_("qb_account_id", ids)
        .execute()
    )
    await run_db(
        lambda ids=stale_ids: sb.table("qb_chart_of_accounts")
        .delete()
        .eq("user_id", user_id)
        .in_("qb_account_id", ids)
        .execute()
    )
    return len(stale_ids)


async def sync_chart_of_accounts(user_id: str) -> dict[str, Any]:
    account = await get_valid_account(user_id)
    if not account:
        raise ValueError("QuickBooks not connected")

    realm_id = account["realm_id"]
    data = await qb_query(user_id, "SELECT * FROM Account WHERE Active = true MAXRESULTS 1000")
    query_response = data.get("QueryResponse") or {}
    accounts = query_response.get("Account") or []
    if isinstance(accounts, dict):
        accounts = [accounts]

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "user_id": user_id,
            "realm_id": realm_id,
            "qb_account_id": str(item.get("Id")),
            "name": item.get("Name") or "Unknown",
            "account_type": item.get("AccountType"),
            "account_sub_type": item.get("AccountSubType"),
            "active": item.get("Active", True),
            "synced_at": now,
        }
        for item in accounts
        if item.get("Id")
    ]
    synced_ids = {row["qb_account_id"] for row in rows}

    sb = get_supabase()
    if rows:
        await run_db(
            lambda: sb.table("qb_chart_of_accounts")
            .upsert(rows, on_conflict="user_id,qb_account_id")
            .execute()
        )

    removed = await _purge_stale_coa(user_id, realm_id, synced_ids)

    return {"synced": len(rows), "removed": removed, "realm_id": realm_id}


async def get_company_info(user_id: str) -> dict[str, Any]:
    account = await get_valid_account(user_id)
    if not account:
        raise ValueError("QuickBooks not connected")

    realm_id = account["realm_id"]
    data = await qb_company_get_json(user_id, f"/companyinfo/{realm_id}?minorversion=75")
    company = data.get("CompanyInfo") or {}
    if not company:
        raise ValueError("Unexpected QuickBooks response (missing CompanyInfo)")

    return {
        "company_name": company.get("CompanyName"),
        "legal_name": company.get("LegalName"),
        "email": (company.get("Email") or {}).get("Address"),
        "phone": (company.get("PrimaryPhone") or {}).get("FreeFormNumber"),
        "fiscal_year_start": company.get("FiscalYearStartMonth"),
        "company_start_date": company.get("CompanyStartDate"),
    }


async def refresh_token_if_needed(account: dict[str, Any]) -> dict[str, Any]:
    refreshed = await get_valid_account(account["user_id"])
    return refreshed or account


async def disconnect(user_id: str, account_id: str) -> None:
    await soft_disconnect_quickbooks(user_id, account_id)
