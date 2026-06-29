"""Unit tests for reconciliation scoring."""

from datetime import datetime, timezone

from app.services.reconciliation.scoring import (
    AUTO_MATCH_THRESHOLD,
    SUGGESTED_MATCH_THRESHOLD,
    amount_score,
    classify_score,
    compute_match_score,
    date_proximity_score,
    is_nip_timing_difference,
    payee_similarity_score,
    reference_match_score,
)


def test_amount_score_exact():
    assert amount_score(1000, 1000) == 1.0


def test_amount_score_within_tolerance():
    assert amount_score(1000, 1005) == 1.0


def test_date_proximity_same_day():
    assert date_proximity_score("2025-06-15", "2025-06-15") == 1.0


def test_date_proximity_nip_next_day():
    assert date_proximity_score("2025-06-15", "2025-06-16") == 0.85


def test_payee_similarity():
    assert payee_similarity_score("UBER TRIP", "uber trip") == 1.0


def test_reference_match():
    assert reference_match_score("REF123", "ref123") == 1.0


def test_compute_match_score_high():
    score = compute_match_score(
        amount_a=5000,
        amount_b=5000,
        date_a="2025-06-15",
        date_b="2025-06-15",
        payee_a="Payroll Services",
        payee_b="Payroll Services",
        ref_a="ABC",
        ref_b="ABC",
    )
    assert score >= AUTO_MATCH_THRESHOLD


def test_classify_score_suggested():
    assert classify_score(0.75) == "SUGGESTED"


def test_classify_score_unexplained():
    assert classify_score(0.50) == "UNEXPLAINED"


def test_nip_timing_difference():
    assert is_nip_timing_difference("2025-06-15", "2025-06-16") is True
    assert is_nip_timing_difference("2025-06-15", "2025-06-20") is False


def test_threshold_constants():
    assert AUTO_MATCH_THRESHOLD == 0.90
    assert SUGGESTED_MATCH_THRESHOLD == 0.65
