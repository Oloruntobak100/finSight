import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth.dependencies import CurrentUser
from app.config import settings
from app.models.analysis_filters import parse_analysis_filters
from app.services.chat_service import _resolve_llm_provider, build_financial_context
from app.services.report_service import get_comprehensive_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/comprehensive")
async def comprehensive_report(
    user_id: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
    compare_account_a: str | None = None,
    compare_account_b: str | None = None,
    compare_period: str = "previous_month",
) -> dict[str, Any]:
    filters = parse_analysis_filters(
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        account_id=account_id,
        include_transfers=include_transfers,
        compare_account_a=compare_account_a,
        compare_account_b=compare_account_b,
        compare_period=compare_period,
    )
    return await get_comprehensive_report(user_id, filters)


@router.post("/ai-insights")
async def ai_insights_report(
    user_id: CurrentUser,
    date_from: str | None = None,
    date_to: str | None = None,
    provider: list[str] | None = Query(default=None),
    account_id: list[str] | None = Query(default=None),
    include_transfers: bool = False,
    compare_period: str = "previous_month",
) -> StreamingResponse:
    provider_llm = _resolve_llm_provider()
    if provider_llm == "none":
        raise HTTPException(
            status_code=503,
            detail="Add OPENAI_API_KEY or ANTHROPIC_API_KEY to generate AI insights.",
        )

    filters = parse_analysis_filters(
        date_from=date_from,
        date_to=date_to,
        provider=provider,
        account_id=account_id,
        include_transfers=include_transfers,
        compare_period=compare_period,
    )
    report = await get_comprehensive_report(user_id, filters)
    context = await build_financial_context(user_id)

    prompt = (
        "Write a concise executive CFO report (3-5 short paragraphs) for this user. "
        "Cover: overall financial health, spending patterns, transfer activity, "
        "counterparties, subscriptions, cross-bank activity, and one actionable recommendation. "
        "Use only the data provided. Cite specific amounts with correct currency.\n\n"
        f"Report data:\n{json.dumps({**report, 'live_context': context}, default=str)}"
    )

    async def stream():
        if provider_llm == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.chat.completions.create(
                model=settings.openai_model,
                max_tokens=1500,
                stream=True,
                messages=[
                    {
                        "role": "system",
                        "content": "You are FinSight AI CFO. Write clear, professional financial reports.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    yield delta
        else:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            with client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=1500,
                system="You are FinSight AI CFO. Write clear, professional financial reports.",
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    yield text

    return StreamingResponse(stream(), media_type="text/plain")
