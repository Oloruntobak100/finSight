"""Tests for transaction posting kind detection."""

from app.services.transaction_posting_utils import (
    detect_posting_kind,
    is_balance_sheet_movement,
    is_bank_fee,
    is_reversal,
    is_vendor_refund,
    posting_kind_to_intent,
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


def test_nip_debit_is_expense():
    kind = detect_posting_kind(
        {
            "transaction_type": "debit",
            "merchant_name": "NIP/John",
            "description": "Sent to John via NIP",
            "category": "Online Payments",
        }
    )
    assert kind == "expense"


def test_nip_credit_is_income():
    kind = detect_posting_kind(
        {
            "transaction_type": "credit",
            "merchant_name": "Adebayo Tunde",
            "description": "Received from Adebayo Tunde (NIP)",
            "category": "Other Income",
        }
    )
    assert kind == "income"


def test_internal_transfer_still_detected():
    kind = detect_posting_kind(
        {
            "transaction_type": "debit",
            "merchant_name": "Kuda",
            "description": "Transfer to own account",
            "category": "Transfer Out",
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


def test_mono_loan_slug_is_balance_sheet():
    kind = detect_posting_kind(
        {
            "transaction_type": "credit",
            "category": "Loans",
            "raw_metadata": {"metadata": {"category": "loan"}, "narration": "Loan disbursement"},
        }
    )
    assert kind == "balance_sheet"


def test_loan_repayment_debit_is_balance_sheet():
    kind = detect_posting_kind(
        {
            "transaction_type": "debit",
            "category": "Loan Repayment",
        }
    )
    assert kind == "balance_sheet"


def test_savings_is_balance_sheet():
    assert is_balance_sheet_movement({"category": "Savings", "transaction_type": "debit"})


def test_vendor_refund_credit():
    kind = detect_posting_kind(
        {
            "transaction_type": "credit",
            "merchant_name": "Amazon",
            "description": "Refund for order 123",
        }
    )
    assert kind == "refund"


def test_refund_is_not_income():
    assert is_vendor_refund(description="Payment refund from vendor")


def test_learned_kind_overrides_credit_default():
    kind = detect_posting_kind(
        {"transaction_type": "credit", "category": "Salary"},
        learned_kind="balance_sheet",
    )
    assert kind == "balance_sheet"


def test_posting_kind_to_intent_refund():
    assert posting_kind_to_intent("refund") == "expense"


def test_posting_kind_to_intent_balance_sheet():
    assert posting_kind_to_intent("balance_sheet") == "transfer"
