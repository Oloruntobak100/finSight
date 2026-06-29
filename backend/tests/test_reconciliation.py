"""Unit tests for reconciliation matching helpers."""

from datetime import datetime, timezone

from app.services.reconciliation_service import (
    AMOUNT_TOLERANCE_PCT,
    DATE_TOLERANCE_DAYS,
    _amounts_match,
    _dates_match,
    _deposit_bank_account_id,
    _filter_qb_by_bank,
    _parse_qb_date,
    _purchase_bank_account_id,
)


def test_amounts_match_within_tolerance():
    assert _amounts_match(1000.0, 1005.0)
    assert not _amounts_match(1000.0, 1020.0)


def test_amounts_match_zero():
    assert _amounts_match(0.0, 0.0)


def test_dates_match_within_window():
    assert _dates_match("2025-06-15", "2025-06-17")
    assert not _dates_match("2025-06-15", "2025-06-25")


def test_parse_qb_date():
    dt = _parse_qb_date("2025-06-15T12:00:00")
    assert dt == datetime(2025, 6, 15, tzinfo=timezone.utc)


def test_tolerance_constants():
    assert DATE_TOLERANCE_DAYS == 3
    assert AMOUNT_TOLERANCE_PCT == 0.01


def test_purchase_bank_account_ref():
    assert _purchase_bank_account_id({"AccountRef": {"value": "35"}}) == "35"
    assert _purchase_bank_account_id({}) is None


def test_deposit_bank_account_ref():
    assert _deposit_bank_account_id({"DepositToAccountRef": {"value": "35"}}) == "35"


def test_filter_qb_by_bank():
    items = [
        {"Id": "1", "AccountRef": {"value": "35"}},
        {"Id": "2", "AccountRef": {"value": "99"}},
    ]
    filtered = _filter_qb_by_bank(items, "35", bank_ref=_purchase_bank_account_id)
    assert len(filtered) == 1
    assert filtered[0]["Id"] == "1"
