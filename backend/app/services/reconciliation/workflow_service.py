"""Reconciliation run state machine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.reconciliation.audit_service import log_audit
from app.services.reconciliation.constants import RUN_TRANSITIONS
from app.services.reconciliation.balance_proof_service import recalculate_balance_proof


async def get_run(run_id: str, user_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .select("*")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return res.data


async def _pending_journal_count(run_id: str) -> int:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_adjustments")
        .select("id", count="exact")
        .eq("run_id", run_id)
        .eq("journal_entry_required", True)
        .eq("journal_entry_posted", False)
        .execute()
    )
    return res.count or 0


async def transition_run(
    run_id: str,
    user_id: str,
    *,
    target_status: str,
    comment: str | None = None,
) -> dict[str, Any]:
    run = await get_run(run_id, user_id)
    if not run:
        raise ValueError("Reconciliation run not found")

    current = run.get("status") or "DRAFT"
    allowed = RUN_TRANSITIONS.get(current, set())
    if target_status not in allowed:
        raise ValueError(f"Cannot transition from {current} to {target_status}")

    if target_status == "APPROVED":
        run = await recalculate_balance_proof(run_id, user_id)
        variance = float(run.get("variance") or 0)
        if abs(variance) > 0.01:
            raise ValueError(
                "Reconciliation cannot be approved while a variance exists. Review unclassified items."
            )
        pending = await _pending_journal_count(run_id)
        if pending > 0:
            raise ValueError(
                f"{pending} required journal entry(ies) must be posted before approval."
            )

    now = datetime.now(timezone.utc).isoformat()
    update: dict[str, Any] = {"status": target_status, "updated_at": now}

    self_approved = False
    if target_status == "IN_REVIEW":
        update["reviewed_by"] = user_id
    elif target_status == "APPROVED":
        update["approved_by"] = user_id
        update["approved_at"] = now
        preparer = run.get("created_by")
        if preparer == user_id:
            self_approved = True
        update["self_approved"] = self_approved
    elif target_status == "LOCKED":
        update["locked_at"] = now

    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .update(update)
        .eq("id", run_id)
        .eq("user_id", user_id)
        .execute()
    )
    updated = (res.data or [update])[0]

    await log_audit(
        run_id=run_id,
        user_id=user_id,
        actor_id=user_id,
        action=f"status_{current}_to_{target_status}",
        before_state={"status": current},
        after_state={"status": target_status, "self_approved": self_approved},
        comment=comment,
    )

    if target_status == "ADJUSTED":
        updated = await recalculate_balance_proof(run_id, user_id)

    return updated if isinstance(updated, dict) and updated.get("id") else (res.data or [run])[0]
