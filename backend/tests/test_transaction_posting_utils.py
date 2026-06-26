"""Tests for transaction posting kind detection."""

from app.services.transaction_posting_utils import (
    detect_posting_kind,
    is_bank_fee,
    is_reversal,
)


def test_stamp_duty_is_fee():
    assert is_bank_fee(merchant_name="STAMP DUTY", description="Charge")


def test_reversal_detected():
    assert is_reversal(description="NIP REV/FAILED")


def test_credit_salary_is_income():
    kind = detect_posting_kind(
        {
            "transaction_type": "credit",
            "category": "Salary",
            "merchant_name": "Employer",
        }
    )
    assert kind == "income"


def test_nip_debit_is_transfer():
    kind = detect_posting_kind(
        {
            "transaction_type": "debit",
            "merchant_name": "NIP/John",
            "description": "",
            "category": "Transfer",
        }
    )
    assert kind == "transfer"


def test_expense_intent_overrides_transfer():
    kind = detect_posting_kind(
        {
            "transaction_type": "debit",
            "merchant_name": "NIP/Landlord",
            "posting_intent": "expense",
        }
    )
    assert kind == "expense"
