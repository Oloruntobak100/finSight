"""Tests for QBO bank activity normalization."""

from app.services.reconciliation.qbo_bank_activity import (
    _normalize_deposit,
    _normalize_purchase,
    _normalize_transfer,
)


def test_normalize_purchase_outflow():
    row = _normalize_purchase(
        {"Id": "1", "TotalAmt": 1500, "TxnDate": "2025-06-15", "AccountRef": {"value": "35"}},
        "35",
    )
    assert row is not None
    assert row["direction"] == "out"
    assert row["amount"] == 1500


def test_normalize_purchase_wrong_bank():
    row = _normalize_purchase(
        {"Id": "1", "TotalAmt": 1500, "AccountRef": {"value": "99"}},
        "35",
    )
    assert row is None


def test_normalize_deposit_inflow():
    row = _normalize_deposit(
        {"Id": "2", "TotalAmt": 2000, "TxnDate": "2025-06-16", "DepositToAccountRef": {"value": "35"}},
        "35",
    )
    assert row is not None
    assert row["direction"] == "in"


def test_normalize_transfer_out():
    row = _normalize_transfer(
        {"Id": "3", "Amount": 5000, "TxnDate": "2025-06-17", "FromAccountRef": {"value": "35"}, "ToAccountRef": {"value": "99"}},
        "35",
    )
    assert row is not None
    assert row["direction"] == "out"


def test_normalize_transfer_in():
    row = _normalize_transfer(
        {"Id": "4", "Amount": 5000, "TxnDate": "2025-06-17", "FromAccountRef": {"value": "99"}, "ToAccountRef": {"value": "35"}},
        "35",
    )
    assert row is not None
    assert row["direction"] == "in"
