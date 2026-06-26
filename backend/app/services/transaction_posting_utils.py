"""Detect how a bank transaction should post to QuickBooks."""

from __future__ import annotations

import re
from typing import Literal

from app.services.transfer_utils import is_transfer

PostingKind = Literal["expense", "income", "transfer", "fee", "reversal"]
PostingType = Literal["expense", "deposit", "fee", "transfer", "skip"]

FEE_TEXT_MARKERS = (
    "stamp duty",
    "stamp ",
    "sms charge",
    "sms fee",
    "sms alert",
    "acct maintenance",
    "account maintenance",
    "card maintenance",
    "cot ",
    "commission on",
    "bank charge",
    "bank fee",
    "service charge",
    "vat on",
    "levy",
    "nip charge",
    "nip fee",
    "transfer charge",
    "transfer fee",
)

REVERSAL_MARKERS = ("reversal", "rev/", "reversed", "failed nip", "nip reversal")


def _text_blob(category: str | None, merchant: str | None, description: str | None) -> str:
    return " ".join(filter(None, [category, merchant, description])).lower()


def is_bank_fee(
    category: str | None = None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    cat = (category or "").strip().lower()
    if "bank charge" in cat or cat == "bank fees":
        return True
    text = _text_blob(category, merchant_name, description)
    return any(marker in text for marker in FEE_TEXT_MARKERS)


def is_reversal(
    category: str | None = None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    cat = (category or "").strip().lower()
    if cat == "reversal":
        return True
    text = _text_blob(category, merchant_name, description)
    return any(marker in text for marker in REVERSAL_MARKERS)


def detect_posting_kind(txn: dict) -> PostingKind:
    """Classify transaction into a Books posting bucket."""
    intent = txn.get("posting_intent")
    if intent == "expense":
        return "expense"
    if intent == "income":
        return "income"
    if intent == "fee":
        return "fee"
    if intent in ("transfer", "personal"):
        return "transfer"

    category = txn.get("category")
    merchant = txn.get("merchant_name")
    description = txn.get("description")
    txn_type = txn.get("transaction_type")

    if is_reversal(category, merchant, description):
        return "reversal"

    if is_bank_fee(category, merchant, description):
        return "fee"

    if txn_type == "credit":
        if is_transfer(category, merchant, description):
            return "transfer"
        return "income"

    if is_transfer(category, merchant, description):
        return "transfer"

    return "expense"


def posting_type_for_kind(kind: PostingKind) -> PostingType:
    if kind == "income":
        return "deposit"
    if kind == "fee":
        return "fee"
    if kind == "transfer":
        return "transfer"
    if kind == "reversal":
        return "skip"
    return "expense"


def default_fee_account_names() -> tuple[str, ...]:
    return (
        "Bank Charges",
        "Bank Fees",
        "Bank Service Charges",
        "Bank charges",
    )
