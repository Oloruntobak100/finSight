from fastapi import APIRouter, Query

from app.auth.dependencies import CurrentUser
from app.models.analysis_filters import parse_analysis_filters
from app.models.metrics import (
    BalancesResponse,
    FinancialAnalysisResponse,
    FinancialMetricsResponse,
    ForecastResponse,
    SubscriptionsListResponse,
    SubscriptionResponse,
)
from app.services.analysis_service import get_financial_analysis
from app.services.analytics_service import calculate_metrics, get_latest_metrics, get_subscriptions
from app.services.balance_service import get_user_balances
from app.services.forecasting_service import generate_forecast, get_latest_forecasts
from app.services.transaction_analytics import get_analytics_meta

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _filters_from_query(
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
    compare_account_a: str | None = None,
    compare_account_b: str | None = None,
    compare_period: str = "previous_month",
):
    return parse_analysis_filters(
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        account_id=account_id,
        include_transfers=include_transfers,
        compare_account_a=compare_account_a,
        compare_account_b=compare_account_b,
        compare_period=compare_period,
    )


@router.get("/meta")
async def analytics_meta(user_id: CurrentUser) -> dict:
    return await get_analytics_meta(user_id)


@router.get("/metrics", response_model=FinancialMetricsResponse)
async def get_metrics(user_id: CurrentUser) -> FinancialMetricsResponse:
    metrics = await get_latest_metrics(user_id)
    if not metrics:
        metrics = await calculate_metrics(user_id)
    return FinancialMetricsResponse(**metrics)


@router.post("/metrics/recalculate", response_model=FinancialMetricsResponse)
async def recalculate_metrics(user_id: CurrentUser) -> FinancialMetricsResponse:
    metrics = await calculate_metrics(user_id)
    return FinancialMetricsResponse(**metrics)


@router.get("/forecast", response_model=list[ForecastResponse])
async def get_forecast(
    user_id: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
    compare_account_a: str | None = None,
    compare_account_b: str | None = None,
    compare_period: str = "previous_month",
) -> list[ForecastResponse]:
    filters = _filters_from_query(
        date_from, date_to, provider, account_id, include_transfers,
        compare_account_a, compare_account_b, compare_period,
    )
    has_filters = bool(filters.providers or filters.account_ids or filters.date_from or filters.date_to)
    if has_filters:
        forecasts = await generate_forecast(user_id, filters, persist=False)
    else:
        forecasts = await get_latest_forecasts(user_id)
        if not forecasts:
            forecasts = await generate_forecast(user_id, filters, persist=True)
    return [ForecastResponse(**f) for f in forecasts]


@router.post("/forecast/generate", response_model=list[ForecastResponse])
async def generate_forecast_endpoint(
    user_id: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
) -> list[ForecastResponse]:
    filters = parse_analysis_filters(
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        account_id=account_id,
        include_transfers=include_transfers,
    )
    forecasts = await generate_forecast(user_id, filters, persist=not (filters.providers or filters.account_ids))
    return [ForecastResponse(**f) for f in forecasts]


@router.get("/subscriptions", response_model=SubscriptionsListResponse)
async def get_subscription_list(user_id: CurrentUser) -> SubscriptionsListResponse:
    data = await get_subscriptions(user_id)
    return SubscriptionsListResponse(
        items=[SubscriptionResponse(**i) for i in data["items"]],
        total_monthly=data["total_monthly"],
        total_annual=data["total_annual"],
    )


@router.get("/balances", response_model=BalancesResponse)
async def get_balances(
    user_id: CurrentUser,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
) -> BalancesResponse:
    filters = parse_analysis_filters(provider=provider, account_id=account_id)
    data = await get_user_balances(user_id, filters)
    return BalancesResponse(**data)


@router.get("/analysis", response_model=FinancialAnalysisResponse)
async def get_analysis(
    user_id: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
    compare_account_a: str | None = None,
    compare_account_b: str | None = None,
    compare_period: str = "previous_month",
) -> FinancialAnalysisResponse:
    filters = _filters_from_query(
        date_from, date_to, provider, account_id, include_transfers,
        compare_account_a, compare_account_b, compare_period,
    )
    data = await get_financial_analysis(user_id, filters, refresh_balances=True)
    return FinancialAnalysisResponse(**data)
