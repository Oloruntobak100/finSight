import json

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.database import get_supabase, run_db
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
from app.services.books_service import get_learning_progress
from app.services.chat_service import _resolve_llm_provider, build_financial_context
from app.services.forecasting_service import generate_forecast, get_latest_forecasts
from app.services.transaction_analytics import get_analytics_meta
from app.services.transfer_utils import mark_transfers_df

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


@router.get("/learning-progress")
async def analytics_learning_progress(user_id: CurrentUser) -> dict:
    items = await get_learning_progress(user_id)
    return {"items": items}


@router.get("/books-insights")
async def books_insights_metrics(user_id: CurrentUser) -> dict:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("amount, transaction_type, category, merchant_name, payee_pattern, description")
        .eq("user_id", user_id)
        .execute()
    )
    rows = res.data or []
    debits = [r for r in rows if r.get("transaction_type") == "debit"]
    df = pd.DataFrame(debits) if debits else pd.DataFrame()
    transfer_volume = 0.0
    expense_volume = 0.0
    if not df.empty:
        marked = mark_transfers_df(df)
        transfer_volume = float(marked[marked["is_transfer"]]["amount"].sum())
        expense_volume = float(marked[~marked["is_transfer"]]["amount"].sum())
    total_debits = transfer_volume + expense_volume
    transfer_ratio = round(transfer_volume / total_debits, 4) if total_debits else 0.0

    payee_totals: dict[str, float] = {}
    for r in debits:
        key = r.get("payee_pattern") or r.get("merchant_name") or "unknown"
        payee_totals[key] = payee_totals.get(key, 0.0) + abs(float(r.get("amount") or 0))
    top_payees = sorted(payee_totals.items(), key=lambda x: -x[1])[:5]

    analysis = await get_financial_analysis(user_id, parse_analysis_filters(), refresh_balances=True)
    balances = analysis.get("balances", {})
    total_balance = float(balances.get("total_balance") or 0)
    monthly_burn = float(analysis.get("metrics", {}).get("total_expenses") or 0)
    runway = round(total_balance / monthly_burn, 1) if monthly_burn > 0 else None

    return {
        "transfer_vs_expense_ratio": transfer_ratio,
        "transfer_volume": transfer_volume,
        "expense_volume": expense_volume,
        "top_payees": [{"payee": k, "amount": v} for k, v in top_payees],
        "estimated_monthly_burn": monthly_burn,
        "cash_runway_months": runway,
        "total_balance": total_balance,
    }


@router.post("/books-insights/commentary")
async def books_insights_commentary(user_id: CurrentUser) -> StreamingResponse:
    provider_llm = _resolve_llm_provider()
    if provider_llm == "none":
        raise HTTPException(status_code=503, detail="LLM not configured")

    metrics = await books_insights_metrics(user_id)
    context = await build_financial_context(user_id)
    prompt = (
        "You are a financial advisor for a Nigerian SME. Be concise. "
        "Give 3-5 specific insights about financial health based on the data. "
        "Flag if transfer ratio is high (books may be incomplete). "
        "Use only provided data.\n\n"
        f"Books metrics: {json.dumps(metrics, default=str)}\n"
        f"Context: {json.dumps(context, default=str)[:12000]}"
    )

    async def stream():
        if provider_llm == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=1200,
                stream=True,
                messages=[
                    {"role": "system", "content": "You are FinSight AI CFO."},
                    {"role": "user", "content": prompt},
                ],
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
        else:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    yield text

    return StreamingResponse(stream(), media_type="text/plain")
