"""Tests for reconciliation workflow state machine."""

from app.services.reconciliation.constants import RUN_TRANSITIONS


def test_draft_to_in_review():
    assert "IN_REVIEW" in RUN_TRANSITIONS["DRAFT"]


def test_locked_has_no_transitions():
    assert RUN_TRANSITIONS["LOCKED"] == set()


def test_approved_can_lock():
    assert "LOCKED" in RUN_TRANSITIONS["APPROVED"]


def test_in_review_can_adjust():
    assert "ADJUSTED" in RUN_TRANSITIONS["IN_REVIEW"]


def test_adjusted_requires_approval_path():
    assert "APPROVED" in RUN_TRANSITIONS["ADJUSTED"]
