from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.database import get_supabase, run_db
from app.models.account import (
    MonoConfigResponse,
    MonoConnectRequest,
    PlaidExchangeRequest,
    PlaidLinkTokenResponse,
    SandboxSimulateRequest,
)
from app.services import mono_service, plaid_service
from app.services.transaction_enrichment import reprocess_stored_transactions

router = APIRouter(prefix="/banking", tags=["banking"])


@router.post("/plaid/link-token", response_model=PlaidLinkTokenResponse)
async def create_plaid_link_token(user_id: CurrentUser) -> PlaidLinkTokenResponse:
    try:
        link_token = await plaid_service.create_link_token(user_id)
        return PlaidLinkTokenResponse(link_token=link_token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/plaid/exchange")
async def exchange_plaid_token(user_id: CurrentUser, body: PlaidExchangeRequest) -> dict:
    try:
        account = await plaid_service.exchange_public_token(
            user_id, body.public_token, body.account_name
        )
        return {"account": account}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/mono/config", response_model=MonoConfigResponse)
async def mono_config(user_id: CurrentUser) -> MonoConfigResponse:
    return MonoConfigResponse(
        public_key=settings.mono_public_key,
        mono_env=settings.mono_env,
        configured=bool(settings.mono_public_key and settings.mono_secret_key),
    )


@router.post("/mono/connect")
async def connect_mono(user_id: CurrentUser, body: MonoConnectRequest) -> dict:
    try:
        account = await mono_service.connect_mono_account(
            user_id, body.code, body.account_name or "Mono Account"
        )
        return {"account": account}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/sync")
async def sync_accounts(
    user_id: CurrentUser,
    account_id: Optional[str] = Query(None),
) -> dict:
    sb = get_supabase()
    query = (
        sb.table("connected_accounts")
        .select("id, provider")
        .eq("user_id", user_id)
        .eq("status", "active")
    )
    if account_id:
        query = query.eq("id", account_id)
    accounts_res = await run_db(lambda: query.execute())

    total = 0
    recurring = 0
    errors: list[dict[str, str]] = []
    for account in accounts_res.data or []:
        try:
            if account["provider"] == "plaid":
                total += await plaid_service.sync_plaid_transactions(user_id, account["id"])
                recurring += await plaid_service.mark_recurring_transactions(user_id, account["id"])
            elif account["provider"] == "mono":
                total += await mono_service.sync_mono_transactions(user_id, account["id"])
        except Exception as exc:
            errors.append({"account_id": account["id"], "error": str(exc)})

    reprocessed = await reprocess_stored_transactions(user_id, account_id)

    return {
        "synced_transactions": total,
        "recurring_marked": recurring,
        "reprocessed_transactions": reprocessed,
        "errors": errors,
        "status": "partial" if errors else "ok",
    }


@router.get("/dev-info")
async def banking_dev_info() -> dict:
    return {
        "plaid_env": settings.plaid_env,
        "mono_env": settings.mono_env,
        "mono_configured": bool(settings.mono_public_key and settings.mono_secret_key),
        "webhook_configured": bool(settings.plaid_webhook_url),
        "webhook_url": settings.plaid_webhook_url or None,
    }


@router.post("/sandbox/simulate-purchase")
async def sandbox_simulate_purchase(user_id: CurrentUser, body: SandboxSimulateRequest) -> dict:
    if settings.plaid_env != "sandbox":
        raise HTTPException(status_code=400, detail="Sandbox tools are only available in Plaid sandbox")
    try:
        return await plaid_service.simulate_sandbox_purchase(
            user_id,
            body.account_id,
            body.description,
            body.amount,
            body.transaction_type,
        )
    except Exception as exc:
        return {
            "injected": False,
            "inject_error": str(exc),
            "sync_error": str(exc),
            "synced_transactions": 0,
            "webhook_fired": False,
            "note": "Simulation could not complete. See inject_error for details.",
        }
