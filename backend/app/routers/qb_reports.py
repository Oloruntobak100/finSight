from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.services.qb_reports_service import fetch_report

router = APIRouter(prefix="/qb-reports", tags=["qb-reports"])


@router.get("/pnl")
async def profit_and_loss(
    user_id: CurrentUser,
    start_date: str = Query(...),
    end_date: str = Query(...),
    refresh: bool = Query(False),
) -> dict:
    try:
        return await fetch_report(
            user_id, "pnl", start_date=start_date, end_date=end_date, refresh=refresh
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/balance-sheet")
async def balance_sheet(
    user_id: CurrentUser,
    as_of_date: str = Query(...),
    refresh: bool = Query(False),
) -> dict:
    try:
        return await fetch_report(
            user_id, "balance-sheet", as_of_date=as_of_date, refresh=refresh
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cash-flow")
async def cash_flow(
    user_id: CurrentUser,
    start_date: str = Query(...),
    end_date: str = Query(...),
    refresh: bool = Query(False),
) -> dict:
    try:
        return await fetch_report(
            user_id, "cash-flow", start_date=start_date, end_date=end_date, refresh=refresh
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
