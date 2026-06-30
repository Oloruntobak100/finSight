"""Tests for bank account disconnect/reconnect lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.bank_account_lifecycle import (
    bank_mapping_keys,
    bank_mapping_lookup,
    connect_or_reactivate_bank_account,
)


def test_bank_mapping_keys_prefers_account_id_then_external():
    assert bank_mapping_keys("uuid-1", "mono-ext-1") == ["uuid-1", "mono-ext-1"]
    assert bank_mapping_keys("uuid-1", "uuid-1") == ["uuid-1"]


def test_bank_mapping_lookup_falls_back_to_external_key():
    mappings = [
        {
            "mapping_type": "bank_account",
            "finsight_key": "mono-ext-1",
            "qb_account_id": "qb-99",
        }
    ]
    found = bank_mapping_lookup(mappings, "new-uuid", "mono-ext-1")
    assert found is not None
    assert found["qb_account_id"] == "qb-99"


@pytest.mark.asyncio
async def test_connect_or_reactivate_reuses_existing_row():
    existing = {"id": "acct-1", "external_account_id": "mono-1"}
    updated_row = {**existing, "status": "active", "account_name": "Main"}
    fetch_res = MagicMock()
    fetch_res.data = updated_row

    with patch(
        "app.services.bank_account_lifecycle.find_bank_account_by_external_id",
        AsyncMock(return_value=existing),
    ), patch(
        "app.services.bank_account_lifecycle.restore_bank_account_continuity",
        AsyncMock(
            return_value={
                "unarchived": 5,
                "orphaned_unarchived": 0,
                "reconciliation_runs_relinked": 1,
            }
        ),
    ) as restore, patch(
        "app.services.bank_account_lifecycle.get_supabase",
    ), patch(
        "app.services.bank_account_lifecycle.run_db",
        new=AsyncMock(side_effect=[None, fetch_res]),
    ):
        account, reconnected = await connect_or_reactivate_bank_account(
            "user-1",
            "mono",
            "mono-1",
            account_name="Main",
            access_token_encrypted="enc",
        )

    assert reconnected is True
    assert account["id"] == "acct-1"
    restore.assert_awaited_once_with("user-1", "acct-1", "mono", "mono-1")


@pytest.mark.asyncio
async def test_relink_legacy_archived_transactions_single_active_account():
    with patch("app.services.bank_account_lifecycle.get_supabase"), patch(
        "app.services.bank_account_lifecycle.run_db",
        new=AsyncMock(
            side_effect=[
                MagicMock(data=[{"id": "new-acct", "status": "active"}]),
                MagicMock(
                    data=[
                        {"id": "t1", "account_id": "old-deleted"},
                        {"id": "t2", "account_id": None},
                    ]
                ),
                None,
            ]
        ),
    ):
        from app.services.bank_account_lifecycle import relink_legacy_archived_transactions

        count = await relink_legacy_archived_transactions("user-1", "new-acct", "mono")

    assert count == 2
