from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.models.synthetic_feed import (
    AccountDetailResponse,
    DateRangeRequest,
    FillHistoryRequest,
    GenerateResponse,
    ImportMonoResponse,
    ProfileUpdateRequest,
    SyntheticFeedStatusResponse,
)
from app.services import synthetic_feed_service as svc

router = APIRouter(prefix="/synthetic-feed", tags=["synthetic-feed"])


def _require_synthetic_feed() -> None:
    if not settings.synthetic_feed_allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Synthetic data feed is disabled. Set ENABLE_SYNTHETIC_FEED=true on the backend "
                "(Railway), or use Mono test_ sandbox keys."
            ),
        )


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    text = str(exc).lower()
    if "synthetic_feed" in text or "does not exist" in text or "42p01" in text:
        raise HTTPException(
            status_code=503,
            detail="Run Supabase migration 012_synthetic_feed.sql, then redeploy the backend.",
        ) from exc
    raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status", response_model=SyntheticFeedStatusResponse)
async def feed_status(user_id: CurrentUser) -> SyntheticFeedStatusResponse:
    _require_synthetic_feed()
    data = await svc.list_status(user_id)
    return SyntheticFeedStatusResponse(**data)


@router.get("/accounts/{account_id}", response_model=AccountDetailResponse)
async def account_detail(user_id: CurrentUser, account_id: str) -> AccountDetailResponse:
    _require_synthetic_feed()
    try:
        data = await svc.get_account_detail(user_id, account_id)
        return AccountDetailResponse(**data)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_service_error(exc)


@router.put("/accounts/{account_id}/profile")
async def update_profile(
    user_id: CurrentUser,
    account_id: str,
    body: ProfileUpdateRequest,
) -> dict:
    _require_synthetic_feed()
    profile = await svc.save_profile(
        user_id,
        account_id,
        persona_type=body.persona_type,
        persona_config=body.persona_config,
        daily_tx_target=body.daily_tx_target,
        live_interval_hours=body.live_interval_hours,
        auto_classify=body.auto_classify,
        historical_start=body.historical_start,
        historical_end=body.historical_end,
    )
    return {"profile": profile}


@router.post("/accounts/{account_id}/import-mono", response_model=ImportMonoResponse)
async def import_mono(
    user_id: CurrentUser,
    account_id: str,
    body: DateRangeRequest,
) -> ImportMonoResponse:
    _require_synthetic_feed()
    try:
        result = await svc.import_mono_history(user_id, account_id, body.start, body.end)
        return ImportMonoResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/fill-history", response_model=GenerateResponse)
async def fill_history(
    user_id: CurrentUser,
    account_id: str,
    body: FillHistoryRequest,
) -> GenerateResponse:
    _require_synthetic_feed()
    try:
        result = await svc.fill_sparse_history(
            user_id, account_id, body.start, body.end, count=body.count
        )
        return GenerateResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/live-feed/start")
async def live_feed_start(user_id: CurrentUser, account_id: str) -> dict:
    _require_synthetic_feed()
    return await svc.start_live_feed(user_id, account_id)


@router.post("/accounts/{account_id}/live-feed/pause")
async def live_feed_pause(user_id: CurrentUser, account_id: str) -> dict:
    _require_synthetic_feed()
    return await svc.pause_live_feed(user_id, account_id)


@router.post("/accounts/{account_id}/live-feed/run-now", response_model=GenerateResponse)
async def live_feed_run_now(user_id: CurrentUser, account_id: str) -> GenerateResponse:
    _require_synthetic_feed()
    result = await svc.run_live_drip_now(user_id, account_id)
    return GenerateResponse(**result)


@router.get("/accounts/{account_id}/runs")
async def list_runs(
    user_id: CurrentUser,
    account_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    _require_synthetic_feed()
    return await svc.list_runs(user_id, account_id, page=page, limit=limit)
