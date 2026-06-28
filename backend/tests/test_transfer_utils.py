"""Tests for transfer vs P&L classification."""

from app.services.transfer_utils import is_transfer


def test_nip_payment_to_person_is_not_transfer():
    assert not is_transfer(
        "Online Payments",
        "Adebayo Tunde",
        "Received from Adebayo Tunde (NIP)",
    )


def test_nip_debit_to_vendor_is_not_transfer():
    assert not is_transfer(
        "Rent & Maintenance",
        "Landlord Properties Ltd",
        "Sent to Landlord Properties Ltd (NIP)",
    )


def test_transfer_category_without_internal_marker_is_not_transfer():
    assert not is_transfer("Transfer Out", "Kuda", "Payment")


def test_internal_transfer_marker():
    assert is_transfer(
        "Online Payments",
        "Kuda",
        "Transfer to own account",
    )


def test_legacy_transfer_category_without_nip():
    assert not is_transfer("Transfer", "John", "")
