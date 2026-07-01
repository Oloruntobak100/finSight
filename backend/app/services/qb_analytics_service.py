"""QuickBooks-backed financial analysis — P&L KPIs, trends, and Books coverage."""

from __future__ import annotations

import asyncio
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.models.analysis_filters import AnalysisFilters
from app.services.qb_reports_service import fetch_report
from app.services.quickbooks_service import _get_quickbooks_account_row
from app.services.transaction_analytics import _pct_change, _round


def _parse_amount(raw: Any) -> float:
    if raw is None or raw == "":
        return 0.0
    try:
        return float(str(raw).replace(",", "").strip())
    except ValueError:
        return 0.0


def _norm_label(label: str | None) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower())


def _is_income_total(label: str) -> bool:
    n = _norm_label(label)
    return n in {"total income", "total for income", "gross profit"} or n.startswith("total income")


def _is_expense_total(label: str) -> bool:
    n = _norm_label(label)
    return n in {
        "total expenses",
        "total for expenses",
        "total operating expenses",
        "total for expenses and other",
    } or n.startswith("total expense")


def _is_net_income(label: str) -> bool:
    n = _norm_label(label)
    return n in {"net income", "net operating income", "net profit"} or n.startswith("net income")


def _column_titles(report: dict[str, Any]) -> list[str]:
    cols = report.get("Columns", {}).get("Column", []) or []
    if isinstance(cols, dict):
        cols = [cols]
    titles: list[str] = []
    for col in cols:
        if not isinstance(col, dict):
            continue
        title = (col.get("ColTitle") or "").strip()
        col_type = (col.get("ColType") or "").strip()
        if title and col_type.lower() in {"money", "amount"}:
            titles.append(title)
    return titles


def _walk_pnl_rows(
    row_list: list | dict,
    *,
    section_name: str = "Report",
    column_count: int = 1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, float]]]:
    """Return (summary_lines, category_lines, monthly_totals_by_label)."""
    if isinstance(row_list, dict):
        row_list = [row_list]

    summaries: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    monthly: dict[str, dict[str, float]] = {}

    for row in row_list:
        if not isinstance(row, dict):
            continue

        header = row.get("Header", {}).get("ColData", [])
        if header and header[0].get("value"):
            section_name = header[0]["value"]

        nested = row.get("Rows", {}).get("Row")
        if nested:
            s, c, m = _walk_pnl_rows(nested, section_name=section_name, column_count=column_count)
            summaries.extend(s)
            categories.extend(c)
            for label, cols in m.items():
                monthly.setdefault(label, {}).update(cols)

        section_summary = row.get("Summary", {}).get("ColData", [])
        if section_summary and len(section_summary) >= 2 and row.get("type") == "Section":
            label = section_summary[0].get("value")
            amount = _parse_amount(section_summary[1].get("value"))
            if label:
                summaries.append({"section": section_name, "label": label, "amount": amount})
                if column_count > 1 and len(section_summary) > 2:
                    per_col = {}
                    for idx in range(1, min(len(section_summary), column_count + 1)):
                        per_col[f"col_{idx - 1}"] = _parse_amount(section_summary[idx].get("value"))
                    monthly.setdefault(label, {}).update(per_col)

        col_data = row.get("ColData")
        if row.get("type") == "Data" and col_data and len(col_data) >= 2:
            label = col_data[0].get("value")
            amount = _parse_amount(col_data[1].get("value"))
            if label and amount != 0:
                section_lower = section_name.lower()
                if "income" in section_lower or section_lower in {"other income"}:
                    categories.append({"section": section_name, "label": label, "amount": abs(amount)})

                if "expense" in section_lower or "cost of goods" in section_lower:
                    categories.append({"section": section_name, "label": label, "amount": abs(amount)})

            if label and column_count > 1 and len(col_data) > 2:
                per_col: dict[str, float] = {}
                for idx in range(1, min(len(col_data), column_count + 1)):
                    per_col[f"col_{idx - 1}"] = _parse_amount(col_data[idx].get("value"))
                monthly.setdefault(label, {}).update(per_col)

        summary = row.get("Summary", {}).get("ColData", [])
        if summary and len(summary) >= 2:
            label = summary[0].get("value")
            amount = _parse_amount(summary[1].get("value"))
            if label:
                summaries.append({"section": section_name, "label": label, "amount": amount})
                if column_count > 1 and len(summary) > 2:
                    per_col = {}
                    for idx in range(1, min(len(summary), column_count + 1)):
                        per_col[f"col_{idx - 1}"] = _parse_amount(summary[idx].get("value"))
                    monthly.setdefault(label, {}).update(per_col)

    return summaries, categories, monthly


