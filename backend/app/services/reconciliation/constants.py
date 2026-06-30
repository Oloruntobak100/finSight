"""Bank reconciliation module constants and types."""

from __future__ import annotations

from typing import Literal

RunStatus = Literal["DRAFT", "IN_REVIEW", "ADJUSTED", "APPROVED", "LOCKED"]

ItemSource = Literal["MONO", "QBO", "BOTH"]

MatchStatus = Literal[
    "MATCHED_EXACT",
    "MATCHED_FUZZY",
    "SUGGESTED",
    "AMOUNT_MATCH_SUGGESTED",
    "AMBIGUOUS_MATCH",
    "DEPOSITS_IN_TRANSIT",
    "OUTSTANDING_PAYMENT",
    "UNRECORDED_BANK_CREDIT",
    "UNRECORDED_BANK_CHARGE",
    "TIMING_DIFFERENCE",
    "UNEXPLAINED",
    "PRIOR_PERIOD_CARRY",
    "DUPLICATE_ENTRY",
    "DATA_ENTRY_ERROR",
    "FLAG_FOR_REVIEW",
]

AdjustmentType = Literal[
    "DEPOSIT_IN_TRANSIT",
    "OUTSTANDING_PAYMENT",
    "BANK_CHARGE",
    "BANK_INTEREST",
    "NSF_RETURN",
    "BOOK_ERROR",
    "BANK_ERROR",
    "FRAUD_FLAG",
]

OutstandingType = Literal["DEPOSIT_IN_TRANSIT", "OUTSTANDING_PAYMENT"]
OutstandingStatus = Literal["OPEN", "CLEARED", "VOIDED"]

AUTO_MATCH_THRESHOLD = 0.90
SUGGESTED_MATCH_THRESHOLD = 0.65

MATCH_STATUSES_MATCHED = frozenset({"MATCHED_EXACT", "MATCHED_FUZZY"})
MATCH_STATUSES_EXCEPTION = frozenset(
    {
        "UNEXPLAINED",
        "FLAG_FOR_REVIEW",
        "UNRECORDED_BANK_CHARGE",
        "UNRECORDED_BANK_CREDIT",
        "DUPLICATE_ENTRY",
        "DATA_ENTRY_ERROR",
    }
)

BANK_SIDE_STATUSES = frozenset(
    {
        "DEPOSITS_IN_TRANSIT",
        "OUTSTANDING_PAYMENT",
        "TIMING_DIFFERENCE",
        "PRIOR_PERIOD_CARRY",
    }
)

BOOK_SIDE_STATUSES = frozenset(
    {
        "UNRECORDED_BANK_CHARGE",
        "UNRECORDED_BANK_CREDIT",
        "OUTSTANDING_PAYMENT",
        "DATA_ENTRY_ERROR",
    }
)

RUN_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"IN_REVIEW"},
    "IN_REVIEW": {"DRAFT", "ADJUSTED"},
    "ADJUSTED": {"IN_REVIEW", "APPROVED"},
    "APPROVED": {"ADJUSTED", "LOCKED"},
    "LOCKED": set(),
}
