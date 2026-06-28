"""Classify transfer vs real spend/income transactions."""

from __future__ import annotations

import pandas as pd

# Explicit FinSight / Mono categories reserved for account-to-account movement.
TRANSFER_CATEGORIES = frozenset(
    {
        "transfer",
        "transfer in",
        "transfer out",
    }
)

# Narration markers for moving money between the user's own accounts (Non-P&L).
INTERNAL_TRANSFER_MARKERS = (
    "to self",
    "own account",
    "between own accounts",
    "between my accounts",
    "inter account",
    "inter-account",
    "self transfer",
    "transfer to self",
    "transfer from self",
)


def is_transfer(
    category: str | None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    """True only for inter-account movement, not routine NIP payments to third parties."""
    cat = (category or "").strip().lower().replace("_", " ")
    if cat in TRANSFER_CATEGORIES:
        return True

    text = " ".join(filter(None, [merchant_name, description])).lower()
    if not text:
        return False

    return any(marker in text for marker in INTERNAL_TRANSFER_MARKERS)


def mark_transfers_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df = df.copy()
        df["is_transfer"] = False
        return df

    out = df.copy()
    out["is_transfer"] = out.apply(
        lambda r: is_transfer(
            r.get("category"),
            r.get("merchant_name"),
            r.get("description"),
        ),
        axis=1,
    )
    return out


def split_spend_income(df: pd.DataFrame, include_transfers: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (transfers_df, real_debits, real_credits)."""
    if df.empty:
        empty = df.copy()
        return empty, empty, empty

    marked = mark_transfers_df(df)
    transfers = marked[marked["is_transfer"]]
    non_transfers = marked[~marked["is_transfer"]]

    if include_transfers:
        debits = marked[marked["transaction_type"] == "debit"]
        credits = marked[marked["transaction_type"] == "credit"]
    else:
        debits = non_transfers[non_transfers["transaction_type"] == "debit"]
        credits = non_transfers[non_transfers["transaction_type"] == "credit"]

    return transfers, debits, credits