def extract_pnl_kpis(report: dict[str, Any]) -> dict[str, float]:
    """Extract total income, expenses, and net income from a QB P&L payload."""
    rows = report.get("Rows", {}).get("Row", []) or []
    summaries, _, _ = _walk_pnl_rows(rows if isinstance(rows, list) else [rows])

    total_income = 0.0
    total_expenses = 0.0
    net_income: float | None = None

    for line in summaries:
        label = line.get("label") or ""
        amount = float(line.get("amount") or 0)
        if _is_net_income(label):
            net_income = amount
        elif _is_income_total(label):
            total_income = abs(amount)
        elif _is_expense_total(label):
            total_expenses = abs(amount)

    if net_income is None:
        net_income = total_income - total_expenses

    return {
        "total_income": _round(total_income),
        "total_expenses": _round(total_expenses),
        "net_income": _round(net_income),
        "net_cash_flow": _round(net_income),
    }


def extract_pnl_categories(report: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    rows = report.get("Rows", {}).get("Row", []) or []
    _, categories, _ = _walk_pnl_rows(rows if isinstance(rows, list) else [rows])
    expense_lines = [c for c in categories if "expense" in (c.get("section") or "").lower() or "cost" in (c.get("section") or "").lower()]
    if not expense_lines:
        expense_lines = categories
    expense_lines.sort(key=lambda x: x["amount"], reverse=True)
    total = sum(c["amount"] for c in expense_lines) or 1.0
    return [
        {
            "category": c["label"],
            "amount": _round(c["amount"]),
            "pct": round(c["amount"] / total * 100, 1),
            "section": c.get("section"),
        }
        for c in expense_lines[:limit]
    ]


def extract_monthly_trend_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse P&L with summarize_column_by=Month into monthly income/expense/net."""
    col_titles = _column_titles(report)
    if not col_titles:
        return []

    rows = report.get("Rows", {}).get("Row", []) or []
    summaries, _, monthly = _walk_pnl_rows(
        rows if isinstance(rows, list) else [rows],
        column_count=len(col_titles),
    )

    income_by_col = {i: 0.0 for i in range(len(col_titles))}
    expense_by_col = {i: 0.0 for i in range(len(col_titles))}
    net_by_col = {i: None for i in range(len(col_titles))}

    for line in summaries:
        label = line.get("label") or ""
        cols = monthly.get(label, {})
        for idx in range(len(col_titles)):
            val = cols.get(f"col_{idx}")
            if val is None:
                continue
            if _is_net_income(label):
                net_by_col[idx] = val
            elif _is_income_total(label):
                income_by_col[idx] = abs(val)
            elif _is_expense_total(label):
                expense_by_col[idx] = abs(val)

    trend: list[dict[str, Any]] = []
    for idx, title in enumerate(col_titles):
        income = income_by_col[idx]
        expenses = expense_by_col[idx]
        net = net_by_col[idx]
        if net is None:
            net = income - expenses
        trend.append(
            {
                "month": title,
                "income": _round(income),
                "expenses": _round(expenses),
                "net": _round(net),
            }
        )
    return trend


async def is_qb_connected(user_id: str) -> bool:
    row = await _get_quickbooks_account_row(user_id)
    return bool(row and row.get("status") == "active")


async def get_books_coverage(user_id: str, period_start: date, period_end: date) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("transactions")
        .select("id, qb_posted_at")
        .eq("user_id", user_id)
        .gte("transaction_date", period_start.isoformat())
        .lte("transaction_date", period_end.isoformat())
        .is_("archived_at", "null")
        .execute()
    )
    rows = res.data or []
    total = len(rows)
    posted = sum(1 for r in rows if r.get("qb_posted_at"))
    pct = round(posted / total * 100, 1) if total else None
    return {
        "posted_count": posted,
        "total_count": total,
        "coverage_pct": pct,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


async def fetch_pnl_raw(
    user_id: str,
    start_date: str,
    end_date: str,
    *,
    summarize_column_by: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    from app.services import qb_reports_service as reports

    params: dict[str, str] = {"start_date": start_date, "end_date": end_date}
    if summarize_column_by:
        params["summarize_column_by"] = summarize_column_by

    ph = reports._params_hash("pnl", params)
    if not refresh:
        cached = await reports._get_cached(user_id, "pnl", ph)
        if cached and cached.get("raw_report"):
            return cached

    query_parts = [f"start_date={start_date}", f"end_date={end_date}"]
    if summarize_column_by:
        query_parts.append(f"summarize_column_by={summarize_column_by}")
    qs = "&".join(query_parts)
    path = f"/reports/ProfitAndLoss?minorversion=75&{qs}"

    from app.services.quickbooks_service import qb_company_get_json

    raw = await qb_company_get_json(user_id, path)
    parsed = reports._parse_report_sections(raw)
    parsed["raw_report"] = raw
    parsed["cached"] = False
    parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
    await reports._set_cache(user_id, "pnl", ph, parsed)
    return parsed


async def get_qb_period_kpis(
    user_id: str,
    period_start: date,
    period_end: date,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    report = await fetch_pnl_raw(
        user_id,
        period_start.isoformat(),
        period_end.isoformat(),
        refresh=refresh,
    )
    raw = report.get("raw_report") or {}
    kpis = extract_pnl_kpis(raw)
    savings_rate = None
    if kpis["total_income"] > 0:
        savings_rate = round(kpis["net_income"] / kpis["total_income"] * 100, 1)
    kpis["savings_rate"] = savings_rate
    kpis["period_start"] = period_start.isoformat()
    kpis["period_end"] = period_end.isoformat()
    return kpis


def _month_ranges(end: date, months: int) -> list[tuple[date, date, str]]:
    """Return (start, end, label) for each calendar month ending at or before `end`."""
    ranges: list[tuple[date, date, str]] = []
    y, m = end.year, end.month
    for _ in range(months):
        _, last = monthrange(y, m)
        start = date(y, m, 1)
        finish = date(y, m, last)
        label = start.strftime("%b %Y")
        ranges.append((start, finish, label))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    ranges.reverse()
    return ranges


async def get_qb_monthly_trend(
    user_id: str,
    *,
    end_date: date | None = None,
    months: int = 12,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    end = end_date or date.today()
    start_month = end.replace(day=1) - timedelta(days=months * 31)
    start = date(start_month.year, start_month.month, 1)

    try:
        report = await fetch_pnl_raw(
            user_id,
            start.isoformat(),
            end.isoformat(),
            summarize_column_by="Month",
            refresh=refresh,
        )
        trend = extract_monthly_trend_from_report(report.get("raw_report") or {})
        if trend:
            return trend[-months:]
    except Exception:
        pass

    ranges = _month_ranges(end, months)

    async def _one(r: tuple[date, date, str]) -> dict[str, Any]:
        s, e, label = r
        try:
            kpis = await get_qb_period_kpis(user_id, s, e, refresh=refresh)
            return {
                "month": label,
                "income": kpis["total_income"],
                "expenses": kpis["total_expenses"],
                "net": kpis["net_income"],
            }
        except Exception:
            return {"month": label, "income": 0.0, "expenses": 0.0, "net": 0.0}

    return list(await asyncio.gather(*[_one(r) for r in ranges]))


def _comparison_period(
    period_start: date, period_end: date, compare: str
) -> tuple[date, date, str]:
    days = (period_end - period_start).days + 1
    if compare == "previous_year":
        prev_start = period_start.replace(year=period_start.year - 1)
        prev_end = period_end.replace(year=period_end.year - 1)
        return prev_start, prev_end, "vs same period last year"
    if compare == "previous_period":
        prev_end = period_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        return prev_start, prev_end, "vs previous period"
    # previous_month default — prior calendar month
    first = period_start.replace(day=1)
    prev_end = first - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return prev_start, prev_end, "vs previous month"


async def get_qb_period_comparison(
    user_id: str,
    period_start: date,
    period_end: date,
    compare: str = "previous_month",
) -> dict[str, Any]:
    prev_start, prev_end, label = _comparison_period(period_start, period_end, compare)
    current, previous = await asyncio.gather(
        get_qb_period_kpis(user_id, period_start, period_end),
        get_qb_period_kpis(user_id, prev_start, prev_end),
    )
    cur = {
        "income": current["total_income"],
        "expenses": current["total_expenses"],
        "net": current["net_income"],
        "transfer_volume": 0.0,
        "transaction_count": 0,
    }
    prev = {
        "income": previous["total_income"],
        "expenses": previous["total_expenses"],
        "net": previous["net_income"],
        "transfer_volume": 0.0,
        "transaction_count": 0,
    }
    return {
        "label": label,
        "current": cur,
        "previous": prev,
        "income_change_pct": _pct_change(cur["income"], prev["income"]),
        "expense_change_pct": _pct_change(cur["expenses"], prev["expenses"]),
        "net_change_pct": _pct_change(cur["net"], prev["net"]),
        "transfer_volume_change_pct": None,
    }


async def build_qb_financial_overlay(
    user_id: str,
    filters: AnalysisFilters,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    period_start, period_end = filters.resolved_date_range()
    pnl_report, kpis, trend, comparison, coverage = await asyncio.gather(
        fetch_pnl_raw(user_id, period_start.isoformat(), period_end.isoformat(), refresh=refresh),
        get_qb_period_kpis(user_id, period_start, period_end, refresh=refresh),
        get_qb_monthly_trend(user_id, end_date=period_end, months=12, refresh=refresh),
        get_qb_period_comparison(user_id, period_start, period_end, filters.compare_period),
        get_books_coverage(user_id, period_start, period_end),
    )
    raw = pnl_report.get("raw_report") or {}
    categories = extract_pnl_categories(raw)

    yearly: dict[str, dict[str, float]] = {}
    for point in trend:
        year = point["month"][-4:] if len(point["month"]) >= 4 else ""
        if not year.isdigit():
            continue
        bucket = yearly.setdefault(year, {"income": 0.0, "expenses": 0.0, "net": 0.0})
        bucket["income"] += point["income"]
        bucket["expenses"] += point["expenses"]
        bucket["net"] += point["net"]

    yearly_trend = [
        {"year": y, "income": _round(v["income"]), "expenses": _round(v["expenses"]), "net": _round(v["net"])}
        for y, v in sorted(yearly.items())
    ]

    insights: list[dict[str, str]] = []
    if coverage["total_count"] and coverage["coverage_pct"] is not None and coverage["coverage_pct"] < 100:
        insights.append(
            {
                "title": "Books coverage incomplete",
                "body": (
                    f"P&L reflects {coverage['posted_count']}/{coverage['total_count']} posted bank "
                    f"transactions ({coverage['coverage_pct']:.0f}%) for this period."
                ),
                "type": "warning",
            }
        )

    return {
        "metrics": {
            "total_income": kpis["total_income"],
            "total_expenses": kpis["total_expenses"],
            "net_cash_flow": kpis["net_income"],
            "savings_rate": kpis.get("savings_rate"),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
        "monthly_trend": trend,
        "yearly_trend": yearly_trend,
        "category_spending": categories,
        "period_comparison": comparison,
        "books_coverage": coverage,
        "insights": insights,
        "qb_reports": {
            "pnl": {
                "start_date": pnl_report.get("start_date"),
                "end_date": pnl_report.get("end_date"),
                "sections": pnl_report.get("sections", []),
                "cached": pnl_report.get("cached", False),
            }
        },
    }


async def get_qb_monthly_history_for_forecast(
    user_id: str,
    *,
    months: int = 18,
) -> list[dict[str, Any]]:
    return await get_qb_monthly_trend(user_id, end_date=date.today(), months=months)
