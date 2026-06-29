"""Post journal entries to QuickBooks from reconciliation adjustments."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.quickbooks_service import qb_company_post_json
from app.services.reconciliation.audit_service import log_audit
from app.services.reconciliation.balance_proof_service import recalculate_balance_proof


async def post_journal_entry(
    user_id: str,
    run_id: str,
    adjustment_id: str,
) -> dict[str, Any]:
    sb = get_supabase()
    adj_res = await run_db(
        lambda: sb.table("reconciliation_adjustments")
        .select("*")
        .eq("id", adjustment_id)
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    adj = adj_res.data
    if not adj:
        raise ValueError("Adjustment not found")

    run_res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .select("qb_bank_account_id, period_end")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    run = run_res.data
    if not run:
        raise ValueError("Run not found")

    bank_id = str(run.get("qb_bank_account_id") or "")
    offset_id = str(adj.get("offset_qb_account_id") or "")
    if not bank_id or not offset_id:
        raise ValueError("Bank account and offset COA account are required")

    amount = abs(float(adj.get("amount") or 0))
    adj_type = adj.get("adjustment_type") or ""
    txn_date = str(run.get("period_end") or datetime.now(timezone.utc).date().isoformat())[:10]

    if adj_type in ("BANK_CHARGE", "NSF_RETURN", "BOOK_ERROR"):
        lines = [
            {"JournalEntryLineDetail": {"PostingType": "Debit", "AccountRef": {"value": offset_id}}, "DetailType": "JournalEntryLineDetail", "Amount": amount},
            {"JournalEntryLineDetail": {"PostingType": "Credit", "AccountRef": {"value": bank_id}}, "DetailType": "JournalEntryLineDetail", "Amount": amount},
        ]
    elif adj_type in ("BANK_INTEREST", "UNRECORDED_BANK_CREDIT"):
        lines = [
            {"JournalEntryLineDetail": {"PostingType": "Debit", "AccountRef": {"value": bank_id}}, "DetailType": "JournalEntryLineDetail", "Amount": amount},
            {"JournalEntryLineDetail": {"PostingType": "Credit", "AccountRef": {"value": offset_id}}, "DetailType": "JournalEntryLineDetail", "Amount": amount},
        ]
    else:
        raise ValueError(f"Journal entry not supported for adjustment type {adj_type}")

    payload = {
        "TxnDate": txn_date,
        "PrivateNote": adj.get("description") or f"FinSight reconciliation {run_id}",
        "Line": lines,
    }

    data = await qb_company_post_json(user_id, "/journalentry?minorversion=75", payload)
    entry = data.get("JournalEntry") or {}
    entry_id = str(entry.get("Id") or "")

    await run_db(
        lambda: sb.table("reconciliation_adjustments")
        .update({"journal_entry_posted": True, "journal_entry_id": entry_id})
        .eq("id", adjustment_id)
        .execute()
    )

    await log_audit(
        run_id=run_id,
        user_id=user_id,
        actor_id=user_id,
        action="journal_entry_posted",
        after_state={"adjustment_id": adjustment_id, "journal_entry_id": entry_id},
    )

    await recalculate_balance_proof(run_id, user_id)
    return {"journal_entry_id": entry_id, "posted": True}


async def create_adjustment(
    user_id: str,
    run_id: str,
    *,
    item_id: str | None,
    adjustment_type: str,
    affects_side: str,
    amount: float,
    description: str | None = None,
    offset_qb_account_id: str | None = None,
    offset_qb_account_name: str | None = None,
    journal_entry_required: bool = False,
) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "run_id": run_id,
        "user_id": user_id,
        "item_id": item_id,
        "adjustment_type": adjustment_type,
        "affects_side": affects_side,
        "amount": abs(amount),
        "description": description,
        "offset_qb_account_id": offset_qb_account_id,
        "offset_qb_account_name": offset_qb_account_name,
        "journal_entry_required": journal_entry_required,
        "journal_entry_posted": False,
    }
    res = await run_db(lambda: sb.table("reconciliation_adjustments").insert(row).execute())
    created = (res.data or [row])[0]
    await recalculate_balance_proof(run_id, user_id)
    return created


async def list_adjustments(run_id: str, user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_adjustments")
        .select("*")
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    return res.data or []
