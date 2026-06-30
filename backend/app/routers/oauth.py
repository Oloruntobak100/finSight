from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.database import get_supabase, run_db
from app.models.account import (
    OAuthAuthorizeResponse,
    QuickBooksConfigResponse,
    QuickBooksExchangeRequest,
)
from app.services import mono_service, plaid_service, quickbooks_service, xero_service

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/quickbooks/config", response_model=QuickBooksConfigResponse)
async def quickbooks_config(user_id: CurrentUser) -> QuickBooksConfigResponse:
    _ = user_id
    return QuickBooksConfigResponse(**quickbooks_service.get_oauth_config())


@router.get("/quickbooks/status")
async def quickbooks_status(user_id: CurrentUser) -> dict:
    return await quickbooks_service.get_connection_status(user_id)


@router.post("/quickbooks/exchange")
async def quickbooks_exchange(user_id: CurrentUser, body: QuickBooksExchangeRequest) -> dict:
    try:
        account = await quickbooks_service.exchange_code(user_id, body.code, body.realm_id)
        return {"status": "ok", "account": account}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/quickbooks/company-info")
async def quickbooks_company_info(user_id: CurrentUser) -> dict:
    try:
        return await quickbooks_service.get_company_info(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/quickbooks/authorize", response_model=OAuthAuthorizeResponse)
async def quickbooks_authorize(user_id: CurrentUser, state: str = Query(..., min_length=8)) -> OAuthAuthorizeResponse:
    """Legacy: build authorize URL when frontend supplies a CSRF state token."""
    url = quickbooks_service.build_authorize_url(state)
    return OAuthAuthorizeResponse(authorization_url=url)


@router.get("/quickbooks/callback", deprecated=True)
async def quickbooks_callback_legacy(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    """Deprecated — Intuit should redirect to the frontend callback. Kept for old redirect URIs."""
    user_id = state.split(":")[0] if ":" in state else ""
    if not user_id:
        return RedirectResponse(f"{settings.frontend_url}/accounts?error=invalid_oauth_state")
    try:
        await quickbooks_service.exchange_code(user_id, code, realmId)
        return RedirectResponse(f"{settings.frontend_url}/accounts?connected=quickbooks")
    except Exception as exc:
        return RedirectResponse(f"{settings.frontend_url}/accounts?error={str(exc)}")


@router.delete("/plaid/disconnect")
async def plaid_disconnect(user_id: CurrentUser, account_id: str = Query(...)) -> dict:
    try:
        await plaid_service.disconnect_plaid_account(user_id, account_id)
        return {"status": "disconnected"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/mono/disconnect")
async def mono_disconnect(user_id: CurrentUser, account_id: str = Query(...)) -> dict:
    try:
        await mono_service.disconnect_mono_account(user_id, account_id)
        return {"status": "disconnected"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/quickbooks/disconnect")
async def quickbooks_disconnect(user_id: CurrentUser, account_id: str = Query(...)) -> dict:
    try:
        await quickbooks_service.disconnect(user_id, account_id)
        return {"status": "disconnected"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/xero/authorize", response_model=OAuthAuthorizeResponse)
async def xero_authorize(user_id: CurrentUser) -> OAuthAuthorizeResponse:
    url = xero_service.build_authorize_url(user_id)
    return OAuthAuthorizeResponse(authorization_url=url)


@router.get("/xero/callback")
async def xero_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    user_id = state.split(":")[0]
    try:
        await xero_service.exchange_code(user_id, code)
        return RedirectResponse(f"{settings.frontend_url}/accounts?connected=xero")
    except Exception as exc:
        return RedirectResponse(f"{settings.frontend_url}/accounts?error={str(exc)}")


@router.delete("/xero/disconnect")
async def xero_disconnect(user_id: CurrentUser, account_id: str = Query(...)) -> dict:
    await xero_service.disconnect(user_id, account_id)
    return {"status": "disconnected"}


@router.get("/accounts")
async def list_connected_accounts(user_id: CurrentUser) -> dict:
    from app.config import settings

    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, provider, account_name, account_type, last_synced_at, status, created_at, external_account_id")
        .eq("user_id", user_id)
        .execute()
    )
    accounts = []
    for row in res.data or []:
        if row.get("status") == "disconnected":
            continue
        item = dict(row)
        if item.get("provider") == "quickbooks":
            item["environment"] = settings.quickbooks_env
        elif item.get("provider") == "plaid":
            item["environment"] = settings.plaid_env
        elif item.get("provider") == "mono":
            item["environment"] = settings.mono_env
        accounts.append(item)
    return {"accounts": accounts}
