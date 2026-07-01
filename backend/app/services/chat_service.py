import json
from datetime import date, timedelta
from typing import Any, AsyncGenerator

import anthropic
from openai import AsyncOpenAI

from app.config import settings
from app.database import get_supabase, run_db
from app.services.analysis_service import get_financial_analysis
from app.services.analytics_service import get_latest_metrics, get_subscriptions
from app.services.forecasting_service import get_latest_forecasts

SYSTEM_PROMPT = """You are FinSight AI, a direct and trustworthy financial advisor.
You answer questions using ONLY the user's actual financial data provided in context.
Revenue, expenses, and net profit come from QuickBooks P&L when data_source is quickbooks.
Bank transactions are operational context (merchants, transfers, unreconciled activity).
Be specific — cite amounts, merchants, banks, categories, and dates when relevant.
When comparing periods, use the period_comparison and monthly_trend data.
If Books coverage is incomplete, say P&L may not include all bank activity yet.
If data is missing, say so clearly. Never invent transactions or balances.
Keep responses concise and actionable. Use bullet points for lists."""


def _resolve_llm_provider() -> str:
    if settings.llm_provider in ("openai", "anthropic"):
        return settings.llm_provider
    if settings.openai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    return "none"


async def build_financial_context(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()

    txns_res = await run_db(
        lambda: sb.table("transactions")
        .select(
            "transaction_date, merchant_name, category, amount, transaction_type, "
            "currency, account_id"
        )
        .eq("user_id", user_id)
        .is_("archived_at", "null")
        .gte("transaction_date", ninety_days_ago)
        .order("transaction_date", desc=True)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )

    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name")
        .eq("user_id", user_id)
        .execute()
    )
    bank_map = {a["id"]: a.get("account_name") for a in (accounts_res.data or [])}

    transactions = []
    for txn in txns_res.data or []:
        row = dict(txn)
        row["bank"] = bank_map.get(txn.get("account_id"), "Unknown")
        transactions.append(row)

    analysis = await get_financial_analysis(user_id, refresh_balances=True)
    metrics = await get_latest_metrics(user_id)
    forecasts = await get_latest_forecasts(user_id)
    subscriptions = await get_subscriptions(user_id)

    return {
        "data_source": analysis.get("data_source"),
        "books_coverage": analysis.get("books_coverage", {}),
        "qb_reports": analysis.get("qb_reports", {}),
        "bank_activity": analysis.get("bank_activity", {}),
        "balances": analysis["balances"],
        "metrics_current_month": analysis["metrics"],
        "period_comparison": analysis["period_comparison"],
        "monthly_trend": analysis["monthly_trend"],
        "yearly_trend": analysis.get("yearly_trend", []),
        "category_spending": analysis["category_spending"][:12],
        "bank_summary": analysis["bank_summary"],
        "top_merchants": analysis["top_merchants"][:10],
        "spending_habits": analysis.get("spending_habits", {}),
        "income_insights": analysis.get("income_insights", {}),
        "transfer_activity": analysis.get("transfer_activity", {}),
        "counterparty_flows": analysis.get("counterparty_flows", [])[:10],
        "anomalies": analysis.get("anomalies", [])[:5],
        "insights": analysis.get("insights", []),
        "transactions_last_90_days": transactions,
        "financial_metrics": metrics,
        "forecasts": forecasts,
        "subscriptions": subscriptions,
    }


async def _stream_openai(messages: list[dict[str, str]], system: str) -> AsyncGenerator[str, None]:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    stream = await client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=2048,
        stream=True,
        messages=[{"role": "system", "content": system}, *messages],
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta


async def _stream_anthropic(messages: list[dict[str, str]], system: str) -> AsyncGenerator[str, None]:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


async def stream_chat_response(
    user_id: str,
    session_id: str,
    user_message: str,
) -> AsyncGenerator[str, None]:
    provider = _resolve_llm_provider()
    if provider == "none":
        yield "No AI provider configured. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to your .env file."
        return

    sb = get_supabase()

    history_res = await run_db(
        lambda: sb.table("chat_messages")
        .select("role, content")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    context = await build_financial_context(user_id)
    messages = [{"role": m["role"], "content": m["content"]} for m in (history_res.data or [])]
    messages.append({"role": "user", "content": user_message})

    system = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Today's date: {date.today().isoformat()}\n\n"
        f"Financial context (live data):\n{json.dumps(context, default=str)}"
    )

    full_response = ""
    stream_fn = _stream_openai if provider == "openai" else _stream_anthropic

    async for text in stream_fn(messages, system):
        full_response += text
        yield text

    await run_db(
        lambda: sb.table("chat_messages")
        .insert([
            {"session_id": session_id, "role": "user", "content": user_message},
            {
                "session_id": session_id,
                "role": "assistant",
                "content": full_response,
                "context_snapshot": context,
            },
        ])
        .execute()
    )
    await run_db(
        lambda: sb.table("chat_sessions")
        .update({"last_message_at": date.today().isoformat()})
        .eq("id", session_id)
        .execute()
    )
