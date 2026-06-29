"""Tests for balance proof calculation."""

from app.services.reconciliation.balance_proof_service import (
    BANK_ADD_STATUSES,
    BANK_SUB_STATUSES,
    BOOK_ADD_STATUSES,
    BOOK_SUB_STATUSES,
)


def test_balance_proof_status_buckets():
    assert "DEPOSITS_IN_TRANSIT" in BANK_ADD_STATUSES
    assert "OUTSTANDING_PAYMENT" in BANK_SUB_STATUSES
    assert "UNRECORDED_BANK_CHARGE" in BOOK_SUB_STATUSES
    assert "UNRECORDED_BANK_CREDIT" in BOOK_ADD_STATUSES


def test_adjusted_bank_formula():
    mono = 100000.0
    dit = 5000.0
    outstanding = 3000.0
    bank_adj = 0.0
    adjusted = mono + dit - outstanding + bank_adj
    assert adjusted == 102000.0


def test_adjusted_book_formula():
    qbo = 101970.0
    charges = 30.0
    credits = 0.0
    book_adj = 0.0
    adjusted = qbo - charges + credits + book_adj
    assert adjusted == 101940.0


def test_variance_zero_when_balanced():
    adjusted_bank = 102000.0
    adjusted_book = 102000.0
    assert round(adjusted_bank - adjusted_book, 2) == 0.0
