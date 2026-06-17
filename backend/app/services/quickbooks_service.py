import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.database import get_supabase, run_db
from app.services.token_service import decrypt_token, encrypt_token

INTUIT_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
INTUIT_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"


def build_authorize_url(user_id: str) -> str:
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": settings.quickbooks_client_id,
        "response_type": "code",
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": settings.quickbooks_redirect_uri,
        "state": f"{user_id}:{state}",
    }
    return f"{settings.quickbooks_oauth_base}?{urlencode(params)}"


async def exchange_code(user_id: str, code: str, realm_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        res = await client.post(
            INTUIT_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.quickbooks_redirect_uri,
            },
            auth=(settings.quickbooks_client_id, settings.quickbooks_client_secret),
        )
        res.raise_for_status()
        tokens = res.json()

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "provider": "quickbooks",
        "account_name": f"QuickBooks ({realm_id})",
        "account_type": "accounting",
        "access_token_encrypted": encrypt_token(tokens["access_token"]),
        "refresh_token_encrypted": encrypt_token(tokens["refresh_token"]),
        "token_expires_at": expires_at.isoformat(),
        "realm_id": realm_id,
        "status": "active",
    }
    result = await run_db(lambda: sb.table("connected_accounts").insert(row).execute())
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert({"user_id": user_id, "provider": "quickbooks", "event": "authorized", "metadata": {"realm_id": realm_id}})
        .execute()
    )
    return result.data[0]


async def refresh_token_if_needed(account: dict[str, Any]) -> dict[str, Any]:
    expires_at = account.get("token_expires_at")
    if not expires_at:
        return account

    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if expiry > datetime.now(timezone.utc) + timedelta(minutes=10):
        return account

    refresh = decrypt_token(account["refresh_token_encrypted"])
    async with httpx.AsyncClient() as client:
        res = await client.post(
            INTUIT_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh},
            auth=(settings.quickbooks_client_id, settings.quickbooks_client_secret),
        )
        res.raise_for_status()
        tokens = res.json()

    new_expires = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    sb = get_supabase()
    update = {
        "access_token_encrypted": encrypt_token(tokens["access_token"]),
        "refresh_token_encrypted": encrypt_token(tokens.get("refresh_token", refresh)),
        "token_expires_at": new_expires.isoformat(),
    }
    await run_db(lambda: sb.table("connected_accounts").update(update).eq("id", account["id"]).execute())
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert({"user_id": account["user_id"], "provider": "quickbooks", "event": "refreshed"})
        .execute()
    )
    return {**account, **update}


async def disconnect(user_id: str, account_id: str) -> None:
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
    token = decrypt_token(account["refresh_token_encrypted"] or account["access_token_encrypted"])
    async with httpx.AsyncClient() as client:
        await client.post(
            INTUIT_REVOKE_URL,
            data={"token": token},
            auth=(settings.quickbooks_client_id, settings.quickbooks_client_secret),
        )
    await run_db(lambda: sb.table("connected_accounts").delete().eq("id", account_id).execute())
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert({"user_id": user_id, "provider": "quickbooks", "event": "revoked"})
        .execute()
    )
