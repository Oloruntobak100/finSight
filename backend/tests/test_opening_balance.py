"""Tests for opening balance onboarding."""

import pytest

from app.services import opening_balance_service


@pytest.mark.asyncio
async def test_post_opening_balance_rejects_non_positive_amount():
    with pytest.raises(ValueError, match="positive"):
        await opening_balance_service.post_opening_balance(
            "user-1", "acct-1", amount=0, as_of_date="2025-01-01"
        )


@pytest.mark.asyncio
async def test_post_opening_balance_requires_bank_mapping(monkeypatch):
    async def fake_mappings(_user_id: str):
        return []

    async def fake_fetch(_user_id: str, _account_id: str):
        return None

    monkeypatch.setattr(opening_balance_service, "get_mappings", fake_mappings)
    monkeypatch.setattr(opening_balance_service, "fetch_bank_account", fake_fetch)

    with pytest.raises(ValueError, match="Map this bank"):
        await opening_balance_service.post_opening_balance(
            "user-1", "acct-1", amount=1000, as_of_date="2025-01-01"
        )
