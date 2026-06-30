"""Tests for Mono kobo → naira normalization."""

from app.services.mono_money import mono_kobo_to_naira, normalize_mono_balance


def test_mono_kobo_to_naira():
    assert mono_kobo_to_naira(327_000_000) == 3_270_000.0
    assert mono_kobo_to_naira(100) == 1.0
    assert mono_kobo_to_naira(None) == 0.0


def test_normalize_mono_balance_from_kobo():
    assert normalize_mono_balance(327_000_000) == 3_270_000.0


def test_normalize_mono_balance_already_naira():
    assert normalize_mono_balance(3_270_000, already_naira=True) == 3_270_000.0
