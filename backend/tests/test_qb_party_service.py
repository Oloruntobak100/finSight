"""Tests for QuickBooks vendor/customer party helpers."""

from app.services.books_service import _apply_entity_and_doc, _build_purchase_payload
from app.services.qb_party_service import (
    normalize_party_lookup,
    qb_party_type_for_posting,
    suggest_party,
    txn_doc_number,
)


def test_party_type_expense_is_vendor():
    assert (
        qb_party_type_for_posting(
            qb_posting_type="expense",
            offset_account_type="Expense",
            transaction_type="debit",
        )
        == "Vendor"
    )


def test_party_type_income_deposit_is_customer():
    assert (
        qb_party_type_for_posting(
            qb_posting_type="deposit",
            offset_account_type="Income",
            transaction_type="credit",
        )
        == "Customer"
    )


def test_party_type_transfer_is_none():
    assert (
        qb_party_type_for_posting(
            qb_posting_type="transfer",
            offset_account_type="Bank",
            transaction_type="debit",
        )
        is None
    )


def test_suggest_party_fuzzy_match():
    parties = [
        {"qb_vendor_id": "1", "display_name": "Uber Trip Help Uber Com"},
        {"qb_vendor_id": "2", "display_name": "Shoprite"},
    ]
    hit = suggest_party("uber trip help uber com", "Vendor", parties, id_key="qb_vendor_id")
    assert hit is not None
    assert hit["qb_party_id"] == "1"


def test_normalize_party_lookup_strips_punctuation():
    assert normalize_party_lookup("UBER* TRIP") == normalize_party_lookup("uber trip")


def test_purchase_payload_includes_entity_ref():
    txn = {
        "id": "t1",
        "transaction_date": "2026-06-27",
        "amount": 10000,
        "qb_payment_account_id": "35",
        "qb_account_id": "42",
        "merchant_name": "Landlord",
        "qb_party_id": "99",
        "qb_party_type": "Vendor",
    }
    payload = _build_purchase_payload(txn)
    assert payload["EntityRef"] == {"value": "99", "type": "Vendor"}


def test_doc_number_from_mono_ref():
    txn = {
        "raw_metadata": {
            "metadata": {"ref_num": "TRF123456"},
        }
    }
    assert txn_doc_number(txn) == "TRF123456"


def test_apply_entity_and_doc_on_deposit():
    txn = {
        "id": "t2",
        "qb_party_id": "7",
        "qb_party_type": "Customer",
        "raw_metadata": {"metadata": {"ref_num": "REF-1"}},
    }
    payload = _apply_entity_and_doc({"Line": []}, txn)
    assert payload["EntityRef"]["type"] == "Customer"
    assert payload["DocNumber"] == "REF-1"
