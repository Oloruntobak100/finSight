"""QuickBooks Reports API with caching."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.database import get_supabase, run_db
from app.services.quickbooks_service import qb_company_get_json


def _params_hash(report_type: str, params: dict[str, str]) -> str:
    payload = json.dumps({"type": report_type, **params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


async def _get_cached(
    user_id: str,
    report_type: str,
    params_hash: str,
    max_age_hours: int = 1,
) -> dict[str, Any] | None:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("qb_report_cache")
        .select("*")
        .eq("user_id", user_id)
        .eq("report_type", report_type)
        .eq("params_hash", params_hash)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        return None
    fetched = row.get("fetched_at")
    if not fetched:
        return row.get("data")
    try:
        ts = datetime.fromisoformat(str(fetched).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - ts > timedelta(hours=max_age_hours):
            return None
    except ValueError:
        return None
    return row.get("data")


async def _set_cache(
    user_id: str,
    report_type: str,
    params_hash: str,
    data: dict[str, Any],
) -> None:
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "report_type": report_type,
        "params_hash": params_hash,
        "data": data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    await run_db(
        lambda: sb.table("qb_report_cache")
        .upsert(row, on_conflict="user_id,report_type,params_hash")
        .execute()
    )


def _parse_report_sections(report: dict[str, Any]) -> dict[str, Any]:
    rows = report.get("Rows", {}).get("Row", []) or []
    sections: list[dict[str, Any]] = []

    def walk(row_list: list, section_name: str = "Report") -> None:
        for row in row_list:
            if not isinstance(row, dict):
                continue
            header = row.get("Header", {}).get("ColData", [])
            if header and header[0].get("value"):
                section_name = header[0]["value"]
            if row.get("type") == "Section":
                nested = row.get("Rows", {}).get("Row", [])
                if nested:
                    walk(nested, section_name)
            summary = row.get("Summary", {}).get("ColData", [])
            if summary and len(summary) >= 2:
                label = summary[0].get("value")
                amount_raw = summary[1].get("value")
                try:
                    amount = float(str(amount_raw).replace(",", "")) if amount_raw else 0.0
                except ValueError:
                    amount = 0.0
                if label:
                    sections.append({"section": section_name, "label": label, "amount": amount})

    walk(rows if isinstance(rows, list) else [rows])
    return {
        "report_name": report.get("Header", {}).get("ReportName"),
        "start_date": report.get("Header", {}).get("StartPeriod"),
        "end_date": report.get("Header", {}).get("EndPeriod"),
        "sections": sections,
        "raw_header": report.get("Header"),
    }


async def fetch_report(
    user_id: str,
    report_type: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    as_of_date: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    params: dict[str, str] = {}
    path_map = {
        "pnl": "ProfitAndLoss",
        "balance-sheet": "BalanceSheet",
        "cash-flow": "CashFlow",
    }
    qb_name = path_map.get(report_type)
    if not qb_name:
        raise ValueError(f"Unknown report type: {report_type}")

    query_parts = []
    if start_date:
        params["start_date"] = start_date
        query_parts.append(f"start_date={start_date}")
    if end_date:
        params["end_date"] = end_date
        query_parts.append(f"end_date={end_date}")
    if as_of_date:
        params["as_of_date"] = as_of_date
        query_parts.append(f"date_macro=Custom&end_date={as_of_date}")

    ph = _params_hash(report_type, params)
    if not refresh:
        cached = await _get_cached(user_id, report_type, ph)
        if cached:
            return {**cached, "cached": True, "fetched_at": cached.get("fetched_at")}

    qs = "&".join(query_parts)
    path = f"/reports/{qb_name}?minorversion=75"
    if qs:
        path += f"&{qs}"

    data = await qb_company_get_json(user_id, path)
    parsed = _parse_report_sections(data)
    parsed["cached"] = False
    parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
    await _set_cache(user_id, report_type, ph, parsed)
    return parsed
