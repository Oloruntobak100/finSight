"""Tests for QuickBooks disconnect/reconnect continuity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_exchange_code_reactivates_disconnected_realm_row():
    disconnected = {
        "id": "qb-acct-1",
        "user_id": "user-1",
        "realm_id": "realm-99",
        "status": "disconnected",
    }
    updated = {**disconnected, "status": "active", "account_name": "Sandbox Co"}

    with patch(
        "app.services.quickbooks_service.settings",
    ) as mock_settings, patch(
        "app.services.quickbooks_service._exchange_tokens",
        AsyncMock(return_value={"access_token": "a", "refresh_token": "r", "expires_in": 3600}),
    ), patch(
        "app.services.quickbooks_service._fetch_company_name",
        AsyncMock(return_value="Sandbox Co"),
    ), patch(
        "app.services.quickbooks_service.find_qb_account_by_realm",
        AsyncMock(return_value=disconnected),
    ), patch(
        "app.services.quickbooks_service._get_quickbooks_account_row",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.quickbooks_service.sync_chart_of_accounts",
        AsyncMock(return_value={"synced": 5, "removed": 0}),
    ), patch(
        "app.services.quickbooks_service.get_supabase",
    ), patch(
        "app.services.quickbooks_service.run_db",
        new=AsyncMock(
            side_effect=[
                MagicMock(data=[updated]),
                None,
            ]
        ),
    ):
        mock_settings.quickbooks_client_id = "id"
        mock_settings.quickbooks_client_secret = "secret"
        from app.services.quickbooks_service import exchange_code

        account = await exchange_code("user-1", "auth-code", "realm-99")

    assert account["id"] == "qb-acct-1"
    assert account["status"] == "active"


@pytest.mark.asyncio
async def test_disconnect_soft_revokes_without_deleting():
    account = {"id": "qb-acct-1", "realm_id": "realm-99", "refresh_token_encrypted": "enc"}

    with patch(
        "app.services.quickbooks_service.get_supabase",
    ), patch(
        "app.services.quickbooks_service.run_db",
        new=AsyncMock(
            side_effect=[
                MagicMock(data=account),
                None,
                None,
            ]
        ),
    ), patch(
        "app.services.quickbooks_service.decrypt_token",
        return_value="token",
    ), patch(
        "app.services.quickbooks_service.httpx.AsyncClient",
    ) as client_cls:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = None
        client.post = AsyncMock()
        client_cls.return_value = client

        from app.services.quickbooks_service import disconnect

        await disconnect("user-1", "qb-acct-1")

    assert client.post.await_count == 1


@pytest.mark.asyncio
async def test_exchange_code_soft_disconnects_other_active_realm():
    active_other = {"id": "qb-old", "realm_id": "realm-old", "status": "active"}

    with patch(
        "app.services.quickbooks_service.settings",
    ) as mock_settings, patch(
        "app.services.quickbooks_service._exchange_tokens",
        AsyncMock(return_value={"access_token": "a", "refresh_token": "r", "expires_in": 3600}),
    ), patch(
        "app.services.quickbooks_service._fetch_company_name",
        AsyncMock(return_value="New Co"),
    ), patch(
        "app.services.quickbooks_service.find_qb_account_by_realm",
        AsyncMock(return_value=None),
    ), patch(
        "app.services.quickbooks_service._get_quickbooks_account_row",
        AsyncMock(return_value=active_other),
    ), patch(
        "app.services.quickbooks_service.soft_disconnect_quickbooks",
        AsyncMock(),
    ) as soft_disconnect, patch(
        "app.services.quickbooks_service.sync_chart_of_accounts",
        AsyncMock(return_value={"synced": 1, "removed": 0}),
    ), patch(
        "app.services.quickbooks_service.get_supabase",
    ), patch(
        "app.services.quickbooks_service.run_db",
        new=AsyncMock(
            side_effect=[
                MagicMock(data=[{"id": "qb-new", "realm_id": "realm-new", "status": "active"}]),
                None,
            ]
        ),
    ):
        mock_settings.quickbooks_client_id = "id"
        mock_settings.quickbooks_client_secret = "secret"
        from app.services.quickbooks_service import exchange_code

        await exchange_code("user-1", "auth-code", "realm-new")

    soft_disconnect.assert_awaited_once_with("user-1", "qb-old")
