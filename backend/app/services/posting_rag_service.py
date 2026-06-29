"""RAG memory for approval-trained QuickBooks account suggestions."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.database import get_supabase, run_db
from app.services.fingerprint_service import extract_fingerprint

logger = logging.getLogger(__name__)

RAG_MATCH_THRESHOLD = 0.85
RAG_MATCH_COUNT = 5


async def user_has_posting_memory(user_id: str) -> bool:
    """True once the user has approved at least one posting (RAG training started)."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("posting_memory")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return (res.count or 0) > 0


async def _embed_text(text: str) -> list[float] | None:
    if not settings.openai_api_key:
        return None
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        res = await client.embeddings.create(
            model=settings.openai_embedding_model,
            input=text[:8000],
        )
        return res.data[0].embedding
    except Exception:
        logger.exception("Embedding failed")
        return None


def build_memory_content_text(
    txn: dict[str, Any],
    qb_account_name: str | None,
    qb_account_id: str,
) -> str:
    fp = extract_fingerprint(txn)
    merchant = txn.get("merchant_name") or ""
    desc = txn.get("description") or ""
    amount = txn.get("amount")
    currency = txn.get("currency") or "NGN"
    return (
        f"{fp['payee_pattern']} | {fp['channel']} | {currency} {amount} | "
        f"{merchant} | {desc[:200]} → {qb_account_name or qb_account_id}"
    )


async def store_posting_memory(
    user_id: str,
    txn: dict[str, Any],
    qb_account_id: str,
    qb_account_name: str | None,
    *,
    fingerprint_id: str | None = None,
    posting_decision_id: str | None = None,
    method: str = "manual",
) -> dict[str, Any] | None:
    content = build_memory_content_text(txn, qb_account_name, qb_account_id)
    embedding = await _embed_text(content)
    if not embedding:
        return None

    sb = get_supabase()
    row = {
        "user_id": user_id,
        "transaction_id": txn.get("id"),
        "fingerprint_id": fingerprint_id,
        "posting_decision_id": posting_decision_id,
        "content_text": content,
        "embedding": embedding,
        "qb_account_id": qb_account_id,
        "qb_account_name": qb_account_name,
        "method": method,
    }
    res = await run_db(lambda: sb.table("posting_memory").insert(row).execute())
    return (res.data or [row])[0]


async def search_similar_memories(
    user_id: str,
    txn: dict[str, Any],
    *,
    threshold: float = RAG_MATCH_THRESHOLD,
    count: int = RAG_MATCH_COUNT,
) -> list[dict[str, Any]]:
    content = build_memory_content_text(txn, None, "")
    embedding = await _embed_text(content)
    if not embedding:
        return []

    sb = get_supabase()
    try:
        res = await run_db(
            lambda: sb.rpc(
                "match_posting_memories",
                {
                    "query_embedding": embedding,
                    "match_user_id": user_id,
                    "match_threshold": threshold,
                    "match_count": count,
                },
            ).execute()
        )
        return res.data or []
    except Exception:
        logger.exception("RAG search failed for user %s", user_id)
        return []


async def rag_classify_hint(
    user_id: str,
    txn: dict[str, Any],
    coa_ids: set[str],
) -> tuple[str | None, str | None, float, str | None]:
    """Return (account_id, account_name, confidence, reason) from best RAG hit."""
    hits = await search_similar_memories(user_id, txn)
    if not hits:
        return None, None, 0.0, None

    best = hits[0]
    account_id = str(best.get("qb_account_id") or "")
    if not account_id or (coa_ids and account_id not in coa_ids):
        return None, None, 0.0, None

    similarity = float(best.get("similarity") or 0)
    name = best.get("qb_account_name")
    reason = f"Similar to '{best.get('content_text', '')[:80]}' ({similarity:.0%})"
    return account_id, name, round(similarity, 2), reason


async def recent_decisions_context(user_id: str, limit: int = 10) -> str:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("posting_decisions")
        .select("final_account_name, reason_text, method, transaction_id")
        .eq("user_id", user_id)
        .eq("was_accepted", True)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    lines: list[str] = []
    for row in res.data or []:
        txn_res = await run_db(
            lambda tid=row["transaction_id"]: sb.table("transactions")
            .select("merchant_name, description, payee_pattern")
            .eq("id", tid)
            .single()
            .execute()
        )
        txn = txn_res.data or {}
        label = txn.get("payee_pattern") or txn.get("merchant_name") or txn.get("description") or "?"
        acct = row.get("final_account_name") or "?"
        lines.append(f"- '{label}' → {acct} ({row.get('method', 'manual')})")
    if not lines:
        return "No prior approvals yet."
    return "Recent user approvals:\n" + "\n".join(lines)
