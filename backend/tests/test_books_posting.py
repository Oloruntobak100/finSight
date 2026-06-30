"""Tests for QuickBooks posting payload routing."""

import pytest

from app.services.books_service import (
    _assert_qbo_txn_date,
    _build_deposit_payload,
    _build_purchase_payload,
    _build_transfer_payload,
    is_closed_period_error,
)
from app.services.transaction_posting_utils import resolve_posting_entity


def test_transfer_payload_credit_moves_into_feed_bank():
    txn = {
        "id": "txn-1",
        "transaction_type": "credit",
        "transaction_date": "2026-01-15",
        "amount": 250000,
        "qb_payment_account_id": "35",
        "qb_account_id": "40",
    }
    payload = _build_transfer_payload(txn)
    assert payload["FromAccountRef"]["value"] == "40"
    assert payload["ToAccountRef"]["value"] == "35"
    assert payload["Amount"] == 250000.0


def test_transfer_payload_debit_moves_out_of_feed_bank():
    txn = {
        "id": "txn-2",
        "transaction_type": "debit",
        "transaction_date": "2026-01-16",
        "amount": 100000,
        "qb_payment_account_id": "35",
        "qb_account_id": "40",
    }
    payload = _build_transfer_payload(txn)
    assert payload["FromAccountRef"]["value"] == "35"
    assert payload["ToAccountRef"]["value"] == "40"


def test_deposit_payload_puts_customer_on_line_not_header():
    txn = {
        "id": "txn-3",
        "transaction_type": "credit",
        "transaction_date": "2025-12-30",
        "amount": 167400,
        "merchant_name": "Chukwu Emeka",
        "qb_payment_account_id": "35",
        "qb_account_id": "79",
        "qb_party_id": "12",
        "qb_party_type": "Customer",
    }
    payload = _build_deposit_payload(txn)
    assert "EntityRef" not in payload
    line = payload["Line"][0]
    assert line["DepositLineDetail"]["Entity"] == {"value": "12", "type": "CUSTOMER"}
    assert line["DepositLineDetail"]["AccountRef"]["value"] == "79"


def test_income_account_credit_routes_to_deposit_not_transfer():
    assert resolve_posting_entity("credit", "Income") == "deposit"
    assert resolve_posting_entity("credit", "Bank") == "transfer"


def test_purchase_payload_uses_transaction_date_as_txn_date():
    txn = {
        "id": "txn-p",
        "transaction_type": "debit",
        "transaction_date": "2025-06-30",
        "amount": 172000,
        "merchant_name": "APTECH",
        "qb_payment_account_id": "35",
        "qb_account_id": "79",
    }
    payload = _build_purchase_payload(txn)
    assert payload["TxnDate"] == "2025-06-30"


def test_assert_qbo_txn_date_rejects_mismatch():
    txn = {"transaction_date": "2025-06-30"}
    payload = {"TxnDate": "2025-07-03"}
    with pytest.raises(ValueError, match="transaction_date"):
        _assert_qbo_txn_date(txn, payload)


def test_assert_qbo_txn_date_allows_catch_up_override():
    txn = {"transaction_date": "2025-06-30"}
    payload = {"TxnDate": "2025-07-03"}
    _assert_qbo_txn_date(txn, payload, allow_override=True)


def test_is_closed_period_error_detects_qbo_message():
    assert is_closed_period_error("The account period has closed")
    assert not is_closed_period_error("Invalid account reference")
