from calendar import monthrange
from datetime import date
from typing import Any

import pandas as pd

from app.database import get_supabase, run_db
from app.models.analysis_filters import AnalysisFilters
from app.services.analysis_service import get_financial_analysis
from app.services.analytics_service import get_subscriptions
from app.services.forecasting_service import generate_forecast, get_latest_forecasts


async def get_comprehensive_report(
    user_id: str,
    filters: AnalysisFilters | None = None,
) -> dict[str, Any]:
    filters = filters or AnalysisFilters()
    today = date.today()
    period_start, period_end = filters.resolved_date_range()

    analysis = await get_financial_analysis(user_id, filters, refresh_balances=True)
    subscriptions = await get_subscriptions(user_id)
    has_filters = bool(filters.providers or filters.account_ids or filters.date_from)
    if has_filters:
        forecasts = await generate_forecast(user_id, filters, persist=False)
    else:
        forecasts = await get_latest_forecasts(user_id) or await generate_forecast(user_id, filters)

    currency = analysis.get("primary_currency", "USD")
    sym = "₦" if currency == "NGN" else "$"

    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("*")
        .eq("user_id", user_id)
        .gte("transaction_date", period_start.isoformat())
        .lte("transaction_date", period_end.isoformat())
    )
    if filters.providers:
        query = query.in_("source_provider", filters.providers)
    if filters.account_ids:
        query = query.in_("account_id", filters.account_ids)

    month_txns_res = await run_db(
        lambda: query.order("transaction_date", desc=True).order("created_at", desc=True).execute()
    )
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name")
        .eq("user_id", user_id)
        .execute()
    )
    bank_map = {a["id"]: a.get("account_name") or "Unknown" for a in (accounts_res.data or [])}

    month_transactions = []
    for txn in month_txns_res.data or []:
        month_transactions.append({
            "id": txn["id"],
            "date": txn["transaction_date"],
            "bank": bank_map.get(txn.get("account_id"), "—"),
            "merchant": txn.get("merchant_name") or txn.get("description") or "—",
            "category": txn.get("category") or "Uncategorized",
            "type": txn["transaction_type"],
            "amount": float(txn["amount"]),
            "currency": txn.get("currency") or currency,
            "is_recurring": bool(txn.get("is_recurring")),
        })

    largest = sorted(
        [t for t in month_transactions if t["type"] == "debit"],
        key=lambda x: x["amount"],
        reverse=True,
    )[:15]

    income_txns = [t for t in month_transactions if t["type"] == "credit"]
    total_income = sum(t["amount"] for t in income_txns)
    total_expenses = sum(t["amount"] for t in month_transactions if t["type"] == "debit")

    recurring_monthly = subscriptions.get("total_monthly", 0)
    savings_rate = analysis["metrics"].get("savings_rate")
    pc = analysis.get("period_comparison", {})

    executive_bullets = [
        f"Total balance ({currency}): {sym}{analysis['balances']['total_balance']:,.2f}",
        f"Period income: {sym}{total_income:,.2f}, expenses: {sym}{total_expenses:,.2f}",
        f"Net cash flow: {sym}{analysis['metrics']['net_cash_flow']:,.2f}",
        f"Transactions in period: {len(month_transactions)}",
        f"Recurring subscriptions: {sym}{recurring_monthly:,.2f}/month ({len(subscriptions.get('items', []))} detected)",
    ]
    if savings_rate is not None:
        executive_bullets.append(f"Savings rate: {savings_rate:.1f}%")
    if pc.get("expense_change_pct") is not None:
        executive_bullets.append(
            f"Expenses vs comparison period: {pc['expense_change_pct']:+.1f}%"
        )
    for insight in (analysis.get("insights") or [])[:3]:
        executive_bullets.append(f"{insight['title']}: {insight['body']}")

    weekly_rows = _weekly_breakdown(month_transactions)

    return {
        "generated_at": today.isoformat(),
        "filters_applied": filters.to_dict(),
        "primary_currency": currency,
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "label": f"{period_start.strftime('%b %d')} – {period_end.strftime('%b %d, %Y')}",
        },
        "executive_summary": {
            "bullets": executive_bullets,
            "total_balance": analysis["balances"]["total_balance"],
            "monthly_income": total_income,
            "monthly_expenses": total_expenses,
            "net_cash_flow": analysis["metrics"]["net_cash_flow"],
            "savings_rate": savings_rate,
            "transaction_count": len(month_transactions),
        },
        "balances": analysis["balances"],
        "monthly_trend": analysis["monthly_trend"],
        "yearly_trend": analysis.get("yearly_trend", []),
        "category_spending": analysis["category_spending"],
        "bank_summary": analysis["bank_summary"],
        "top_merchants": analysis["top_merchants"],
        "period_comparison": analysis["period_comparison"],
        "spending_habits": analysis.get("spending_habits", {}),
        "income_insights": analysis.get("income_insights", {}),
        "cash_runway": analysis.get("cash_runway", []),
        "counterparty_flows": analysis.get("counterparty_flows", []),
        "transfer_activity": analysis.get("transfer_activity", {}),
        "anomalies": analysis.get("anomalies", []),
        "recurring_detected": analysis.get("recurring_detected", []),
        "account_comparison": analysis.get("account_comparison"),
        "insights": analysis.get("insights", []),
        "month_transactions": month_transactions,
        "largest_expenses": largest,
        "income_transactions": sorted(income_txns, key=lambda x: x["amount"], reverse=True),
        "weekly_breakdown": weekly_rows,
        "subscriptions": subscriptions,
        "forecasts": forecasts[:3] if forecasts else [],
    }


def _weekly_breakdown(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not transactions:
        return []
    df = pd.DataFrame(transactions)
    df["date"] = pd.to_datetime(df["date"])
    df["week"] = df["date"].dt.to_period("W").astype(str)
    rows = []
    for week, group in df.groupby("week"):
        inc = float(group[group["type"] == "credit"]["amount"].sum())
        exp = float(group[group["type"] == "debit"]["amount"].sum())
        rows.append({
            "week": week,
            "income": round(inc, 2),
            "expenses": round(exp, 2),
            "net": round(inc - exp, 2),
            "transaction_count": int(len(group)),
        })
    return sorted(rows, key=lambda x: x["week"])
