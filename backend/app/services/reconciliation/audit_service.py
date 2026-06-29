"""Immutable audit trail for reconciliation runs."""

from __future__ import annotations

from typing import Any

from app.database import get_supabase, run_db


async def log_audit(
    *,
    run_id: str,
    user_id: str,
    actor_id: str,
    action: str,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "run_id": run_id,
        "user_id": user_id,
        "actor_id": actor_id,
        "action": action,
        "before_state": before_state,
        "after_state": after_state,
        "comment": comment,
    }
    res = await run_db(lambda: sb.table("reconciliation_audit_log").insert(row).execute())
    return (res.data or [row])[0]


async def list_audit_log(run_id: str, user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_audit_log")
        .select("*")
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []
