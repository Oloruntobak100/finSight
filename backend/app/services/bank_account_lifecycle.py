"""Bank account disconnect/reconnect lifecycle — preserve Supabase continuity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db

BANK_PROVIDERS = ("plaid", "mono")
OPEN_RECON_STATUSES = ("DRAFT", "IN_REVIEW", "ADJUSTED")
UNARCHIVE_BATCH = 100


def bank_mapping_keys(account_id: str, external_account_id: str | None = None) -> list[str]:
    keys: list[str] = []
    if account_id:
        keys.append(str(account_id))
    if external_account_id:
        ext = str(external_account_id)
        if ext not in keys:
            keys.append(ext)
    return keys


def bank_mapping_lookup(
    mappings: list[dict[str, Any]],
    account_id: str,
    external_account_id: str | None = None,
) -> dict[str, Any] | None:
    from app.services.books_service import _mapping_lookup

    for key in bank_mapping_keys(account_id, external_account_id):
        found = _mapping_lookup(mappings, "bank_account", key)
        if found:
            return found
    return None


async def fetch_bank_account(user_id: str, account_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


async def find_bank_account_by_external_id(
    user_id: str,
    provider: str,
    external_account_id: str,
) -> dict[str, Any] | None:
    if not external_account_id:
        return None
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("user_id", user_id)
        .eq("provider", provider)
        .eq("external_account_id", external_account_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


async def soft_disconnect_bank_account(user_id: str, account_id: str, provider: str) -> None:
    account = await fetch_bank_account(user_id, account_id)
    if not account or account.get("provider") != provider:
        raise ValueError("Bank account not found")
    sb = get_supabase()
    await run_db(
        lambda: sb.table("connected_accounts")
        .update(
            {
                "status": "disconnected",
                "access_token_encrypted": None,
            }
        )
        .eq("id", account_id)
        .eq("user_id", user_id)
        .execute()
    )
    await run_db(
        lambda: sb.table("oauth_audit_log")
        .insert(
            {
                "user_id": user_id,
                "provider": provider,
                "event": "revoked",
                "metadata": {"account_id": account_id, "soft_disconnect": True},
            }
        )
        .execute()
    )


async def _clear_archived_at(user_id: str, ids: list[str]) -> int:
    if not ids:
        return 0
    sb = get_supabase()
    await run_db(
        lambda: sb.table("transactions")
        .update({"archived_at": None})
        .eq("user_id", user_id)
        .in_("id", ids)
        .execute()
    )
    return len(ids)


async def unarchive_transactions_for_account(user_id: str, account_id: str) -> int:
    sb = get_supabase()
    total = 0
    while True:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("id")
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .not_.is_("archived_at", "null")
            .limit(UNARCHIVE_BATCH)
            .execute()
        )
        ids = [row["id"] for row in (res.data or []) if row.get("id")]
        if not ids:
            break
        total += await _clear_archived_at(user_id, ids)
        if len(ids) < UNARCHIVE_BATCH:
            break
    return total


async def unarchive_orphaned_bank_transactions(
    user_id: str, account_id: str, provider: str
) -> int:
    """Relink and unarchive bank rows detached by legacy hard-delete (account_id IS NULL)."""
    sb = get_supabase()
    total = 0
    while True:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("id")
            .eq("user_id", user_id)
            .eq("source_provider", provider)
            .is_("account_id", "null")
            .not_.is_("archived_at", "null")
            .limit(UNARCHIVE_BATCH)
            .execute()
        )
        ids = [row["id"] for row in (res.data or []) if row.get("id")]
        if not ids:
            break
        await run_db(
            lambda: sb.table("transactions")
            .update({"account_id": account_id, "archived_at": None})
            .eq("user_id", user_id)
            .in_("id", ids)
            .execute()
        )
        total += len(ids)
        if len(ids) < UNARCHIVE_BATCH:
            break
    return total


async def relink_legacy_archived_transactions(
    user_id: str,
    account_id: str,
    provider: str,
) -> int:
    """Relink archived bank txs from deleted/disconnected account rows to the current one."""
    sb = get_supabase()
    conn_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, status")
        .eq("user_id", user_id)
        .eq("provider", provider)
        .execute()
    )
    connected_rows = conn_res.data or []
    active_same_provider = [
        r for r in connected_rows if r.get("status") == "active"
    ]
    if len(active_same_provider) != 1 or active_same_provider[0]["id"] != account_id:
        return 0

    all_connected_ids = {r["id"] for r in connected_rows}
    total = 0
    while True:
        res = await run_db(
            lambda: sb.table("transactions")
            .select("id, account_id")
            .eq("user_id", user_id)
            .eq("source_provider", provider)
            .not_.is_("archived_at", "null")
            .limit(UNARCHIVE_BATCH)
            .execute()
        )
        batch = res.data or []
        if not batch:
            break
        relink_ids: list[str] = []
        for row in batch:
            tid = row.get("id")
            old_account_id = row.get("account_id")
            if not tid:
                continue
            if old_account_id == account_id:
                relink_ids.append(tid)
            elif old_account_id is None:
                relink_ids.append(tid)
            elif old_account_id not in all_connected_ids:
                relink_ids.append(tid)
            else:
                old_row = next(
                    (r for r in connected_rows if r["id"] == old_account_id),
                    None,
                )
                if old_row and old_row.get("status") == "disconnected":
                    relink_ids.append(tid)
        if not relink_ids:
            break
        await run_db(
            lambda: sb.table("transactions")
            .update({"account_id": account_id, "archived_at": None})
            .eq("user_id", user_id)
            .in_("id", relink_ids)
            .execute()
        )
        total += len(relink_ids)
        if len(batch) < UNARCHIVE_BATCH:
            break
    return total


async def relink_open_reconciliation(user_id: str, account_id: str, provider: str) -> int:
    if provider != "mono":
        return 0
    account = await fetch_bank_account(user_id, account_id)
    if not account:
        return 0
    from app.services.books_service import get_mappings

    mappings = await get_mappings(user_id)
    bank_map = bank_mapping_lookup(
        mappings, account_id, account.get("external_account_id")
    )
    if not bank_map:
        return 0
    qb_id = bank_map.get("qb_account_id")
    if not qb_id:
        return 0

    sb = get_supabase()
    runs_res = await run_db(
        lambda: sb.table("reconciliation_runs")
        .update({"mono_account_id": account_id, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("user_id", user_id)
        .is_("mono_account_id", "null")
        .eq("qb_bank_account_id", qb_id)
        .in_("status", list(OPEN_RECON_STATUSES))
        .execute()
    )
    await run_db(
        lambda: sb.table("reconciliation_outstanding_items")
        .update({"mono_account_id": account_id})
        .eq("user_id", user_id)
        .is_("mono_account_id", "null")
        .eq("qb_bank_account_id", qb_id)
        .eq("status", "OPEN")
        .execute()
    )
    return len(runs_res.data or [])


async def migrate_bank_mapping_alias(
    user_id: str,
    account_id: str,
    external_account_id: str | None,
) -> None:
    """Copy bank mapping from stable external key to current account id when needed."""
    if not external_account_id or str(external_account_id) == str(account_id):
        return
    from app.services.books_service import _mapping_lookup, get_mappings

    mappings = await get_mappings(user_id)
    ext_map = _mapping_lookup(mappings, "bank_account", str(external_account_id))
    id_map = _mapping_lookup(mappings, "bank_account", str(account_id))
    if not ext_map or id_map:
        return

    sb = get_supabase()
    row = {
        "user_id": user_id,
        "mapping_type": "bank_account",
        "finsight_key": str(account_id),
        "qb_account_id": ext_map["qb_account_id"],
        "qb_account_name": ext_map.get("qb_account_name"),
        "opening_balance_amount": ext_map.get("opening_balance_amount"),
        "opening_balance_as_of": ext_map.get("opening_balance_as_of"),
        "opening_balance_qb_journal_id": ext_map.get("opening_balance_qb_journal_id"),
        "opening_balance_posted_at": ext_map.get("opening_balance_posted_at"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await run_db(
        lambda: sb.table("qb_account_mappings")
        .upsert(row, on_conflict="user_id,mapping_type,finsight_key")
        .execute()
    )


async def connect_or_reactivate_bank_account(
    user_id: str,
    provider: str,
    external_account_id: str,
    *,
    account_name: str,
    access_token_encrypted: str,
    account_type: str = "bank",
    extra_fields: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Insert or reactivate a bank account row keyed by provider external id."""
    existing = await find_bank_account_by_external_id(user_id, provider, external_account_id)
    sb = get_supabase()
    if existing:
        account_id = existing["id"]
        update: dict[str, Any] = {
            "status": "active",
            "account_name": account_name,
            "access_token_encrypted": access_token_encrypted,
            "external_account_id": external_account_id,
        }
        if extra_fields:
            update.update(extra_fields)
        await run_db(
            lambda: sb.table("connected_accounts")
            .update(update)
            .eq("id", account_id)
            .eq("user_id", user_id)
            .execute()
        )
        await restore_bank_account_continuity(
            user_id, account_id, provider, external_account_id
        )
        res = await run_db(
            lambda: sb.table("connected_accounts")
            .select("*")
            .eq("id", account_id)
            .single()
            .execute()
        )
        return res.data, True

    row: dict[str, Any] = {
        "user_id": user_id,
        "provider": provider,
        "account_name": account_name,
        "account_type": account_type,
        "access_token_encrypted": access_token_encrypted,
        "external_account_id": external_account_id,
        "status": "active",
    }
    if extra_fields:
        row.update(extra_fields)
    result = await run_db(lambda: sb.table("connected_accounts").insert(row).execute())
    account = result.data[0]
    await restore_bank_account_continuity(
        user_id, account["id"], provider, external_account_id
    )
    return account, False


async def restore_bank_account_continuity(
    user_id: str,
    account_id: str,
    provider: str,
    external_account_id: str | None,
) -> dict[str, int]:
    unarchived = await unarchive_transactions_for_account(user_id, account_id)
    orphaned = await unarchive_orphaned_bank_transactions(user_id, account_id, provider)
    legacy = await relink_legacy_archived_transactions(user_id, account_id, provider)
    await migrate_bank_mapping_alias(user_id, account_id, external_account_id)
    relinked = await relink_open_reconciliation(user_id, account_id, provider)
    return {
        "unarchived": unarchived,
        "orphaned_unarchived": orphaned,
        "legacy_relinked": legacy,
        "reconciliation_runs_relinked": relinked,
    }
