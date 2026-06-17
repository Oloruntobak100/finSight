from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.database import get_supabase, run_db
from app.models.account import OAuthAuthorizeResponse
from app.services import mono_service, plaid_service, quickbooks_service, xero_service

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/quickbooks/authorize", response_model=OAuthAuthorizeResponse)
async def quickbooks_authorize(user_id: CurrentUser) -> OAuthAuthorizeResponse:
    url = quickbooks_service.build_authorize_url(user_id)
    return OAuthAuthorizeResponse(authorization_url=url)


@router.get("/quickbooks/callback")
async def quickbooks_callback(
    code: str = Query(...),
    realmId: str = Query(...),
    state: str = Query(...),
) -> RedirectResponse:
    user_id = state.split(":")[0]
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
    await quickbooks_service.disconnect(user_id, account_id)
    return {"status": "disconnected"}


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
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, provider, account_name, account_type, last_synced_at, status, created_at")
        .eq("user_id", user_id)
        .execute()
    )
    return {"accounts": res.data or []}
