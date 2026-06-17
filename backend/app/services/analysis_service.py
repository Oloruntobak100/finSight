from typing import Any

from app.models.analysis_filters import AnalysisFilters
from app.services.balance_service import get_user_balances
from app.services.transaction_analytics import build_analysis


async def get_financial_analysis(
    user_id: str,
    filters: AnalysisFilters | None = None,
    *,
    refresh_balances: bool = True,
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
    return await build_analysis(user_id, filters, balances)
