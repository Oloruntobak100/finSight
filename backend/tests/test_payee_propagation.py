"""Tests for payee-level training propagation."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.books_service import _fingerprint_prefill_patch, _payee_propagation_candidates
from app.services.fingerprint_service import fingerprint_propagation_confidence, payee_pattern_for_row


def test_payee_pattern_derived_when_column_null():
    txn = {
        "payee_pattern": None,
        "source_provider": "mono",
        "merchant_name": "UBER TRIP",
        "description": "UBER TRIP HELP.UBER.COM",
        "raw_metadata": {"narration": "POS/UBER TRIP HELP.UBER.COM", "metadata": {}},
    }
    assert payee_pattern_for_row(txn) == payee_pattern_for_row(
        {**txn, "payee_pattern": payee_pattern_for_row(txn)}
    )


def test_propagation_confidence_uses_trained_payee():
    fp_row = {
        "payee_pattern": "uber trip help uber com",
        "confidence": 1.0,
        "recurrence_count": 2,
    }
    txn = {
        "payee_pattern": None,
        "source_provider": "mono",
        "merchant_name": "UBER* TRIP",
        "description": "POS/UBER TRIP HELP.UBER.COM",
        "raw_metadata": {"narration": "POS/UBER TRIP HELP.UBER.COM", "metadata": {}},
        "amount": 4500,
        "transaction_type": "debit",
    }
    assert fingerprint_propagation_confidence(txn, fp_row) >= 0.6


def test_propagation_prefill_moves_to_pending():
    fp_row = {
        "payee_pattern": "uber trip help uber com",
        "qb_account_id": "42",
        "qb_account_name": "Travel",
        "confidence": 1.0,
        "recurrence_count": 3,
        "posting_kind": "expense",
    }
    txn = {
        "account_id": "bank-1",
        "payee_pattern": None,
        "source_provider": "mono",
        "merchant_name": "UBER TRIP",
        "description": "WEB/UBER TRIP HELP.UBER.COM",
        "raw_metadata": {"narration": "WEB/UBER TRIP HELP.UBER.COM", "metadata": {}},
        "amount": 8900,
        "transaction_type": "debit",
        "category": "Transport",
    }
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "bank-1",
            "qb_account_id": "35",
            "qb_account_name": "Checking",
        }
    ]
    patch = _fingerprint_prefill_patch(
        txn,
        fp_row,
        mappings,
        {"35", "42"},
        None,
        propagation=True,
    )
    assert patch is not None
    assert patch["qb_account_id"] == "42"
    assert patch["qb_sync_status"] == "pending"
    assert patch["payee_pattern"] == fp_row["payee_pattern"]


@pytest.mark.asyncio
async def test_payee_candidates_match_derived_payee():
    payee = "uber trip help uber com"
    rows = [
        {
            "id": "a",
            "payee_pattern": None,
            "source_provider": "mono",
            "merchant_name": "UBER TRIP",
            "description": "WEB/UBER TRIP HELP.UBER.COM",
            "raw_metadata": {"narration": "WEB/UBER TRIP HELP.UBER.COM", "metadata": {}},
            "qb_sync_status": "needs_review",
        },
        {
            "id": "b",
            "payee_pattern": "other payee",
            "source_provider": "mono",
            "merchant_name": "SHOPRITE",
            "description": "POS SHOPRITE",
            "raw_metadata": {"narration": "POS SHOPRITE", "metadata": {}},
            "qb_sync_status": "needs_review",
        },
    ]

    with patch("app.services.books_service.run_db", new_callable=AsyncMock) as run_db:
        run_db.return_value = type("R", (), {"data": rows})()
        found = await _payee_propagation_candidates("user-1", payee, exclude_ids=set())

    assert list(found.keys()) == ["a"]
