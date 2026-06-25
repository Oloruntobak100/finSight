"""Unit tests for reconciliation matching helpers."""

from datetime import datetime, timezone

from app.services.reconciliation_service import (
    AMOUNT_TOLERANCE_PCT,
    DATE_TOLERANCE_DAYS,
    _amounts_match,
    _dates_match,
    _parse_qb_date,
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
