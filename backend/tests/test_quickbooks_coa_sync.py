"""Tests for QuickBooks chart-of-accounts sync stale purge."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.quickbooks_service import _purge_stale_coa, sync_chart_of_accounts


def _chainable_table(*, select_data=None):
    table = MagicMock()
    chain = MagicMock()
    chain.eq.return_value = chain
    chain.neq.return_value = chain
    chain.in_.return_value = chain
    chain.execute.return_value = MagicMock(data=select_data or [])
    table.delete.return_value = chain
    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.execute.return_value = MagicMock(data=select_data or [])
    table.select.return_value = select_chain
    return table


@pytest.mark.asyncio
async def test_purge_stale_coa_removes_missing_accounts_and_mappings():
    coa_table = _chainable_table(
        select_data=[
            {"qb_account_id": "1"},
            {"qb_account_id": "2"},
            {"qb_account_id": "99"},
        ]
    )
    mappings_table = _chainable_table()
    sb = MagicMock()
    sb.table.side_effect = lambda name: coa_table if name == "qb_chart_of_accounts" else mappings_table

    async def fake_run_db(fn):
        return fn()

    with patch("app.services.quickbooks_service.get_supabase", return_value=sb), patch(
        "app.services.quickbooks_service.run_db",
        side_effect=fake_run_db,
    ):
        removed = await _purge_stale_coa("user-1", "realm-1", {"1", "2"})

    assert removed == 1
    mappings_table.delete.return_value.in_.assert_called_once_with("qb_account_id", ["99"])
    coa_table.delete.return_value.in_.assert_called_once_with("qb_account_id", ["99"])


@pytest.mark.asyncio
async def test_sync_chart_of_accounts_purges_stale_after_upsert():
    qb_accounts = [
        {"Id": "10", "Name": "Access Bank", "AccountType": "Bank", "Active": True},
        {"Id": "11", "Name": "GT Bank", "AccountType": "Bank", "Active": True},
    ]

    with patch(
        "app.services.quickbooks_service.get_valid_account",
        AsyncMock(return_value={"realm_id": "realm-1"}),
    ), patch(
        "app.services.quickbooks_service.qb_query",
        AsyncMock(return_value={"QueryResponse": {"Account": qb_accounts}}),
    ), patch(
        "app.services.quickbooks_service.get_supabase",
        return_value=MagicMock(),
    ), patch(
        "app.services.quickbooks_service.run_db",
        new=AsyncMock(return_value=MagicMock(data=[])),
    ), patch(
        "app.services.quickbooks_service._purge_stale_coa",
        AsyncMock(return_value=2),
    ) as purge:
        result = await sync_chart_of_accounts("user-1")

    assert result["synced"] == 2
    assert result["removed"] == 2
    purge.assert_awaited_once_with("user-1", "realm-1", {"10", "11"})


@pytest.mark.asyncio
async def test_ensure_coa_synced_always_pulls_from_quickbooks():
    with patch(
        "app.services.books_service.sync_chart_of_accounts",
        AsyncMock(return_value={"synced": 39, "removed": 0, "realm_id": "realm-1"}),
    ) as sync:
        from app.services.books_service import ensure_coa_synced

        result = await ensure_coa_synced("user-1")

    sync.assert_awaited_once_with("user-1")
    assert result["synced"] == 39
