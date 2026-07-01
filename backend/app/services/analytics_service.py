from calendar import monthrange
from datetime import date
from typing import Any

from app.database import get_supabase, run_db
from app.services.qb_analytics_service import get_books_coverage, get_qb_period_kpis, is_qb_connected


async def _calculate_bank_cash_metrics(user_id: str, period_start: date, period_end: date) -> dict[str, Any]:
    sb = get_supabase()
    txns_res = await run_db(
        lambda: sb.table("transactions")
        .select("amount, transaction_type")
        .eq("user_id", user_id)
        .gte("transaction_date", period_start.isoformat())
        .lte("transaction_date", period_end.isoformat())
        .is_("archived_at", "null")
        .execute()
    )

    total_income = 0.0
    total_expenses = 0.0
    for txn in txns_res.data or []:
        amount = float(txn["amount"])
        if txn["transaction_type"] == "credit":
            total_income += amount
        else:
            total_expenses += amount

    net_cash_flow = total_income - total_expenses
    _, last_day = monthrange(period_start.year, period_start.month)
    savings_rate = (net_cash_flow / total_income * 100) if total_income > 0 else None
    burn_rate = total_expenses / last_day if total_expenses > 0 else None

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_cash_flow": net_cash_flow,
        "savings_rate": savings_rate,
        "burn_rate": burn_rate,
        "data_source": "bank",
    }


async def calculate_metrics(user_id: str) -> dict[str, Any]:
    today = date.today()
    period_start = date(today.year, today.month, 1)
    _, last_day = monthrange(today.year, today.month)
    period_end = date(today.year, today.month, last_day)

    coverage = await get_books_coverage(user_id, period_start, period_end)
    bank_cash = await _calculate_bank_cash_metrics(user_id, period_start, period_end)

    metrics: dict[str, Any]
    data_source = "bank"
    qb_unavailable_reason = None

    if await is_qb_connected(user_id):
        try:
            kpis = await get_qb_period_kpis(user_id, period_start, period_end)
            metrics = {
                "total_income": kpis["total_income"],
                "total_expenses": kpis["total_expenses"],
                "net_cash_flow": kpis["net_income"],
                "savings_rate": kpis.get("savings_rate"),
                "burn_rate": bank_cash.get("burn_rate"),
                "data_source": "quickbooks",
            }
            data_source = "quickbooks"
        except Exception as exc:
            metrics = bank_cash
            qb_unavailable_reason = str(exc)
    else:
        metrics = bank_cash
        qb_unavailable_reason = "QuickBooks not connected"

    row = {
        "user_id": user_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        **metrics,
    }
    sb = get_supabase()
    result = await run_db(lambda: sb.table("financial_metrics").insert(row).execute())
    stored = result.data[0]
    stored["data_source"] = data_source
    stored["books_coverage_pct"] = coverage.get("coverage_pct")
    stored["books_posted_count"] = coverage.get("posted_count")
    stored["books_total_count"] = coverage.get("total_count")
    stored["cash_in"] = bank_cash["total_income"]
    stored["cash_out"] = bank_cash["total_expenses"]
    stored["qb_unavailable_reason"] = qb_unavailable_reason
    return stored


async def get_latest_metrics(user_id: str) -> dict[str, Any] | None:
    today = date.today()
    period_start = date(today.year, today.month, 1)
    _, last_day = monthrange(today.year, today.month)
    period_end = date(today.year, today.month, last_day)

    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("financial_metrics")
        .select("*")
        .eq("user_id", user_id)
        .eq("period_start", period_start.isoformat())
        .eq("period_end", period_end.isoformat())
        .order("calculated_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        row = res.data[0]
        coverage = await get_books_coverage(user_id, period_start, period_end)
        row["books_coverage_pct"] = coverage.get("coverage_pct")
        row["books_posted_count"] = coverage.get("posted_count")
        row["books_total_count"] = coverage.get("total_count")
        row.setdefault("data_source", "quickbooks" if await is_qb_connected(user_id) else "bank")
        return row

    return await calculate_metrics(user_id)


async def get_subscriptions(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("merchant_name, amount, currency")
        .eq("user_id", user_id)
        .eq("is_recurring", True)
        .is_("archived_at", "null")
        .execute()
    )

    grouped: dict[str, dict[str, Any]] = {}
    for txn in res.data or []:
        merchant = txn.get("merchant_name") or "Unknown"
        if merchant not in grouped:
            grouped[merchant] = {
                "merchant_name": merchant,
                "amount": float(txn["amount"]),
                "currency": txn.get("currency", "USD"),
                "frequency": "monthly",
                "transaction_count": 1,
            }
        else:
            grouped[merchant]["transaction_count"] += 1
            grouped[merchant]["amount"] = max(grouped[merchant]["amount"], float(txn["amount"]))

    items = []
    total_monthly = 0.0
    for item in grouped.values():
        item["annual_cost"] = item["amount"] * 12
        total_monthly += item["amount"]
        items.append(item)

    return {
        "items": items,
        "total_monthly": total_monthly,
        "total_annual": total_monthly * 12,
    }
