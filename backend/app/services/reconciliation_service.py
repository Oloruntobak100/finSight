"""Bank vs QuickBooks reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.quickbooks_service import qb_query

BANK_PROVIDERS = ("plaid", "mono")
DATE_TOLERANCE_DAYS = 3
AMOUNT_TOLERANCE_PCT = 0.01


def _parse_qb_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _amounts_match(a: float, b: float) -> bool:
    a, b = abs(a), abs(b)
    if a == 0 and b == 0:
        return True
    if max(a, b) == 0:
        return False
    return abs(a - b) / max(a, b) <= AMOUNT_TOLERANCE_PCT


def _dates_match(bank_date: str, qb_date: str | None) -> bool:
    bd = _parse_qb_date(bank_date)
    qd = _parse_qb_date(qb_date)
    if not bd or not qd:
        return False
    return abs((bd - qd).days) <= DATE_TOLERANCE_DAYS


async def reconcile(
    user_id: str,
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    sb = get_supabase()
    bank_res = await run_db(
        lambda: sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .gte("transaction_date", period_start)
        .lte("transaction_date", period_end)
        .execute()
    )
    bank_txns = bank_res.data or []

    qb_purchases: list[dict[str, Any]] = []
    try:
        sql = (
            f"SELECT * FROM Purchase WHERE TxnDate >= '{period_start}' "
            f"AND TxnDate <= '{period_end}' MAXRESULTS 500"
        )
        qb_data = await qb_query(user_id, sql)
        qb_purchases = qb_data.get("QueryResponse", {}).get("Purchase", []) or []
        if isinstance(qb_purchases, dict):
            qb_purchases = [qb_purchases]
    except Exception:
        qb_purchases = []

    matched: list[dict[str, Any]] = []
    unmatched_bank: list[dict[str, Any]] = []
    unmatched_qb: list[dict[str, Any]] = list(qb_purchases)
    used_qb: set[int] = set()

    for bank in bank_txns:
        if bank.get("transaction_type") != "debit":
            continue
        bank_amount = abs(float(bank.get("amount") or 0))
        found = False
        for idx, purchase in enumerate(qb_purchases):
            if idx in used_qb:
                continue
            qb_amount = abs(float(purchase.get("TotalAmt") or 0))
            if _amounts_match(bank_amount, qb_amount) and _dates_match(
                str(bank.get("transaction_date")), purchase.get("TxnDate")
            ):
                matched.append(
                    {
                        "bank": bank,
                        "qb": purchase,
                    }
                )
                used_qb.add(idx)
                found = True
                break
        if not found:
            unmatched_bank.append(bank)

    unmatched_qb = [p for i, p in enumerate(qb_purchases) if i not in used_qb]

    matched_amount = sum(abs(float(m["bank"].get("amount") or 0)) for m in matched)
    variance = sum(abs(float(b.get("amount") or 0)) for b in unmatched_bank)

    summary = {
        "matched_count": len(matched),
        "unmatched_bank_count": len(unmatched_bank),
        "unmatched_qb_count": len(unmatched_qb),
        "bank_count": len([b for b in bank_txns if b.get("transaction_type") == "debit"]),
        "matched_amount": matched_amount,
        "variance": variance,
        "match_rate": round(len(matched) / max(1, len(matched) + len(unmatched_bank)), 4),
    }

    run_row = {
        "user_id": user_id,
        "period_start": period_start,
        "period_end": period_end,
        "summary": summary,
        "matched": matched,
        "unmatched_bank": unmatched_bank,
        "unmatched_qb": unmatched_qb,
    }
    res = await run_db(lambda: sb.table("reconciliation_runs").insert(run_row).execute())
    saved = (res.data or [run_row])[0]

    if not qb_purchases and bank_txns:
        summary["message"] = (
            "No QuickBooks transactions found for this period. "
            "Make sure your books are synced."
        )

    return {
        "id": saved.get("id"),
        "summary": summary,
        "matched": matched,
        "unmatched_bank": unmatched_bank,
        "unmatched_qb": unmatched_qb,
    }
