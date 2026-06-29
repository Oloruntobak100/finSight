from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import CurrentUser
from app.services.reconciliation_service import (
    get_reconciliation_options,
    reconcile,
)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


class ReconcileRequest(BaseModel):
    period_start: str | None = None
    period_end: str | None = None
    bank_account_id: str | None = None
    qb_bank_account_id: str | None = None
    transaction_side: Literal["debit", "credit", "all"] = "debit"


@router.get("/options")
async def reconciliation_options(user_id: CurrentUser) -> dict:
    return await get_reconciliation_options(user_id)


@router.post("/run")
async def run_reconciliation(
    user_id: CurrentUser,
    body: ReconcileRequest = ReconcileRequest(),
) -> dict:
    today = date.today()
    start = body.period_start or today.replace(day=1).isoformat()
    end = body.period_end or today.isoformat()
    try:
        return await reconcile(
            user_id,
            start,
            end,
            bank_account_id=body.bank_account_id,
            qb_bank_account_id=body.qb_bank_account_id,
            transaction_side=body.transaction_side,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/latest")
async def latest_reconciliation(user_id: CurrentUser) -> dict:
    from app.database import get_supabase, run_db

    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"run": None}
    return {"run": res.data[0]}
