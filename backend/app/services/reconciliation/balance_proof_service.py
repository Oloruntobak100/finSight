"""Balance proof assembly for bank reconciliation."""

from __future__ import annotations

from typing import Any

from app.database import get_supabase, run_db

BANK_ADD_STATUSES = frozenset({"DEPOSITS_IN_TRANSIT"})
BANK_SUB_STATUSES = frozenset({"OUTSTANDING_PAYMENT"})
BOOK_SUB_STATUSES = frozenset({"UNRECORDED_BANK_CHARGE", "NSF_RETURN"})
BOOK_ADD_STATUSES = frozenset({"UNRECORDED_BANK_CREDIT"})


async def _sum_items_by_status(run_id: str, statuses: frozenset[str]) -> float:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_items")
        .select("amount")
        .eq("run_id", run_id)
        .in_("match_status", list(statuses))
        .execute()
    )
    return sum(abs(float(r.get("amount") or 0)) for r in (res.data or []))


async def _sum_adjustments(run_id: str, affects_side: str) -> float:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_adjustments")
        .select("amount, adjustment_type")
        .eq("run_id", run_id)
        .eq("affects_side", affects_side)
        .execute()
    )
    total = 0.0
    for row in res.data or []:
        amt = abs(float(row.get("amount") or 0))
        adj_type = row.get("adjustment_type") or ""
        if adj_type in ("OUTSTANDING_PAYMENT", "UNRECORDED_BANK_CHARGE", "NSF_RETURN", "BOOK_ERROR"):
            total -= amt
        else:
            total += amt
    return total


async def recalculate_balance_proof(run_id: str, user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    run_res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .select("*")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    run = run_res.data
    if not run:
        raise ValueError("Reconciliation run not found")

    mono_closing = float(run.get("mono_closing_balance") or 0)
    qbo_balance = float(run.get("qbo_book_balance") or 0)

    deposits_in_transit = await _sum_items_by_status(run_id, BANK_ADD_STATUSES)
    outstanding_payments = await _sum_items_by_status(run_id, BANK_SUB_STATUSES)
    unrecorded_charges = await _sum_items_by_status(run_id, BOOK_SUB_STATUSES)
    unrecorded_credits = await _sum_items_by_status(run_id, BOOK_ADD_STATUSES)

    bank_adj = await _sum_adjustments(run_id, "BANK")
    book_adj = await _sum_adjustments(run_id, "BOOK")

    adjusted_bank = mono_closing + deposits_in_transit - outstanding_payments + bank_adj
    adjusted_book = qbo_balance - unrecorded_charges + unrecorded_credits + book_adj
    variance = round(adjusted_bank - adjusted_book, 2)

    proof = {
        "mono_closing_balance": mono_closing,
        "deposits_in_transit": deposits_in_transit,
        "outstanding_payments": outstanding_payments,
        "bank_adjustments": bank_adj,
        "adjusted_bank_balance": round(adjusted_bank, 2),
        "qbo_book_balance": qbo_balance,
        "unrecorded_bank_charges": unrecorded_charges,
        "unrecorded_bank_credits": unrecorded_credits,
        "book_adjustments": book_adj,
        "adjusted_book_balance": round(adjusted_book, 2),
        "variance": variance,
    }

    summary = run.get("summary") or {}
    if isinstance(summary, dict):
        summary["balance_proof"] = proof
    else:
        summary = {"balance_proof": proof}

    update = {
        "adjusted_bank_balance": proof["adjusted_bank_balance"],
        "adjusted_book_balance": proof["adjusted_book_balance"],
        "variance": variance,
        "summary": summary,
    }
    res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .update(update)
        .eq("id", run_id)
        .eq("user_id", user_id)
        .execute()
    )
    row = (res.data or [run])[0]
    row["balance_proof"] = proof
    return row


async def get_balance_proof(run_id: str, user_id: str) -> dict[str, Any]:
    run = await recalculate_balance_proof(run_id, user_id)
    return run.get("balance_proof") or (run.get("summary") or {}).get("balance_proof") or {}
