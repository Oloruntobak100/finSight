"""Tests for identity-based reconciliation matching."""

from app.services.reconciliation.identity_matching import (
    has_identity_discriminator,
    is_ambiguous_auto_match,
    parse_finsight_transaction_id,
)
from app.services.reconciliation.scoring import AUTO_MATCH_THRESHOLD


def test_parse_finsight_transaction_id_from_private_note():
    txn_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    note = f"FinSight:{txn_id}"
    assert parse_finsight_transaction_id(note) == txn_id


def test_parse_finsight_transaction_id_embedded_in_text():
    txn_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert parse_finsight_transaction_id(f"Posted via FinSight:{txn_id} batch") == txn_id


def test_has_identity_discriminator_finsight_uuid():
    mono = {"mono_transaction_id": "abc-123", "reference": ""}
    qbo = {"finsight_transaction_id": "abc-123", "qb_entity_id": "99", "reference": ""}
    assert has_identity_discriminator(mono, qbo) is True


def test_has_identity_discriminator_bank_ref():
    mono = {"mono_transaction_id": "abc", "reference": "NIP-001", "qb_entity_id": None}
    qbo = {"finsight_transaction_id": None, "qb_entity_id": "99", "reference": "nip-001"}
    assert has_identity_discriminator(mono, qbo) is True


def test_is_ambiguous_when_duplicate_high_scores_without_discriminator():
    mono = {"mono_transaction_id": "m1", "reference": "", "qb_entity_id": None}
    qbo_a = {"qbo_entity_id": "1", "reference": ""}
    qbo_b = {"qbo_entity_id": "2", "reference": ""}
    score = AUTO_MATCH_THRESHOLD + 0.01
    assert (
        is_ambiguous_auto_match(
            scored_candidates=[(score, qbo_a), (score, qbo_b)],
            mono=mono,
            best_qbo=qbo_a,
            best_score=score,
        )
        is True
    )


def test_is_not_ambiguous_with_finsight_discriminator():
    txn_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    mono = {"mono_transaction_id": txn_id, "reference": ""}
    qbo_a = {"qbo_entity_id": "1", "finsight_transaction_id": txn_id, "reference": ""}
    qbo_b = {"qbo_entity_id": "2", "reference": ""}
    score = AUTO_MATCH_THRESHOLD + 0.01
    assert (
        is_ambiguous_auto_match(
            scored_candidates=[(score, qbo_a), (score, qbo_b)],
            mono=mono,
            best_qbo=qbo_a,
            best_score=score,
        )
        is False
    )
