"""Tests for bank provider registry."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.bank_providers import (
    MonoBankProvider,
    PlaidBankProvider,
    disconnect_bank_account,
    get_bank_provider,
    should_skip_sync,
    sync_bank_account,
)


def test_get_bank_provider_known():
    assert get_bank_provider("mono").provider_id == "mono"
    assert get_bank_provider("plaid").provider_id == "plaid"


def test_get_bank_provider_unknown():
    with pytest.raises(ValueError, match="Unsupported"):
        get_bank_provider("unknown")


@pytest.mark.asyncio
async def test_sync_bank_account_delegates_to_mono():
    with patch(
        "app.services.bank_providers.should_skip_sync",
        return_value=False,
    ), patch(
        "app.services.mono_service.sync_mono_transactions",
        AsyncMock(return_value=12),
    ) as sync:
        count = await sync_bank_account("user-1", "acct-1", "mono")
    assert count == 12
    sync.assert_awaited_once_with("user-1", "acct-1")


@pytest.mark.asyncio
async def test_disconnect_bank_account_delegates_to_plaid():
    with patch(
        "app.services.plaid_service.disconnect_plaid_account",
        AsyncMock(),
    ) as disconnect:
        await disconnect_bank_account("user-1", "acct-1", "plaid")
    disconnect.assert_awaited_once_with("user-1", "acct-1")


def test_provider_classes_expose_id():
    assert MonoBankProvider().provider_id == "mono"
    assert PlaidBankProvider().provider_id == "plaid"


def test_should_skip_sync_respects_settings():
    with patch("app.services.bank_providers.settings") as mock_settings:
        mock_settings.skip_mono_sandbox_sync = True
        assert should_skip_sync("mono") is True
        assert should_skip_sync("plaid") is False
