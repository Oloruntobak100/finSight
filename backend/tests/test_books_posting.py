"""Tests for QuickBooks posting payload routing."""

from app.services.books_service import _build_transfer_payload


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
