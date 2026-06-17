from calendar import monthrange
from datetime import date
from typing import Any

from app.database import get_supabase, run_db


async def calculate_metrics(user_id: str) -> dict[str, Any]:
    today = date.today()
    period_start = date(today.year, today.month, 1)
    _, last_day = monthrange(today.year, today.month)
    period_end = date(today.year, today.month, last_day)

    sb = get_supabase()
    txns_res = await run_db(
        lambda: sb.table("transactions")
        .select("amount, transaction_type")
        .eq("user_id", user_id)
        .gte("transaction_date", period_start.isoformat())
        .lte("transaction_date", period_end.isoformat())
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
    savings_rate = (net_cash_flow / total_income * 100) if total_income > 0 else None
    burn_rate = total_expenses / last_day if total_expenses > 0 else None

    row = {
        "user_id": user_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_cash_flow": net_cash_flow,
        "savings_rate": savings_rate,
        "burn_rate": burn_rate,
    }
    result = await run_db(lambda: sb.table("financial_metrics").insert(row).execute())
    return result.data[0]


async def get_latest_metrics(user_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("financial_metrics")
        .select("*")
        .eq("user_id", user_id)
        .order("calculated_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def get_subscriptions(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("merchant_name, amount, currency")
        .eq("user_id", user_id)
        .eq("is_recurring", True)
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
