from typing import Any

from app.models.analysis_filters import AnalysisFilters
from app.services.balance_service import get_user_balances
from app.services.qb_analytics_service import build_qb_financial_overlay, is_qb_connected
from app.services.transaction_analytics import build_analysis


def _bank_activity_payload(bank_analysis: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": bank_analysis.get("metrics", {}),
        "top_merchants": bank_analysis.get("top_merchants", []),
        "bank_summary": bank_analysis.get("bank_summary", []),
        "transfer_activity": bank_analysis.get("transfer_activity", {}),
        "counterparty_flows": bank_analysis.get("counterparty_flows", []),
        "anomalies": bank_analysis.get("anomalies", []),
        "recurring_detected": bank_analysis.get("recurring_detected", []),
        "spending_habits": bank_analysis.get("spending_habits", {}),
        "income_insights": bank_analysis.get("income_insights", {}),
        "daily_cashflow": bank_analysis.get("daily_cashflow", []),
        "transaction_count": bank_analysis.get("transaction_count", 0),
    }


async def get_financial_analysis(
    user_id: str,
    filters: AnalysisFilters | None = None,
    *,
    refresh_balances: bool = True,
    refresh_qb: bool = False,
) -> dict[str, Any]:
    filters = filters or AnalysisFilters()
    balances = await get_user_balances(user_id, filters) if refresh_balances else {
        "total_balance": 0,
        "totals_by_currency": {},
        "primary_currency": "USD",
        "accounts": [],
        "as_of": "",
        "errors": [],
    }
    bank_analysis = await build_analysis(user_id, filters, balances)
    merged: dict[str, Any] = {**bank_analysis, "bank_activity": _bank_activity_payload(bank_analysis)}

    if not await is_qb_connected(user_id):
        merged["data_source"] = "bank"
        merged["qb_unavailable_reason"] = "QuickBooks not connected"
        return merged

    try:
        qb_overlay = await build_qb_financial_overlay(user_id, filters, refresh=refresh_qb)
        merged.update(
            {
                "metrics": qb_overlay["metrics"],
                "monthly_trend": qb_overlay["monthly_trend"],
                "yearly_trend": qb_overlay.get("yearly_trend", []),
                "category_spending": qb_overlay["category_spending"],
                "period_comparison": qb_overlay["period_comparison"],
                "books_coverage": qb_overlay["books_coverage"],
                "qb_reports": qb_overlay.get("qb_reports", {}),
                "data_source": "quickbooks",
                "qb_unavailable_reason": None,
            }
        )
        qb_insights = qb_overlay.get("insights") or []
        bank_insights = bank_analysis.get("insights") or []
        merged["insights"] = qb_insights + bank_insights
    except Exception as exc:
        merged["data_source"] = "bank"
        merged["qb_unavailable_reason"] = str(exc)

    return merged
