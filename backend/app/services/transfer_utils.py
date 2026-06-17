"""Classify transfer vs real spend/income transactions."""

from __future__ import annotations

import re

import pandas as pd

TRANSFER_CATEGORY_MARKERS = (
    "transfer",
    "transfer in",
    "transfer out",
    "transfer_in",
    "transfer_out",
)


def is_transfer(
    category: str | None,
    merchant_name: str | None = None,
    description: str | None = None,
) -> bool:
    cat = (category or "").strip().lower().replace("_", " ")
    if any(marker in cat for marker in TRANSFER_CATEGORY_MARKERS):
        return True

    text = " ".join(filter(None, [merchant_name, description])).lower()
    if not text:
        return False

    if re.search(r"\bnip[/\s]", text) or text.startswith("nip/"):
        return True
    if re.search(r"\b(transfer|trf)\b", text) and "/" in text:
        return True
    return False


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
