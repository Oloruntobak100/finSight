"""Tests for active-bank transaction scope."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.bank_transaction_scope import (
    apply_active_bank_scope,
    archive_detached_bank_transactions,
    count_scoped_transactions,
)


def test_apply_active_bank_scope_requires_active_account_ids():
    query = MagicMock()
    query.is_.return_value = query
    query.in_.return_value = query
    query.eq.return_value = query

    apply_active_bank_scope(query, set())

    query.eq.assert_called_with("account_id", "00000000-0000-0000-0000-000000000000")


def test_apply_active_bank_scope_filters_by_account_ids():
    query = MagicMock()
    query.is_.return_value = query
    query.in_.return_value = query

    active = {"aaa-111", "bbb-222"}
    apply_active_bank_scope(query, active)

    query.in_.assert_any_call("source_provider", list(("plaid", "mono")))
    account_calls = [c.args for c in query.in_.call_args_list if c.args[0] == "account_id"]
    assert len(account_calls) == 1
    assert set(account_calls[0][1]) == active


@pytest.mark.asyncio
async def test_count_scoped_transactions_uses_exact_count():
    mock_res = MagicMock()
    mock_res.count = 1062

    with patch("app.services.bank_transaction_scope.get_supabase") as mock_sb, patch(
        "app.services.bank_transaction_scope.run_db",
        new=AsyncMock(return_value=mock_res),
    ), patch(
        "app.services.bank_transaction_scope.apply_active_bank_scope",
        side_effect=lambda q, ids: q,
    ):
        mock_sb.return_value.table.return_value.select.return_value.eq.return_value = MagicMock()
        total = await count_scoped_transactions("user-1", {"acct-1"})

    assert total == 1062


@pytest.mark.asyncio
async def test_archive_detached_archives_orphan_and_stale_rows():
    rows = [
        {"id": "t1", "account_id": None},
        {"id": "t2", "account_id": "old-acct"},
        {"id": "t3", "account_id": "active-acct"},
    ]

    async def fake_run_db(fn):
        return fn()

    mock_res = MagicMock()
    mock_res.data = rows

    mock_query = MagicMock()
    mock_query.select.return_value = mock_query
    mock_query.eq.return_value = mock_query
    mock_query.is_.return_value = mock_query
    mock_query.in_.return_value = mock_query
    mock_query.range.return_value = mock_query
    mock_query.execute = MagicMock(return_value=mock_res)

    mock_update = MagicMock()
    mock_update.in_.return_value = mock_update
    mock_update.execute = MagicMock(return_value=MagicMock())

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value = mock_query
    mock_sb.table.return_value.update.return_value = mock_update

    with patch("app.services.bank_transaction_scope.get_supabase", return_value=mock_sb), patch(
        "app.services.bank_transaction_scope.run_db",
        side_effect=fake_run_db,
    ), patch(
        "app.services.bank_transaction_scope.get_active_bank_accounts",
        AsyncMock(return_value=([], {"active-acct"})),
    ):
        archived = await archive_detached_bank_transactions("user-1")

    assert archived == 2


@pytest.mark.asyncio
async def test_get_summary_aggregates_exact_counts():
    async def fake_count(
        user_id,
        active_bank_ids,
        *,
        qb_sync_status=None,
        unclassified=False,
        date_from=None,
        date_to=None,
    ):
        if unclassified:
            return 700
        if qb_sync_status == "needs_review":
            return 166
        if qb_sync_status == "excluded":
            return 137
        return 0

    with patch(
        "app.services.books_service._active_bank_accounts",
        AsyncMock(return_value=([], {"acct-1"})),
    ), patch(
        "app.services.books_service.count_scoped_transactions",
        side_effect=fake_count,
    ), patch(
        "app.services.books_service._count_books_queue_status",
        side_effect=lambda _uid, _ids, status, date_from=None, date_to=None: 303
        if status == "needs_review"
        else 0,
    ), patch(
        "app.services.books_service.get_user_automation",
        AsyncMock(return_value={"auto_approve_enabled": False, "auto_approve_threshold": 0.9, "digest_enabled": True}),
    ), patch(
        "app.services.books_service.get_books_readiness",
        AsyncMock(return_value={"bank_connected": True, "bank_accounts": []}),
    ):
        from app.services.books_service import get_summary

        result = await get_summary("user-1")

    assert result["coverage"]["total_bank_transactions"] == 1003
    assert result["counts"]["unclassified"] == 700
    assert result["counts"]["needs_review"] == 303


@pytest.mark.asyncio
async def test_disconnect_mono_archives_before_delete():
    with patch(
        "app.services.mono_service.archive_transactions_for_account",
        AsyncMock(return_value=42),
    ) as archive_acct, patch(
        "app.services.mono_service.archive_detached_bank_transactions",
        AsyncMock(return_value=2),
    ) as archive_detached, patch(
        "app.services.mono_service.get_supabase",
    ), patch(
        "app.services.mono_service.run_db",
        new=AsyncMock(),
    ):
        from app.services.mono_service import disconnect_mono_account

        await disconnect_mono_account("user-1", "acct-1")

    archive_acct.assert_awaited_once_with("user-1", "acct-1")
    archive_detached.assert_awaited_once_with("user-1")
