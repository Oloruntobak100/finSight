"""Shared transaction analytics for Analysis, Forecast, and Reports."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.database import get_supabase, run_db
from app.models.analysis_filters import AnalysisFilters
from app.services.transaction_enrichment import extract_transaction_details
from app.services.transfer_utils import is_transfer, mark_transfers_df, split_spend_income


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _round(v: float) -> float:
    return round(float(v), 2)


def _period_totals(df: pd.DataFrame, include_transfers: bool) -> dict[str, float]:
    _, debits, credits = split_spend_income(df, include_transfers)
    transfers, _, _ = split_spend_income(df, include_transfers=False)
    transfer_vol = float(transfers["amount"].sum()) if not transfers.empty else 0.0
    income = float(credits["amount"].sum()) if not credits.empty else 0.0
    expenses = float(debits["amount"].sum()) if not debits.empty else 0.0
    return {
        "income": _round(income),
        "expenses": _round(expenses),
        "net": _round(income - expenses),
        "transfer_volume": _round(transfer_vol),
        "transaction_count": int(len(df)),
    }


async def fetch_accounts_meta(user_id: str) -> tuple[dict[str, dict], list[dict]]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name, provider, status")
        .eq("user_id", user_id)
        .neq("status", "disconnected")
        .execute()
    )
    accounts = res.data or []
    by_id = {
        a["id"]: {
            "account_name": a.get("account_name") or "Unknown",
            "provider": a.get("provider") or "unknown",
        }
        for a in accounts
    }
    return by_id, accounts


async def fetch_transactions_df(user_id: str, filters: AnalysisFilters) -> pd.DataFrame:
    sb = get_supabase()
    start, end = filters.resolved_date_range()

    query = (
        sb.table("transactions")
        .select(
            "id, transaction_date, amount, transaction_type, category, sub_category, "
            "merchant_name, description, currency, account_id, source_provider, "
            "is_recurring, raw_metadata"
        )
        .eq("user_id", user_id)
        .gte("transaction_date", start.isoformat())
        .lte("transaction_date", end.isoformat())
    )

    if filters.providers:
        query = query.in_("source_provider", filters.providers)
    if filters.account_ids:
        query = query.in_("account_id", filters.account_ids)

    res = await run_db(lambda: query.execute())
    rows = res.data or []
    if not rows:
        return pd.DataFrame()

    account_map, _ = await fetch_accounts_meta(user_id)
    df = pd.DataFrame(rows)
    df["amount"] = df["amount"].astype(float)
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["currency"] = df["currency"].fillna("USD")
    df["account_name"] = df["account_id"].map(
        lambda aid: account_map.get(aid, {}).get("account_name", "Unknown") if aid else "Unknown"
    )
    df["provider"] = df["account_id"].map(
        lambda aid: account_map.get(aid, {}).get("provider", "unknown") if aid else "unknown"
    )

    counterparties: list[str | None] = []
    channels: list[str | None] = []
    for _, row in df.iterrows():
        raw = row.get("raw_metadata") if isinstance(row.get("raw_metadata"), dict) else None
        details = extract_transaction_details(
            source_provider=row.get("source_provider") or "",
            transaction_type=row.get("transaction_type") or "debit",
            raw_metadata=raw,
            merchant_name=row.get("merchant_name"),
            description=row.get("description"),
        )
        counterparties.append(details.get("counterparty"))
        channels.append(details.get("channel"))

    df["counterparty"] = counterparties
    df["channel"] = channels
    df = mark_transfers_df(df)
    return df


async def get_analytics_meta(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    account_map, accounts = await fetch_accounts_meta(user_id)

    txn_res = await run_db(
        lambda: sb.table("transactions")
        .select("transaction_date, account_id, currency, source_provider")
        .eq("user_id", user_id)
        .order("transaction_date")
        .execute()
    )
    rows = txn_res.data or []
    dates = [r["transaction_date"] for r in rows if r.get("transaction_date")]
    currencies = sorted({r.get("currency") or "USD" for r in rows})

    account_currencies: dict[str, str] = {}
    account_providers: dict[str, str] = {}
    for r in rows:
        aid = r.get("account_id")
        if aid and aid not in account_currencies:
            account_currencies[aid] = r.get("currency") or "USD"
            account_providers[aid] = r.get("source_provider") or "unknown"

    known_ids = {a["id"] for a in accounts}
    for aid in account_currencies:
        if aid not in known_ids:
            accounts.append({
                "id": aid,
                "account_name": f"Account ({aid[:8]}…)",
                "provider": account_providers.get(aid, "unknown"),
            })

    return {
        "accounts": [
            {
                "id": a["id"],
                "account_name": a.get("account_name") or "Unknown",
                "provider": a.get("provider") or "unknown",
                "currency": account_currencies.get(a["id"], "USD"),
            }
            for a in accounts
        ],
        "date_range": {
            "min": min(dates) if dates else None,
            "max": max(dates) if dates else None,
        },
        "providers": sorted({a.get("provider") for a in accounts if a.get("provider")}),
        "currencies": currencies,
    }


def _primary_currency(df: pd.DataFrame) -> str:
    if df.empty:
        return "USD"
    vol = df.groupby("currency")["amount"].sum()
    return str(vol.idxmax())


def _filter_currency(df: pd.DataFrame, currency: str) -> pd.DataFrame:
    return df[df["currency"] == currency].copy()


def _monthly_trend(df: pd.DataFrame, include_transfers: bool) -> list[dict]:
    if df.empty:
        return []
    _, debits, credits = split_spend_income(df, include_transfers)
    work = df.copy()
    work["month"] = work["transaction_date"].dt.to_period("M").astype(str)

    months = sorted(work["month"].unique())
    result = []
    for m in months:
        mdf = work[work["month"] == m]
        inc = float(credits[credits["transaction_date"].dt.to_period("M").astype(str) == m]["amount"].sum())
        exp = float(debits[debits["transaction_date"].dt.to_period("M").astype(str) == m]["amount"].sum())
        result.append({"month": m, "income": _round(inc), "expenses": _round(exp), "net": _round(inc - exp)})
    return result


def _yearly_trend(df: pd.DataFrame, include_transfers: bool) -> list[dict]:
    if df.empty:
        return []
    _, debits, credits = split_spend_income(df, include_transfers)
    years = sorted(df["transaction_date"].dt.year.unique())
    result = []
    for y in years:
        ydf = df[df["transaction_date"].dt.year == y]
        inc = float(credits[credits["transaction_date"].dt.year == y]["amount"].sum())
        exp = float(debits[debits["transaction_date"].dt.year == y]["amount"].sum())
        result.append({"year": str(y), "income": _round(inc), "expenses": _round(exp), "net": _round(inc - exp)})
    return result


def _category_spending(debits: pd.DataFrame) -> list[dict]:
    if debits.empty:
        return []
    total = float(debits["amount"].sum()) or 1.0
    cat_spend = debits.groupby("category")["amount"].sum().sort_values(ascending=False)
    return [
        {
            "category": str(cat or "Uncategorized"),
            "amount": _round(amt),
            "pct": round(float(amt) / total * 100, 1),
        }
        for cat, amt in cat_spend.items()
    ]


def _bank_summary(df: pd.DataFrame, include_transfers: bool) -> list[dict]:
    if df.empty:
        return []
    _, debits, credits = split_spend_income(df, include_transfers)
    rows = []
    for account_id, group in df.groupby("account_id", dropna=False):
        aid = account_id if pd.notna(account_id) else None
        inc = float(credits[credits["account_id"] == account_id]["amount"].sum()) if aid else 0.0
        exp = float(debits[debits["account_id"] == account_id]["amount"].sum()) if aid else 0.0
        cur = str(group["currency"].mode().iloc[0]) if not group.empty else "USD"
        rows.append({
            "bank": str(group["account_name"].iloc[0]),
            "account_id": aid,
            "provider": str(group["provider"].iloc[0]),
            "currency": cur,
            "income": _round(inc),
            "expenses": _round(exp),
            "net": _round(inc - exp),
            "transaction_count": int(len(group)),
        })
    rows.sort(key=lambda x: x["expenses"], reverse=True)
    return rows


def _top_merchants(debits: pd.DataFrame) -> list[dict]:
    if debits.empty:
        return []
    merchant_spend = (
        debits.groupby("merchant_name")
        .agg(amount=("amount", "sum"), count=("amount", "count"))
        .sort_values("amount", ascending=False)
        .head(15)
    )
    return [
        {
            "merchant": str(name or "Unknown"),
            "amount": _round(row["amount"]),
            "count": int(row["count"]),
        }
        for name, row in merchant_spend.iterrows()
    ]


def _daily_cashflow(df: pd.DataFrame, include_transfers: bool, days: int = 30) -> list[dict]:
    if df.empty:
        return []
    _, debits, credits = split_spend_income(df, include_transfers)
    cutoff = df["transaction_date"].max() - pd.Timedelta(days=days)
    recent = df[df["transaction_date"] >= cutoff]
    rows = []
    for day, group in recent.groupby(recent["transaction_date"].dt.date):
        inc = float(credits[credits["transaction_date"].dt.date == day]["amount"].sum())
        exp = float(debits[debits["transaction_date"].dt.date == day]["amount"].sum())
        rows.append({"date": str(day), "income": _round(inc), "expenses": _round(exp), "net": _round(inc - exp)})
    return sorted(rows, key=lambda x: x["date"])


def _comparison_windows(filters: AnalysisFilters) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp, str]:
    today = date.today()
    end = filters.date_to or today
    start = filters.date_to and filters.date_from or (end - timedelta(days=30))
    if filters.date_from:
        start = filters.date_from
    else:
        start = date(end.year, end.month, 1) if filters.compare_period == "previous_month" else (end - timedelta(days=180))

    if filters.compare_period == "previous_month":
        cur_start = date(end.year, end.month, 1)
        cur_end = end
        prev_end = cur_start - timedelta(days=1)
        prev_start = date(prev_end.year, prev_end.month, 1)
        label = f"{cur_start.strftime('%b %Y')} vs {prev_start.strftime('%b %Y')}"
    elif filters.compare_period == "previous_year":
        cur_start = date(end.year, 1, 1)
        cur_end = end
        prev_start = date(end.year - 1, 1, 1)
        prev_end = date(end.year - 1, end.month, end.day)
        label = f"{end.year} YTD vs {end.year - 1} YTD"
    else:
        span = (end - start).days + 1
        cur_start, cur_end = start, end
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        label = f"{start.isoformat()}–{end.isoformat()} vs prior {span}d"

    return (
        pd.Timestamp(cur_start),
        pd.Timestamp(cur_end),
        pd.Timestamp(prev_start),
        pd.Timestamp(prev_end),
        label,
    )


def _period_comparison(df: pd.DataFrame, filters: AnalysisFilters) -> dict[str, Any]:
    cur_start, cur_end, prev_start, prev_end, label = _comparison_windows(filters)
    cur_df = df[(df["transaction_date"] >= cur_start) & (df["transaction_date"] <= pd.Timestamp(cur_end))]
    prev_df = df[(df["transaction_date"] >= prev_start) & (df["transaction_date"] <= prev_end)]

    current = _period_totals(cur_df, filters.include_transfers)
    previous = _period_totals(prev_df, filters.include_transfers)

    return {
        "label": label,
        "current": current,
        "previous": previous,
        "income_change_pct": _pct_change(current["income"], previous["income"]),
        "expense_change_pct": _pct_change(current["expenses"], previous["expenses"]),
        "net_change_pct": _pct_change(current["net"], previous["net"]),
        "transfer_volume_change_pct": _pct_change(current["transfer_volume"], previous["transfer_volume"]),
    }


def _spending_habits(df: pd.DataFrame, debits: pd.DataFrame, filters: AnalysisFilters) -> dict[str, Any]:
    if debits.empty:
        return {
            "weekday_vs_weekend": {"weekday": 0, "weekend": 0, "weekend_pct": 0},
            "channel_mix": [],
            "category_drift": [],
            "spending_velocity_mom_pct": None,
        }

    debits = debits.copy()
    debits["dow"] = debits["transaction_date"].dt.dayofweek
    weekday = float(debits[debits["dow"] < 5]["amount"].sum())
    weekend = float(debits[debits["dow"] >= 5]["amount"].sum())
    total = weekday + weekend or 1.0

    channel_mix = []
    if "channel" in debits.columns:
        ch = debits.groupby("channel")["amount"].sum().sort_values(ascending=False)
        ch_total = float(ch.sum()) or 1.0
        channel_mix = [
            {"channel": str(c or "Other"), "amount": _round(amt), "pct": round(float(amt) / ch_total * 100, 1)}
            for c, amt in ch.items()
        ]

    debits["month"] = debits["transaction_date"].dt.to_period("M").astype(str)
    months = sorted(debits["month"].unique())
    category_drift: list[dict] = []
    if len(months) >= 2:
        cur_m, prev_m = months[-1], months[-2]
        cur_cat = debits[debits["month"] == cur_m].groupby("category")["amount"].sum()
        prev_cat = debits[debits["month"] == prev_m].groupby("category")["amount"].sum()
        for cat in set(cur_cat.index) | set(prev_cat.index):
            c_amt = float(cur_cat.get(cat, 0))
            p_amt = float(prev_cat.get(cat, 0))
            if c_amt == 0 and p_amt == 0:
                continue
            category_drift.append({
                "category": str(cat or "Uncategorized"),
                "current": _round(c_amt),
                "previous": _round(p_amt),
                "change_pct": _pct_change(c_amt, p_amt),
            })
        category_drift.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
        category_drift = category_drift[:5]

    mom_pct = None
    if len(months) >= 2:
        cur_total = float(debits[debits["month"] == months[-1]]["amount"].sum())
        prev_total = float(debits[debits["month"] == months[-2]]["amount"].sum())
        mom_pct = _pct_change(cur_total, prev_total)

    return {
        "weekday_vs_weekend": {
            "weekday": _round(weekday),
            "weekend": _round(weekend),
            "weekend_pct": round(weekend / total * 100, 1),
        },
        "channel_mix": channel_mix,
        "category_drift": category_drift,
        "spending_velocity_mom_pct": mom_pct,
    }


def _income_insights(credits: pd.DataFrame) -> dict[str, Any]:
    if credits.empty:
        return {
            "stability_score": None,
            "salary_candidates": [],
            "next_payday_estimate": None,
            "monthly_income_avg": 0,
        }

    credits = credits.copy()
    credits["month"] = credits["transaction_date"].dt.to_period("M").astype(str)
    monthly = credits.groupby("month")["amount"].sum()
    monthly_vals = monthly.values.astype(float)
    stability = None
    if len(monthly_vals) >= 2 and monthly_vals.mean() > 0:
        stability = round(max(0, 100 - float(np.std(monthly_vals) / monthly_vals.mean() * 100)), 1)

    salary_candidates: list[dict] = []
    for cp, group in credits.groupby("counterparty"):
        if not cp or len(group) < 2:
            continue
        amounts = group["amount"].astype(float)
        if amounts.std() / amounts.mean() < 0.1 if amounts.mean() else False:
            salary_candidates.append({
                "counterparty": str(cp),
                "avg_amount": _round(amounts.mean()),
                "count": int(len(group)),
                "last_date": str(group["transaction_date"].max().date()),
            })
    salary_candidates.sort(key=lambda x: x["avg_amount"], reverse=True)

    next_payday = None
    if salary_candidates:
        top = credits[credits["counterparty"] == salary_candidates[0]["counterparty"]].sort_values("transaction_date")
        if len(top) >= 2:
            gaps = top["transaction_date"].diff().dt.days.dropna()
            if not gaps.empty:
                median_gap = int(gaps.median())
                last = top["transaction_date"].max().date()
                next_payday = (last + timedelta(days=median_gap)).isoformat()

    return {
        "stability_score": stability,
        "salary_candidates": salary_candidates[:5],
        "next_payday_estimate": next_payday,
        "monthly_income_avg": _round(monthly_vals.mean()) if len(monthly_vals) else 0,
    }


def _cash_runway(debits: pd.DataFrame, credits: pd.DataFrame, balances: dict) -> list[dict]:
    rows = []
    for acct in balances.get("accounts", []):
        cur = acct.get("currency", "USD")
        aid = acct.get("connected_account_id")
        acct_debits = debits[(debits["account_id"] == aid) & (debits["currency"] == cur)] if not debits.empty else debits
        acct_credits = credits[(credits["account_id"] == aid) & (credits["currency"] == cur)] if not credits.empty else credits

        days_span = 30
        if not acct_debits.empty:
            span = (acct_debits["transaction_date"].max() - acct_debits["transaction_date"].min()).days
            days_span = max(span, 7)

        total_out = float(acct_debits["amount"].sum()) if not acct_debits.empty else 0.0
        total_in = float(acct_credits["amount"].sum()) if not acct_credits.empty else 0.0
        daily_burn = (total_out - total_in) / days_span
        balance = float(acct.get("current") or 0)
        runway = int(balance / daily_burn) if daily_burn > 0 else None

        rows.append({
            "account_id": aid,
            "account_name": acct.get("institution_name") or acct.get("name"),
            "currency": cur,
            "balance": _round(balance),
            "avg_daily_net_burn": _round(daily_burn),
            "days_of_runway": runway,
        })
    return rows


def _counterparty_flows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    rows = []
    for cp, group in df.groupby("counterparty"):
        if not cp:
            continue
        sent = float(group[group["transaction_type"] == "debit"]["amount"].sum())
        received = float(group[group["transaction_type"] == "credit"]["amount"].sum())
        rows.append({
            "counterparty": str(cp),
            "sent": _round(sent),
            "received": _round(received),
            "net": _round(received - sent),
            "count": int(len(group)),
        })
    rows.sort(key=lambda x: x["sent"] + x["received"], reverse=True)
    return rows[:20]


def _transfer_activity(transfers: pd.DataFrame) -> dict[str, Any]:
    if transfers.empty:
        return {"transfer_in": 0, "transfer_out": 0, "count": 0, "top_counterparties": []}
    tin = float(transfers[transfers["transaction_type"] == "credit"]["amount"].sum())
    tout = float(transfers[transfers["transaction_type"] == "debit"]["amount"].sum())
    top = []
    if "counterparty" in transfers.columns:
        for cp, group in transfers.groupby("counterparty"):
            if not cp:
                continue
            top.append({
                "counterparty": str(cp),
                "volume": _round(float(group["amount"].sum())),
                "count": int(len(group)),
            })
        top.sort(key=lambda x: x["volume"], reverse=True)
    return {
        "transfer_in": _round(tin),
        "transfer_out": _round(tout),
        "count": int(len(transfers)),
        "top_counterparties": top[:10],
    }


def _anomalies(df: pd.DataFrame, threshold: float = 2.0) -> list[dict]:
    if df.empty:
        return []
    flagged = []
    for cp, group in df.groupby("counterparty"):
        if not cp or len(group) < 3:
            continue
        amounts = group["amount"].astype(float)
        mean, std = amounts.mean(), amounts.std()
        if std == 0:
            continue
        for _, row in group.iterrows():
            z = abs((float(row["amount"]) - mean) / std)
            if z >= threshold:
                flagged.append({
                    "id": row.get("id"),
                    "date": str(row["transaction_date"].date()),
                    "counterparty": str(cp),
                    "amount": _round(float(row["amount"])),
                    "currency": str(row.get("currency", "USD")),
                    "z_score": round(z, 2),
                    "reason": f"Amount unusual for {cp}",
                })
    flagged.sort(key=lambda x: x["z_score"], reverse=True)
    return flagged[:15]


def _recurring_detected(df: pd.DataFrame) -> list[dict]:
    items: list[dict] = []
    plaid_recurring = df[df.get("is_recurring", False) == True]  # noqa: E712
    for merchant, group in plaid_recurring.groupby("merchant_name"):
        if not merchant:
            continue
        items.append({
            "name": str(merchant),
            "amount": _round(float(group["amount"].median())),
            "currency": str(group["currency"].mode().iloc[0]),
            "frequency": "monthly",
            "source": "plaid",
            "count": int(len(group)),
        })

    debits = df[df["transaction_type"] == "debit"].copy()
    for cp, group in debits.groupby("counterparty"):
        if not cp or len(group) < 3:
            continue
        group = group.sort_values("transaction_date")
        gaps = group["transaction_date"].diff().dt.days.dropna()
        if gaps.empty:
            continue
        median_gap = gaps.median()
        if 25 <= median_gap <= 35:
            amounts = group["amount"].astype(float)
            if amounts.std() / amounts.mean() < 0.08 if amounts.mean() else False:
                items.append({
                    "name": str(cp),
                    "amount": _round(amounts.median()),
                    "currency": str(group["currency"].mode().iloc[0]),
                    "frequency": "monthly",
                    "source": "pattern",
                    "count": int(len(group)),
                })
    return items[:20]


def _account_snapshot(df: pd.DataFrame, account_id: str, include_transfers: bool) -> dict[str, Any]:
    adf = df[df["account_id"] == account_id]
    totals = _period_totals(adf, include_transfers)
    _, debits, _ = split_spend_income(adf, include_transfers)
    top_cats = _category_spending(debits)[:5]
    name = str(adf["account_name"].iloc[0]) if not adf.empty else "Unknown"
    provider = str(adf["provider"].iloc[0]) if not adf.empty else "unknown"
    currency = str(adf["currency"].mode().iloc[0]) if not adf.empty else "USD"
    savings = (totals["net"] / totals["income"] * 100) if totals["income"] > 0 else None
    return {
        "account_id": account_id,
        "account_name": name,
        "provider": provider,
        "currency": currency,
        **totals,
        "savings_rate": round(savings, 1) if savings is not None else None,
        "top_categories": top_cats,
    }


def _account_comparison(df: pd.DataFrame, filters: AnalysisFilters) -> dict[str, Any] | None:
    a, b = filters.compare_account_a, filters.compare_account_b
    if not a or not b or a == b:
        return None

    snap_a = _account_snapshot(df, a, filters.include_transfers)
    snap_b = _account_snapshot(df, b, filters.include_transfers)

    cats_a = {c["category"]: c["amount"] for c in snap_a.get("top_categories", [])}
    cats_b = {c["category"]: c["amount"] for c in snap_b.get("top_categories", [])}
    category_diff = []
    for cat in set(cats_a) | set(cats_b):
        ca, cb = cats_a.get(cat, 0), cats_b.get(cat, 0)
        category_diff.append({
            "category": cat,
            "amount_a": ca,
            "amount_b": cb,
            "delta_pct": _pct_change(ca, cb),
        })
    category_diff.sort(key=lambda x: max(x["amount_a"], x["amount_b"]), reverse=True)

    return {
        "account_a": snap_a,
        "account_b": snap_b,
        "deltas": {
            "income": _pct_change(snap_a["income"], snap_b["income"]),
            "expenses": _pct_change(snap_a["expenses"], snap_b["expenses"]),
            "net": _pct_change(snap_a["net"], snap_b["net"]),
        },
        "category_diff": category_diff[:10],
    }


def _generate_insights(
    period_comparison: dict,
    spending_habits: dict,
    income_insights: dict,
    transfer_activity: dict,
    cash_runway: list,
    primary_currency: str,
) -> list[dict]:
    bullets: list[dict] = []

    exp_chg = period_comparison.get("expense_change_pct")
    if exp_chg is not None:
        direction = "up" if exp_chg > 0 else "down"
        bullets.append({
            "title": "Spending trend",
            "body": f"Expenses are {direction} {abs(exp_chg):.1f}% vs the comparison period ({primary_currency}).",
            "type": "warning" if exp_chg > 10 else "info",
        })

    weekend_pct = spending_habits.get("weekday_vs_weekend", {}).get("weekend_pct", 0)
    if weekend_pct > 40:
        bullets.append({
            "title": "Weekend spending",
            "body": f"{weekend_pct:.0f}% of spending happens on weekends.",
            "type": "info",
        })

    if income_insights.get("salary_candidates"):
        sal = income_insights["salary_candidates"][0]
        bullets.append({
            "title": "Detected income",
            "body": f"Recurring credit from {sal['counterparty']} (~{sal['avg_amount']:,.0f} {primary_currency}).",
            "type": "positive",
        })

    if transfer_activity.get("count", 0) > 0:
        bullets.append({
            "title": "Transfer activity",
            "body": (
                f"{transfer_activity['count']} transfers: "
                f"in {transfer_activity['transfer_in']:,.0f}, out {transfer_activity['transfer_out']:,.0f} {primary_currency}."
            ),
            "type": "info",
        })

    for runway in cash_runway:
        days = runway.get("days_of_runway")
        if days is not None and days < 30:
            bullets.append({
                "title": "Low runway",
                "body": f"{runway['account_name']} may run low in ~{days} days at current burn.",
                "type": "warning",
            })

    stability = income_insights.get("stability_score")
    if stability is not None:
        bullets.append({
            "title": "Income stability",
            "body": f"Income stability score: {stability}/100.",
            "type": "positive" if stability >= 70 else "info",
        })

    return bullets[:10]


def _compute_metrics_from_df(debits: pd.DataFrame, credits: pd.DataFrame, filters: AnalysisFilters) -> dict[str, Any]:
    start, end = filters.resolved_date_range()
    income = float(credits["amount"].sum()) if not credits.empty else 0.0
    expenses = float(debits["amount"].sum()) if not debits.empty else 0.0
    net = income - expenses
    savings_rate = (net / income * 100) if income > 0 else None
    days = (end - start).days + 1
    burn_rate = expenses / days if expenses > 0 else None
    return {
        "total_income": _round(income),
        "total_expenses": _round(expenses),
        "net_cash_flow": _round(net),
        "savings_rate": round(savings_rate, 1) if savings_rate is not None else None,
        "burn_rate": round(burn_rate, 2) if burn_rate is not None else None,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


def build_analysis_payload(
    df: pd.DataFrame,
    filters: AnalysisFilters,
    balances: dict[str, Any],
) -> dict[str, Any]:
    """Build full analysis dict from a prepared DataFrame."""
    if df.empty:
        return _empty_analysis(filters, balances)

    primary = _primary_currency(df)
    cdf = _filter_currency(df, primary)

    transfers, debits, credits = split_spend_income(cdf, filters.include_transfers)
    all_transfers = cdf[cdf["is_transfer"]]

    metrics = _compute_metrics_from_df(debits, credits, filters)
    period_comparison = _period_comparison(cdf, filters)
    spending_habits = _spending_habits(cdf, debits, filters)
    income_insights = _income_insights(credits)
    cash_runway = _cash_runway(debits, credits, balances)
    transfer_activity = _transfer_activity(all_transfers)
    anomalies = _anomalies(cdf)
    recurring = _recurring_detected(cdf)
    account_comparison = _account_comparison(cdf, filters)

    insights = _generate_insights(
        period_comparison, spending_habits, income_insights, transfer_activity, cash_runway, primary
    )

    currencies = sorted(df["currency"].unique().tolist())
    by_currency = {}
    for cur in currencies:
        cur_df = _filter_currency(df, cur)
        _, cur_debits, cur_credits = split_spend_income(cur_df, filters.include_transfers)
        by_currency[cur] = _compute_metrics_from_df(cur_debits, cur_credits, filters)

    return {
        "filters_applied": filters.to_dict(),
        "primary_currency": primary,
        "currencies": currencies,
        "by_currency": by_currency,
        "balances": balances,
        "metrics": metrics,
        "monthly_trend": _monthly_trend(cdf, filters.include_transfers),
        "yearly_trend": _yearly_trend(cdf, filters.include_transfers),
        "category_spending": _category_spending(debits),
        "bank_summary": _bank_summary(cdf, filters.include_transfers),
        "top_merchants": _top_merchants(debits),
        "daily_cashflow": _daily_cashflow(cdf, filters.include_transfers),
        "period_comparison": period_comparison,
        "spending_habits": spending_habits,
        "income_insights": income_insights,
        "cash_runway": cash_runway,
        "counterparty_flows": _counterparty_flows(cdf),
        "transfer_activity": transfer_activity,
        "anomalies": anomalies,
        "recurring_detected": recurring,
        "account_comparison": account_comparison,
        "insights": insights,
        "transaction_count": int(len(cdf)),
    }


def _empty_analysis(filters: AnalysisFilters, balances: dict) -> dict[str, Any]:
    empty_period = {
        "label": "No data",
        "current": {"income": 0, "expenses": 0, "net": 0, "transfer_volume": 0, "transaction_count": 0},
        "previous": {"income": 0, "expenses": 0, "net": 0, "transfer_volume": 0, "transaction_count": 0},
        "income_change_pct": None,
        "expense_change_pct": None,
        "net_change_pct": None,
        "transfer_volume_change_pct": None,
    }
    return {
        "filters_applied": filters.to_dict(),
        "primary_currency": "USD",
        "currencies": [],
        "by_currency": {},
        "balances": balances,
        "metrics": {
            "total_income": 0,
            "total_expenses": 0,
            "net_cash_flow": 0,
            "savings_rate": None,
            "burn_rate": None,
            "period_start": filters.resolved_date_range()[0].isoformat(),
            "period_end": filters.resolved_date_range()[1].isoformat(),
        },
        "monthly_trend": [],
        "yearly_trend": [],
        "category_spending": [],
        "bank_summary": [],
        "top_merchants": [],
        "daily_cashflow": [],
        "period_comparison": empty_period,
        "spending_habits": {},
        "income_insights": {},
        "cash_runway": [],
        "counterparty_flows": [],
        "transfer_activity": {},
        "anomalies": [],
        "recurring_detected": [],
        "account_comparison": None,
        "insights": [],
        "transaction_count": 0,
    }


async def build_analysis(
    user_id: str,
    filters: AnalysisFilters,
    balances: dict[str, Any],
) -> dict[str, Any]:
    df = await fetch_transactions_df(user_id, filters)
    return build_analysis_payload(df, filters, balances)
