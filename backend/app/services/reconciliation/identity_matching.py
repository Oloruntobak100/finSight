"""Deterministic identity keys for bank ↔ books matching."""

from __future__ import annotations

import re
from typing import Any

from app.services.reconciliation.scoring import AUTO_MATCH_THRESHOLD, amount_score, reference_match_score

FINSIGHT_NOTE_PREFIX = "FinSight:"
_FINSIGHT_ID_RE = re.compile(
    rf"{re.escape(FINSIGHT_NOTE_PREFIX)}([0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}})",
    re.IGNORECASE,
)

# Minimum score gap required to auto-match when multiple fuzzy candidates qualify.
AMBIGUITY_SCORE_MARGIN = 0.05


def parse_finsight_transaction_id(text: str | None) -> str | None:
    """Extract FinSight transaction UUID from QBO PrivateNote / narration."""
    if not text:
        return None
    match = _FINSIGHT_ID_RE.search(str(text))
    return match.group(1).lower() if match else None


def exact_reference_match(ref_a: str | None, ref_b: str | None) -> bool:
    return reference_match_score(ref_a, ref_b) == 1.0


def amounts_match(mono: dict[str, Any], qbo: dict[str, Any]) -> bool:
    return amount_score(float(mono.get("amount") or 0), float(qbo.get("amount") or 0)) >= 1.0


def transaction_dates_match(mono: dict[str, Any], qbo: dict[str, Any]) -> bool:
    mono_date = str(mono.get("transaction_date") or "")[:10]
    qbo_date = str(qbo.get("transaction_date") or "")[:10]
    return bool(mono_date and qbo_date and mono_date == qbo_date)


def has_identity_discriminator(mono: dict[str, Any], qbo: dict[str, Any]) -> bool:
    """True when an explicit id/ref ties this pair apart from lookalikes."""
    mid = str(mono.get("mono_transaction_id") or "").lower()
    fid = str(qbo.get("finsight_transaction_id") or "").lower()
    if mid and fid and mid == fid:
        return True
    entity_id = mono.get("qb_entity_id")
    if entity_id and str(entity_id) == str(qbo.get("qbo_entity_id") or ""):
        return True
    return exact_reference_match(mono.get("reference"), qbo.get("reference"))


def is_ambiguous_auto_match(
    *,
    scored_candidates: list[tuple[float, dict[str, Any]]],
    mono: dict[str, Any],
    best_qbo: dict[str, Any],
    best_score: float,
) -> bool:
    """True when fuzzy auto-match would be unsafe due to duplicate lookalikes."""
    if best_score < AUTO_MATCH_THRESHOLD:
        return False
    if has_identity_discriminator(mono, best_qbo):
        return False
    strong = [score for score, _ in scored_candidates if score >= AUTO_MATCH_THRESHOLD]
    if len(strong) < 2:
        return False
    strong.sort(reverse=True)
    return (strong[0] - strong[1]) < AMBIGUITY_SCORE_MARGIN
