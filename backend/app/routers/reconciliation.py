from fastapi import APIRouter, HTTPException, Query

from app.auth.dependencies import CurrentUser
from app.models.reconciliation import (
    CreateAdjustmentRequest,
    CreateRunRequest,
    TransitionRequest,
    UpdateItemRequest,
)
from app.services.reconciliation import (
    create_adjustment,
    get_balance_proof,
    get_run,
    get_setup,
    list_adjustments,
    list_audit_log,
    list_items,
    post_journal_entry,
    preview_balances,
    recalculate_balance_proof,
    run_matching_engine,
    transition_run,
    update_item,
)
from app.services.reconciliation_service import get_reconciliation_options, reconcile

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


@router.get("/setup")
async def reconciliation_setup(user_id: CurrentUser) -> dict:
    return await get_setup(user_id)


@router.get("/options")
async def reconciliation_options(user_id: CurrentUser) -> dict:
    return await get_reconciliation_options(user_id)


@router.get("/preview-balances")
async def reconciliation_preview_balances(
    user_id: CurrentUser,
    mono_account_id: str = Query(...),
    qb_bank_account_id: str = Query(...),
    period_end: str = Query(...),
) -> dict:
    try:
        return await preview_balances(
            user_id,
            mono_account_id=mono_account_id,
            qb_bank_account_id=qb_bank_account_id,
            period_end=period_end,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs")
async def create_reconciliation_run(user_id: CurrentUser, body: CreateRunRequest) -> dict:
    try:
        return await run_matching_engine(
            user_id,
            mono_account_id=body.mono_account_id,
            qb_bank_account_id=body.qb_bank_account_id,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
async def get_reconciliation_run(user_id: CurrentUser, run_id: str) -> dict:
    run = await get_run(run_id, user_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    proof = (run.get("summary") or {}).get("balance_proof")
    if proof:
        run["balance_proof"] = proof
    return run


@router.get("/runs/{run_id}/items")
async def get_reconciliation_items(
    user_id: CurrentUser,
    run_id: str,
    match_status: str | None = Query(None),
) -> dict:
    items = await list_items(run_id, user_id, match_status=match_status)
    return {"items": items}


@router.patch("/runs/{run_id}/items/{item_id}")
async def patch_reconciliation_item(
    user_id: CurrentUser,
    run_id: str,
    item_id: str,
    body: UpdateItemRequest,
) -> dict:
    try:
        item = await update_item(
            user_id,
            run_id,
            item_id,
            match_status=body.match_status,
            confirm_suggested=body.confirm_suggested,
            reject_suggested=body.reject_suggested,
        )
        return {"item": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/balance-proof")
async def get_run_balance_proof(user_id: CurrentUser, run_id: str) -> dict:
    try:
        proof = await get_balance_proof(run_id, user_id)
        return {"balance_proof": proof}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/recalculate")
async def recalculate_run(user_id: CurrentUser, run_id: str) -> dict:
    try:
        run = await recalculate_balance_proof(run_id, user_id)
        return run
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/adjustments")
async def get_run_adjustments(user_id: CurrentUser, run_id: str) -> dict:
    items = await list_adjustments(run_id, user_id)
    return {"adjustments": items}


@router.post("/runs/{run_id}/adjustments")
async def add_run_adjustment(
    user_id: CurrentUser,
    run_id: str,
    body: CreateAdjustmentRequest,
) -> dict:
    try:
        adj = await create_adjustment(
            user_id,
            run_id,
            item_id=body.item_id,
            adjustment_type=body.adjustment_type,
            affects_side=body.affects_side,
            amount=body.amount,
            description=body.description,
            offset_qb_account_id=body.offset_qb_account_id,
            offset_qb_account_name=body.offset_qb_account_name,
            journal_entry_required=body.journal_entry_required,
        )
        return {"adjustment": adj}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/adjustments/{adjustment_id}/post")
async def post_run_journal_entry(
    user_id: CurrentUser,
    run_id: str,
    adjustment_id: str,
) -> dict:
    try:
        return await post_journal_entry(user_id, run_id, adjustment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/{run_id}/transition")
async def transition_reconciliation_run(
    user_id: CurrentUser,
    run_id: str,
    body: TransitionRequest,
) -> dict:
    try:
        run = await transition_run(
            run_id,
            user_id,
            target_status=body.target_status,
            comment=body.comment,
        )
        return {"run": run}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}/audit")
async def get_run_audit_log(user_id: CurrentUser, run_id: str) -> dict:
    entries = await list_audit_log(run_id, user_id)
    return {"entries": entries}


# Legacy endpoint — kept for backward compatibility
@router.post("/run")
async def run_reconciliation_legacy(user_id: CurrentUser, body: dict | None = None) -> dict:
    from datetime import date
    from typing import Literal

    from pydantic import BaseModel

    class LegacyBody(BaseModel):
        period_start: str | None = None
        period_end: str | None = None
        bank_account_id: str | None = None
        qb_bank_account_id: str | None = None
        transaction_side: Literal["debit", "credit", "all"] = "debit"

    parsed = LegacyBody(**(body or {}))
    today = date.today()
    start = parsed.period_start or today.replace(day=1).isoformat()
    end = parsed.period_end or today.isoformat()
    try:
        return await reconcile(
            user_id,
            start,
            end,
            bank_account_id=parsed.bank_account_id,
            qb_bank_account_id=parsed.qb_bank_account_id,
            transaction_side=parsed.transaction_side,
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
