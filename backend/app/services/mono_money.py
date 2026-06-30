"""Mono / NGN money normalization (kobo to naira)."""

from __future__ import annotations


def mono_kobo_to_naira(value: float | int | None) -> float:
    """Convert Mono API integer kobo to naira."""
    if value is None:
        return 0.0
    return float(value) / 100.0


def normalize_mono_balance(raw_balance: float | int | None, *, already_naira: bool = False) -> float:
    """Return bank balance in naira."""
    if raw_balance is None:
        return 0.0
    if already_naira:
        return float(raw_balance)
    return mono_kobo_to_naira(raw_balance)
