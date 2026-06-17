from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.database import get_supabase, run_db
from app.models.analysis_filters import AnalysisFilters
from app.services.balance_service import get_user_balances
from app.services.transaction_analytics import fetch_transactions_df, _primary_currency, _filter_currency
from app.services.transfer_utils import split_spend_income


def _forecast_series(daily: pd.Series) -> tuple[float, float, float]:
    """Return (point, low, high) for next day extrapolated over horizon scaling."""
    if daily.empty or len(daily) < 7:
        mean = float(daily.mean()) if not daily.empty else 0.0
        return mean, mean * 0.85, mean * 1.15

    try:
        model = ExponentialSmoothing(daily.values, trend="add", seasonal=None)
        fit = model.fit(optimized=True)
        forecast = float(fit.forecast(1)[0])
        resid_std = float(np.std(fit.resid)) if len(fit.resid) else abs(forecast) * 0.1
        return forecast, forecast - 1.28 * resid_std, forecast + 1.28 * resid_std
    except Exception:
        mean = float(daily.tail(30).mean())
        return mean, mean * 0.85, mean * 1.15


async def generate_forecast(
    user_id: str,
    filters: AnalysisFilters | None = None,
    *,
    persist: bool = True,
) -> list[dict[str, Any]]:
    filters = filters or AnalysisFilters()
    df = await fetch_transactions_df(user_id, filters)
    if df.empty:
        return []

    currency = _primary_currency(df)
    cdf = _filter_currency(df, currency)
    _, debits, credits = split_spend_income(cdf, filters.include_transfers)

    inc_daily = credits.groupby("transaction_date")["amount"].sum().sort_index()
    exp_daily = debits.groupby("transaction_date")["amount"].sum().sort_index()

    # fill date range
    idx = pd.date_range(cdf["transaction_date"].min(), cdf["transaction_date"].max(), freq="D")
    inc_daily = inc_daily.reindex(idx, fill_value=0)
    exp_daily = exp_daily.reindex(idx, fill_value=0)

    inc_pt, inc_lo, inc_hi = _forecast_series(inc_daily)
    exp_pt, exp_lo, exp_hi = _forecast_series(exp_daily)
    net_pt = inc_pt - exp_pt
    net_lo = inc_lo - exp_hi
    net_hi = inc_hi - exp_lo

    balances = await get_user_balances(user_id, filters)
    current_balance = balances.get("totals_by_currency", {}).get(currency, balances.get("total_balance", 0))

    sb = get_supabase()
    results = []
    for horizon in (30, 60, 90):
        row = {
            "user_id": user_id,
            "forecast_date": date.today().isoformat(),
            "horizon_days": horizon,
            "predicted_income": round(inc_pt * horizon, 2),
            "predicted_expenses": round(exp_pt * horizon, 2),
            "projected_balance": round(float(current_balance) + net_pt * horizon, 2),
            "confidence_score": 0.8,
            "confidence_low": round(float(current_balance) + net_lo * horizon, 2),
            "confidence_high": round(float(current_balance) + net_hi * horizon, 2),
            "currency": currency,
            "model_version": "holt_winters_v2",
        }
        if persist and not filters.account_ids and not filters.providers:
            ins = await run_db(lambda r=row: sb.table("forecasts").insert(r).execute())
            stored = ins.data[0]
            results.append({**stored, **{k: row[k] for k in ("confidence_low", "confidence_high", "currency") if k not in stored}})
        else:
            results.append(row)

    return results


async def get_latest_forecasts(user_id: str) -> list[dict[str, Any]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("forecasts")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(3)
        .execute()
    )
    rows = res.data or []
    for row in rows:
        row.setdefault("currency", "USD")
        row.setdefault("confidence_low", row.get("projected_balance", 0) * 0.9)
        row.setdefault("confidence_high", row.get("projected_balance", 0) * 1.1)
    return rows
