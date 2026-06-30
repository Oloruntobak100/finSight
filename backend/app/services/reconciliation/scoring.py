"""Weighted match scoring for transaction matching."""

from __future__ import annotations

from datetime import datetime, timezone
from difflib import SequenceMatcher

from app.services.qb_party_service import normalize_party_lookup
from app.services.reconciliation.constants import (
    AUTO_MATCH_THRESHOLD,
    SUGGESTED_MATCH_THRESHOLD,
)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def amount_score(a: float, b: float, tolerance_pct: float = 0.01) -> float:
    a, b = abs(a), abs(b)
    if a == 0 and b == 0:
        return 1.0
    if max(a, b) == 0:
        return 0.0
    diff_pct = abs(a - b) / max(a, b)
    if diff_pct <= tolerance_pct:
        return 1.0
    if diff_pct <= 0.05:
        return 0.7
    return 0.0


def date_proximity_score(date_a: str | None, date_b: str | None, max_days: int = 1) -> float:
    da = _parse_date(date_a)
    db = _parse_date(date_b)
    if not da or not db:
        return 0.0
    days = abs((da - db).days)
    if days == 0:
        return 1.0
    if days == 1:
        return 0.85
    if days <= max_days:
        return max(0.0, 1.0 - (days / (max_days + 1)))
    return 0.0


def payee_similarity_score(payee_a: str | None, payee_b: str | None) -> float:
    a = normalize_party_lookup(payee_a or "")
    b = normalize_party_lookup(payee_b or "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def reference_match_score(ref_a: str | None, ref_b: str | None) -> float:
    a = (ref_a or "").strip().lower()
    b = (ref_b or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return 0.0


def compute_match_score(
    *,
    amount_a: float,
    amount_b: float,
    date_a: str | None,
    date_b: str | None,
    payee_a: str | None = None,
    payee_b: str | None = None,
    ref_a: str | None = None,
    ref_b: str | None = None,
    max_date_days: int = 1,
) -> float:
    score = (
        amount_score(amount_a, amount_b) * 0.40
        + date_proximity_score(date_a, date_b, max_days=max_date_days) * 0.25
        + payee_similarity_score(payee_a, payee_b) * 0.20
        + reference_match_score(ref_a, ref_b) * 0.15
    )
    return round(min(1.0, max(0.0, score)), 4)


def is_amount_only_match(
    amount_a: float,
    amount_b: float,
    date_a: str | None,
    date_b: str | None,
) -> bool:
    """Tier 3: same amount but dates more than max fuzzy window apart."""
    if amount_score(amount_a, amount_b) < 1.0:
        return False
    return date_proximity_score(date_a, date_b, max_days=1) == 0.0


def classify_score(score: float) -> str:
    if score >= AUTO_MATCH_THRESHOLD:
        return "MATCHED_FUZZY"
    if score >= SUGGESTED_MATCH_THRESHOLD:
        return "SUGGESTED"
    return "UNEXPLAINED"


def is_nip_timing_difference(qbo_date: str | None, mono_date: str | None) -> bool:
    """NIP/NIBSS: QBO same day, Mono next business day."""
    dq = _parse_date(qbo_date)
    dm = _parse_date(mono_date)
    if not dq or not dm:
        return False
    delta = (dm - dq).days
    return delta in (0, 1)
