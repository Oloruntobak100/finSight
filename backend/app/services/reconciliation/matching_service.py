"""Four-pass transaction matching engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.books_service import _mapping_lookup, get_mappings
from app.services.qb_party_service import normalize_party_lookup
from app.services.reconciliation.audit_service import log_audit
from app.services.reconciliation.balance_proof_service import recalculate_balance_proof
from app.services.reconciliation.constants import AUTO_MATCH_THRESHOLD
from app.services.reconciliation.mono_bank_activity import load_mono_bank_activity, mono_closing_balance
from app.services.reconciliation.qbo_bank_activity import load_qbo_bank_activity, qbo_bank_account_balance
from app.services.reconciliation.scoring import classify_score, compute_match_score, is_nip_timing_difference


def _default_mono_classification(direction: str) -> str:
    if direction == "in":
        return "DEPOSITS_IN_TRANSIT"
    return "UNRECORDED_BANK_CHARGE"


def _default_qbo_classification(direction: str) -> str:
    if direction == "out":
        return "OUTSTANDING_PAYMENT"
    return "TIMING_DIFFERENCE"


async def _load_timing_patterns(user_id: str) -> set[str]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_timing_patterns")
        .select("payee_pattern")
        .eq("user_id", user_id)
        .execute()
    )
    return {r["payee_pattern"] for r in (res.data or []) if r.get("payee_pattern")}


async def _load_open_outstanding(
    user_id: str,
    mono_account_id: str,
    qb_bank_account_id: str,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("reconciliation_outstanding_items")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "OPEN")
        .eq("mono_account_id", mono_account_id)
        .eq("qb_bank_account_id", qb_bank_account_id)
        .execute()
    )
    return res.data or []


async def _resolve_qb_bank(user_id: str, mono_account_id: str, qb_bank_account_id: str | None) -> str:
    if qb_bank_account_id:
        return str(qb_bank_account_id)
    mappings = await get_mappings(user_id)
    bank_map = _mapping_lookup(mappings, "bank_account", mono_account_id)
    if bank_map and bank_map.get("qb_account_id"):
        return str(bank_map["qb_account_id"])
    raise ValueError("QuickBooks bank account is required. Map this bank under Books → Mappings.")


def _item_row(
    *,
    run_id: str,
    user_id: str,
    source: str,
    match_status: str,
    line: dict[str, Any],
    match_score: float = 0.0,
    carry_forward: bool = False,
    prior_run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "user_id": user_id,
        "source": source,
        "match_status": match_status,
        "mono_transaction_id": line.get("mono_transaction_id"),
        "qbo_entity_id": line.get("qbo_entity_id"),
        "qbo_entity_type": line.get("qbo_entity_type"),
        "match_score": match_score,
        "amount": line.get("amount") or 0,
        "currency": line.get("currency") or "NGN",
        "transaction_date": line.get("transaction_date"),
        "direction": line.get("direction"),
        "payee": line.get("payee"),
        "reference": line.get("reference"),
        "narration": line.get("narration"),
        "carry_forward": carry_forward,
        "prior_run_id": prior_run_id,
    }


async def _import_prior_outstanding(
    user_id: str,
    run_id: str,
    mono_account_id: str,
    qb_bank_account_id: str,
) -> None:
    """Attach open outstanding items from prior runs to this run's context."""
    outstanding = await _load_open_outstanding(user_id, mono_account_id, qb_bank_account_id)
    if not outstanding:
        return
    sb = get_supabase()
    for item in outstanding:
        await run_db(
            lambda i=item: sb.table("reconciliation_outstanding_items")
            .update({"updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", i["id"])
            .execute()
        )


async def run_matching_engine(
    user_id: str,
    *,
    mono_account_id: str,
    qb_bank_account_id: str | None,
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    resolved_qb = await _resolve_qb_bank(user_id, mono_account_id, qb_bank_account_id)
    timing_patterns = await _load_timing_patterns(user_id)
    open_outstanding = await _load_open_outstanding(user_id, mono_account_id, resolved_qb)

    mono_lines = await load_mono_bank_activity(
        user_id,
        mono_account_id=mono_account_id,
        period_start=period_start,
        period_end=period_end,
    )
    qbo_lines = await load_qbo_bank_activity(
        user_id,
        qb_bank_account_id=resolved_qb,
        period_start=period_start,
        period_end=period_end,
    )

    mono_balance, currency, balance_source = await mono_closing_balance(
        user_id, mono_account_id, period_end
    )
    qbo_balance = await qbo_bank_account_balance(user_id, resolved_qb)

    sb = get_supabase()
    run_row = {
        "user_id": user_id,
        "mono_account_id": mono_account_id,
        "qb_bank_account_id": resolved_qb,
        "period_start": period_start,
        "period_end": period_end,
        "mono_closing_balance": mono_balance,
        "qbo_book_balance": qbo_balance,
        "mono_balance_source": balance_source,
        "status": "DRAFT",
        "created_by": user_id,
        "snapshot_mono_data": mono_lines,
        "snapshot_qbo_data": qbo_lines,
        "summary": {},
    }
    run_res = await run_db(lambda: sb.table("reconciliation_runs").insert(run_row).execute())
    run = (run_res.data or [run_row])[0]
    run_id = run["id"]

    await _import_prior_outstanding(user_id, run_id, mono_account_id, resolved_qb)

    qbo_by_id = {line["qbo_entity_id"]: line for line in qbo_lines if line.get("qbo_entity_id")}
    used_mono: set[str] = set()
    used_qbo: set[str] = set()
    items_to_insert: list[dict[str, Any]] = []

    # Pass 1 — exact match by qb_entity_id
    for mono in mono_lines:
        entity_id = mono.get("qb_entity_id")
        if not entity_id or mono.get("qb_sync_status") != "posted":
            continue
        qbo = qbo_by_id.get(str(entity_id))
        if not qbo:
            continue
        used_mono.add(mono.get("mono_transaction_id") or "")
        used_qbo.add(qbo["qbo_entity_id"])
        merged = {**mono, **qbo, "source": "BOTH"}
        items_to_insert.append(
            _item_row(
                run_id=run_id,
                user_id=user_id,
                source="BOTH",
                match_status="MATCHED_EXACT",
                line=merged,
                match_score=1.0,
            )
        )

    # Pass 3 — prior outstanding (before fuzzy)
    for mono in mono_lines:
        mid = mono.get("mono_transaction_id") or ""
        if mid in used_mono:
            continue
        for outstanding in open_outstanding:
            if outstanding.get("status") != "OPEN":
                continue
            score = compute_match_score(
                amount_a=mono["amount"],
                amount_b=float(outstanding.get("amount") or 0),
                date_a=mono.get("transaction_date"),
                date_b=str(outstanding.get("original_date") or ""),
                payee_a=mono.get("payee"),
                payee_b=outstanding.get("description"),
            )
            if score >= AUTO_MATCH_THRESHOLD:
                used_mono.add(mid)
                items_to_insert.append(
                    _item_row(
                        run_id=run_id,
                        user_id=user_id,
                        source="MONO",
                        match_status="PRIOR_PERIOD_CARRY",
                        line=mono,
                        match_score=score,
                        carry_forward=False,
                        prior_run_id=outstanding.get("originating_run_id"),
                    )
                )
                await run_db(
                    lambda oid=outstanding["id"]: sb.table("reconciliation_outstanding_items")
                    .update(
                        {
                            "status": "CLEARED",
                            "resolved_run_id": run_id,
                            "cleared_date": mono.get("transaction_date"),
                            "mono_transaction_id": mid,
                        }
                    )
                    .eq("id", oid)
                    .execute()
                )
                break

    # Pass 2 — fuzzy match
    remaining_mono = [m for m in mono_lines if (m.get("mono_transaction_id") or "") not in used_mono]
    remaining_qbo = [q for q in qbo_lines if q.get("qbo_entity_id") not in used_qbo]

    for mono in remaining_mono:
        best_score = 0.0
        best_qbo: dict[str, Any] | None = None
        for qbo in remaining_qbo:
            if qbo.get("qbo_entity_id") in used_qbo:
                continue
            if mono.get("direction") != qbo.get("direction"):
                continue
            score = compute_match_score(
                amount_a=mono["amount"],
                amount_b=qbo["amount"],
                date_a=mono.get("transaction_date"),
                date_b=qbo.get("transaction_date"),
                payee_a=mono.get("payee"),
                payee_b=qbo.get("payee"),
                ref_a=mono.get("reference"),
                ref_b=qbo.get("reference"),
            )
            if score > best_score:
                best_score = score
                best_qbo = qbo

        if best_qbo and best_score >= AUTO_MATCH_THRESHOLD:
            used_mono.add(mono.get("mono_transaction_id") or "")
            used_qbo.add(best_qbo["qbo_entity_id"])
            merged = {**mono, **best_qbo, "source": "BOTH"}
            items_to_insert.append(
                _item_row(
                    run_id=run_id,
                    user_id=user_id,
                    source="BOTH",
                    match_status="MATCHED_FUZZY",
                    line=merged,
                    match_score=best_score,
                )
            )
        elif best_qbo and best_score >= 0.65:
            used_mono.add(mono.get("mono_transaction_id") or "")
            used_qbo.add(best_qbo["qbo_entity_id"])
            merged = {**mono, **best_qbo, "source": "BOTH"}
            items_to_insert.append(
                _item_row(
                    run_id=run_id,
                    user_id=user_id,
                    source="BOTH",
                    match_status="SUGGESTED",
                    line=merged,
                    match_score=best_score,
                )
            )

    # Pass 4 — classify remainder
    for mono in mono_lines:
        mid = mono.get("mono_transaction_id") or ""
        if mid in used_mono:
            continue
        payee_key = normalize_party_lookup(mono.get("payee"))
        status = _default_mono_classification(mono.get("direction") or "out")
        if payee_key in timing_patterns:
            status = "TIMING_DIFFERENCE"
        items_to_insert.append(
            _item_row(
                run_id=run_id,
                user_id=user_id,
                source="MONO",
                match_status=status,
                line=mono,
            )
        )
        if status in ("DEPOSITS_IN_TRANSIT", "OUTSTANDING_PAYMENT"):
            outstanding_type = (
                "DEPOSIT_IN_TRANSIT" if status == "DEPOSITS_IN_TRANSIT" else "OUTSTANDING_PAYMENT"
            )
            await run_db(
                lambda m=mono, ot=outstanding_type: sb.table("reconciliation_outstanding_items")
                .insert(
                    {
                        "user_id": user_id,
                        "mono_account_id": mono_account_id,
                        "qb_bank_account_id": resolved_qb,
                        "originating_run_id": run_id,
                        "item_type": ot,
                        "amount": m["amount"],
                        "currency": m.get("currency") or "NGN",
                        "description": m.get("payee") or m.get("narration"),
                        "original_date": m.get("transaction_date"),
                        "status": "OPEN",
                        "mono_transaction_id": m.get("mono_transaction_id"),
                    }
                )
                .execute()
            )

    for qbo in qbo_lines:
        qid = qbo.get("qbo_entity_id") or ""
        if qid in used_qbo:
            continue
        status = _default_qbo_classification(qbo.get("direction") or "in")
        for mono in mono_lines:
            if is_nip_timing_difference(qbo.get("transaction_date"), mono.get("transaction_date")):
                if abs(mono["amount"] - qbo["amount"]) / max(mono["amount"], qbo["amount"], 1) <= 0.01:
                    status = "TIMING_DIFFERENCE"
                    break
        items_to_insert.append(
            _item_row(
                run_id=run_id,
                user_id=user_id,
                source="QBO",
                match_status=status,
                line=qbo,
            )
        )

    if items_to_insert:
        await run_db(lambda: sb.table("reconciliation_items").insert(items_to_insert).execute())

    counts: dict[str, int] = {}
    for item in items_to_insert:
        st = item["match_status"]
        counts[st] = counts.get(st, 0) + 1

    summary = {
        "counts": counts,
        "mono_line_count": len(mono_lines),
        "qbo_line_count": len(qbo_lines),
        "currency": currency,
        "mono_balance_source": balance_source,
    }

    await run_db(
        lambda: sb.table("reconciliation_runs")
        .update({"summary": summary})
        .eq("id", run_id)
        .execute()
    )

    await log_audit(
        run_id=run_id,
        user_id=user_id,
        actor_id=user_id,
        action="matching_engine_completed",
        after_state={"counts": counts},
    )

    run = await recalculate_balance_proof(run_id, user_id)
    run["items_count"] = len(items_to_insert)
    return run


async def update_item(
    user_id: str,
    run_id: str,
    item_id: str,
    *,
    match_status: str | None = None,
    confirm_suggested: bool = False,
    reject_suggested: bool = False,
) -> dict[str, Any]:
    sb = get_supabase()
    item_res = await run_db(
        lambda: sb.table("reconciliation_items")
        .select("*")
        .eq("id", item_id)
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    item = item_res.data
    if not item:
        raise ValueError("Item not found")

    run = await run_db(
        lambda: sb.table("reconciliation_runs")
        .select("status")
        .eq("id", run_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if (run.data or {}).get("status") == "LOCKED":
        raise ValueError("This reconciliation is locked and cannot be modified")

    update: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if confirm_suggested and item.get("match_status") == "SUGGESTED":
        update["match_status"] = "MATCHED_FUZZY"
        update["manually_matched_by"] = user_id
        update["manually_matched_at"] = datetime.now(timezone.utc).isoformat()
    elif reject_suggested and item.get("match_status") == "SUGGESTED":
        update["match_status"] = "UNEXPLAINED"
        update["source"] = "MONO" if item.get("mono_transaction_id") else "QBO"
    elif match_status:
        update["match_status"] = match_status

    res = await run_db(
        lambda: sb.table("reconciliation_items")
        .update(update)
        .eq("id", item_id)
        .execute()
    )

    if match_status == "TIMING_DIFFERENCE":
        payee_key = normalize_party_lookup(item.get("payee"))
        if payee_key:
            await run_db(
                lambda: sb.table("reconciliation_timing_patterns")
                .upsert(
                    {
                        "user_id": user_id,
                        "payee_pattern": payee_key,
                        "auto_match_status": "TIMING_DIFFERENCE",
                        "hit_count": 1,
                    },
                    on_conflict="user_id,payee_pattern",
                )
                .execute()
            )

    await log_audit(
        run_id=run_id,
        user_id=user_id,
        actor_id=user_id,
        action="item_updated",
        before_state={"match_status": item.get("match_status")},
        after_state=update,
    )

    await recalculate_balance_proof(run_id, user_id)
    return (res.data or [item])[0]


async def list_items(
    run_id: str,
    user_id: str,
    *,
    match_status: str | None = None,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("reconciliation_items")
        .select("*")
        .eq("run_id", run_id)
        .eq("user_id", user_id)
        .order("transaction_date")
    )
    if match_status:
        query = query.eq("match_status", match_status)
    res = await run_db(lambda: query.execute())
    return res.data or []
