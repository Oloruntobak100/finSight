"""Detect how a bank transaction should post to QuickBooks."""

from __future__ import annotations

import re
from typing import Literal

from app.services.transfer_utils import is_transfer

PostingKind = Literal[
    "expense", "income", "transfer", "fee", "reversal", "balance_sheet", "refund"
]
PostingType = Literal["expense", "deposit", "fee", "transfer", "skip", "refund"]

# Mono metadata slugs that are balance-sheet movements, not P&L
MONO_BALANCE_SHEET_SLUGS = frozenset(
    {
        "loan",
        "loan_repayment",
        "savings",
        "investment_payout",
        "investment_deposit",
        "cash_deposit",
        "cheque_deposits",
        "cheque",
    }
)

# Human-readable FinSight categories (from MONO_CATEGORY_LABELS)
BALANCE_SHEET_CATEGORIES = frozenset(
    {
        "loans",
        "loan repayment",
        "savings",
        "investment payout",
        "investment deposit",
        "cash deposit",
        "cheque deposits",
        "cheque",
    }
)

EQUITY_TEXT_MARKERS = (
    "owner capital",
    "owner's capital",
    "capital injection",
    "equity injection",
    "owner draw",
    "owners draw",
    "shareholder loan",
    "director loan",
)

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

REFUND_TEXT_MARKERS = (
    "refund",
    "reimbursement",
    "reimbursed",
    "chargeback",
    "charge back",
    "returned payment",
    "payment returned",
    "rvsl cr",
    "credit reversal",
)


def _text_blob(category: str | None, merchant: str | None, description: str | None) -> str:
    return " ".join(filter(None, [category, merchant, description])).lower()


def _mono_category_slug(txn: dict) -> str | None:
    raw = txn.get("raw_metadata") or {}
    if not isinstance(raw, dict):
        return None
    metadata = raw.get("metadata") or {}
    slug = metadata.get("category") or raw.get("category")
    if not slug or not isinstance(slug, str):
        return None
    normalized = slug.strip().lower()
    if normalized in ("unknown", "null", "none", "n/a", "uncategorized"):
        return None
    return normalized


def is_balance_sheet_movement(
    txn: dict,
    *,
    category: str | None = None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    slug = _mono_category_slug(txn)
    if slug and slug in MONO_BALANCE_SHEET_SLUGS:
        return True

    cat = (category or txn.get("category") or "").strip().lower()
    if cat in BALANCE_SHEET_CATEGORIES:
        return True

    text = _text_blob(category or txn.get("category"), merchant_name, description)
    return any(marker in text for marker in EQUITY_TEXT_MARKERS)


def is_vendor_refund(
    category: str | None = None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    text = _text_blob(category, merchant_name, description)
    if not text:
        return False
    if any(marker in text for marker in REFUND_TEXT_MARKERS):
        return True
    if re.search(r"\bref\b.*\bcr\b", text):
        return True
    return False


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


def posting_kind_to_intent(kind: PostingKind) -> str:
    """Map posting kind to persisted posting_intent / fingerprint value."""
    if kind == "income":
        return "income"
    if kind == "fee":
        return "fee"
    if kind in ("transfer", "reversal", "balance_sheet"):
        return "transfer"
    if kind == "refund":
        return "expense"
    return "expense"


def intent_to_posting_kind(intent: str | None) -> PostingKind | None:
    if intent == "expense":
        return "expense"
    if intent == "income":
        return "income"
    if intent == "fee":
        return "fee"
    if intent in ("transfer", "personal"):
        return "transfer"
    return None


def detect_posting_kind(
    txn: dict,
    *,
    learned_kind: PostingKind | None = None,
) -> PostingKind:
    """Classify transaction into a Books posting bucket."""
    taught = intent_to_posting_kind(txn.get("posting_intent"))
    if taught:
        return taught

    if learned_kind:
        return learned_kind

    category = txn.get("category")
    merchant = txn.get("merchant_name")
    description = txn.get("description")
    txn_type = txn.get("transaction_type")

    if is_reversal(category, merchant, description):
        return "reversal"

    if is_bank_fee(category, merchant, description):
        return "fee"

    if is_balance_sheet_movement(txn, category=category, merchant_name=merchant, description=description):
        return "balance_sheet"

    if txn_type == "credit" and is_vendor_refund(category, merchant, description):
        return "refund"

    if txn_type == "credit":
        if is_transfer(category, merchant, description):
            return "transfer"
        return "income"

    if is_transfer(category, merchant, description):
        return "transfer"

    return "expense"


def posting_kind_for_coa_account(
    account_type: str | None,
    *,
    transaction_type: str | None = None,
) -> PostingKind:
    """Infer posting kind when the user picks a QuickBooks account directly."""
    at = (account_type or "").strip().lower()
    if at == "income":
        return "income"
    if at in ("expense", "other expense", "cost of goods sold"):
        return "expense"
    if transaction_type == "credit":
        return "income"
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
    if kind == "balance_sheet":
        return "skip"
    if kind == "refund":
        return "refund"
    return "expense"


def default_fee_account_names() -> tuple[str, ...]:
    return (
        "Bank Charges",
        "Bank Fees",
        "Bank Service Charges",
        "Bank charges",
    )
