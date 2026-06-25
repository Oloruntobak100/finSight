"""Unit tests for posting RAG helpers."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.posting_rag_service import (
    RAG_MATCH_THRESHOLD,
    build_memory_content_text,
    rag_classify_hint,
)


def test_build_memory_content_text():
    txn = {
        "merchant_name": "Landlord",
        "description": "NIP/GTB/LANDLORD/RNT",
        "amount": 450000,
        "currency": "NGN",
        "raw_metadata": {"narration": "NIP/GTB/LANDLORD/RNT"},
    }
    text = build_memory_content_text(txn, "Rent Expense", "42")
    assert "landlord" in text.lower()
    assert "Rent Expense" in text


@pytest.mark.asyncio
async def test_rag_classify_hint_uses_best_hit():
    hits = [
        {
            "qb_account_id": "42",
            "qb_account_name": "Rent",
            "similarity": 0.91,
            "content_text": "landlord | NIP | NGN 450000",
        }
    ]
    with patch(
        "app.services.posting_rag_service.search_similar_memories",
        new=AsyncMock(return_value=hits),
    ):
        acct_id, name, conf, reason = await rag_classify_hint(
            "user-1",
            {"merchant_name": "Landlord"},
            {"35", "42"},
        )
    assert acct_id == "42"
    assert name == "Rent"
    assert conf == 0.91
    assert reason is not None


@pytest.mark.asyncio
async def test_rag_classify_hint_rejects_stale_coa():
    hits = [
        {
            "qb_account_id": "99",
            "qb_account_name": "Deleted",
            "similarity": 0.95,
            "content_text": "old memory",
        }
    ]
    with patch(
        "app.services.posting_rag_service.search_similar_memories",
        new=AsyncMock(return_value=hits),
    ):
        acct_id, name, conf, reason = await rag_classify_hint(
            "user-1",
            {"merchant_name": "Landlord"},
            {"35", "42"},
        )
    assert acct_id is None
    assert conf == 0.0


@pytest.mark.asyncio
async def test_rag_classify_hint_below_threshold_empty():
    with patch(
        "app.services.posting_rag_service.search_similar_memories",
        new=AsyncMock(return_value=[]),
    ):
        acct_id, name, conf, reason = await rag_classify_hint(
            "user-1",
            {"merchant_name": "X"},
            set(),
        )
    assert acct_id is None
    assert conf == 0.0


def test_rag_match_threshold_constant():
    assert RAG_MATCH_THRESHOLD == 0.85
