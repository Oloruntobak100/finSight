"""Bank account disconnect/reconnect lifecycle — preserve Supabase continuity."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.database import get_supabase, run_db

logger = logging.getLogger(__name__)

BANK_PROVIDERS = ("plaid", "mono")
OPEN_RECON_STATUSES = ("DRAFT", "IN_REVIEW", "ADJUSTED")
UNARCHIVE_BATCH = 100
AUTO_RESTORE_BUDGET = 150


def _batch_size(limit: int | None, restored: int) -> int:
    if limit is None:
        return UNARCHIVE_BATCH
    remaining = limit - restored
    if remaining <= 0:
        return 0
    return min(UNARCHIVE_BATCH, remaining)


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


async def unarchive_transactions_for_account(
    user_id: str, account_id: str, *, limit: int | None = None
) -> int:
    sb = get_supabase()
    total = 0
    while True:
        batch = _batch_size(limit, total)
        if batch <= 0:
            break
        res = await run_db(
            lambda size=batch: sb.table("transactions")
            .select("id")
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .not_.is_("archived_at", "null")
            .limit(size)
            .execute()
        )
        ids = [row["id"] for row in (res.data or []) if row.get("id")]
        if not ids:
            break
        total += await _clear_archived_at(user_id, ids)
        if len(ids) < batch:
            break
    return total


async def unarchive_orphaned_bank_transactions(
    user_id: str, account_id: str, provider: str, *, limit: int | None = None
) -> int:
    """Relink and unarchive bank rows detached by legacy hard-delete (account_id IS NULL)."""
    sb = get_supabase()
    total = 0
    while True:
        batch = _batch_size(limit, total)
        if batch <= 0:
            break
        res = await run_db(
            lambda size=batch: sb.table("transactions")
            .select("id")
            .eq("user_id", user_id)
            .eq("source_provider", provider)
            .is_("account_id", "null")
            .not_.is_("archived_at", "null")
            .limit(size)
            .execute()
        )
        ids = [row["id"] for row in (res.data or []) if row.get("id")]
        if not ids:
            break
        await run_db(
            lambda row_ids=ids: sb.table("transactions")
            .update({"account_id": account_id, "archived_at": None})
            .eq("user_id", user_id)
            .in_("id", row_ids)
            .execute()
        )
        total += len(ids)
        if len(ids) < batch:
            break
    return total


async def count_archived_bank_transactions(user_id: str, provider: str | None = None) -> int:
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("source_provider", list(BANK_PROVIDERS))
        .not_.is_("archived_at", "null")
    )
    if provider:
        query = query.eq("source_provider", provider)
    res = await run_db(lambda: query.execute())
    return res.count or 0


def _mono_synthetic_wins() -> bool:
    return settings.synthetic_feed_allowed


async def _restore_bank_metadata_only(
    user_id: str,
    account_id: str,
    provider: str,
    external_account_id: str | None,
) -> dict[str, Any] | None:
    """Reconnect mappings/reconciliation; restore synthetic rows; resume live drip."""
    from app.services.bank_transaction_scope import unarchive_synthetic_transactions_for_account
    from app.services.synthetic_feed_service import resume_live_feed_on_reconnect

    await unarchive_synthetic_transactions_for_account(user_id, account_id)
    await migrate_bank_mapping_alias(user_id, account_id, external_account_id)
    await relink_open_reconciliation(user_id, account_id, provider)
    if provider == "mono":
        return await resume_live_feed_on_reconnect(user_id, account_id)
    return None


async def maybe_auto_restore_bank_data(
    user_id: str,
    bank_accounts: list[dict[str, Any]],
    *,
    visible_count: int,
) -> dict[str, int] | None:
    """Restore a small batch of archived bank rows when an account shows zero visible txns."""
    if _mono_synthetic_wins():
        return None
    if visible_count > 0 or not bank_accounts:
        return None
    totals: dict[str, int] = {
        "unarchived": 0,
        "orphaned_unarchived": 0,
        "legacy_relinked": 0,
        "reconciliation_runs_relinked": 0,
    }
    restored = False
    try:
        for account in bank_accounts:
            provider = account.get("provider")
            if provider not in BANK_PROVIDERS or account.get("status") == "disconnected":
                continue
            archived = await count_archived_bank_transactions(user_id, provider)
            if archived <= 0:
                continue
            result = await restore_bank_account_continuity(
                user_id,
                account["id"],
                provider,
                account.get("external_account_id"),
                max_rows=AUTO_RESTORE_BUDGET,
            )
            for key in totals:
                totals[key] += int(result.get(key) or 0)
            restored = True
    except Exception as exc:
        logger.warning("Auto-restore skipped for user %s: %s", user_id, exc)
        return None
    return totals if restored else None


async def relink_legacy_archived_transactions(
    user_id: str,
    account_id: str,
    provider: str,
    *,
    limit: int | None = None,
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
    all_connected_ids = {r["id"] for r in connected_rows}
    other_active_ids = {
        r["id"]
        for r in connected_rows
        if r.get("status") == "active" and r["id"] != account_id
    }

    total = 0
    offset = 0
    while True:
        batch = _batch_size(limit, total)
        if batch <= 0:
            break
        page_offset = offset

        def _page(off: int = page_offset, size: int = batch) -> Any:
            return (
                sb.table("transactions")
                .select("id, account_id")
                .eq("user_id", user_id)
                .eq("source_provider", provider)
                .not_.is_("archived_at", "null")
                .range(off, off + size - 1)
                .execute()
            )

        res = await run_db(_page)
        batch_rows = res.data or []
        if not batch_rows:
            break
        relink_ids: list[str] = []
        for row in batch_rows:
            tid = row.get("id")
            old_account_id = row.get("account_id")
            if not tid:
                continue
            if old_account_id in other_active_ids:
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
        if relink_ids:
            if limit is not None:
                room = limit - total
                if room <= 0:
                    break
                relink_ids = relink_ids[:room]
            await run_db(
                lambda ids=relink_ids: sb.table("transactions")
                .update({"account_id": account_id, "archived_at": None})
                .eq("user_id", user_id)
                .in_("id", ids)
                .execute()
            )
            total += len(relink_ids)
        offset += batch
        if len(batch_rows) < batch or (limit is not None and total >= limit):
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
        if provider == "mono" and _mono_synthetic_wins():
            await _restore_bank_metadata_only(
                user_id, account_id, provider, external_account_id
            )
        else:
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
        if provider == "mono" and _mono_synthetic_wins():
            from app.services.synthetic_feed_service import maybe_enforce_synthetic_wins

            await maybe_enforce_synthetic_wins(user_id, account_id)
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
    if provider == "mono" and _mono_synthetic_wins():
        await _restore_bank_metadata_only(
            user_id, account["id"], provider, external_account_id
        )
    else:
        await restore_bank_account_continuity(
            user_id, account["id"], provider, external_account_id
        )
    if provider == "mono" and _mono_synthetic_wins():
        from app.services.synthetic_feed_service import maybe_enforce_synthetic_wins

        await maybe_enforce_synthetic_wins(user_id, account["id"])
    return account, False


async def restore_bank_account_continuity(
    user_id: str,
    account_id: str,
    provider: str,
    external_account_id: str | None,
    *,
    max_rows: int | None = None,
) -> dict[str, int]:
    remaining = max_rows
    unarchived = await unarchive_transactions_for_account(
        user_id, account_id, limit=remaining
    )
    if remaining is not None:
        remaining = max(0, remaining - unarchived)
    orphaned = await unarchive_orphaned_bank_transactions(
        user_id, account_id, provider, limit=remaining
    )
    if remaining is not None:
        remaining = max(0, remaining - orphaned)
    legacy = await relink_legacy_archived_transactions(
        user_id, account_id, provider, limit=remaining
    )
    if max_rows is None:
        await migrate_bank_mapping_alias(user_id, account_id, external_account_id)
        relinked = await relink_open_reconciliation(user_id, account_id, provider)
    else:
        relinked = 0
    feed_resume: dict[str, Any] | None = None
    if max_rows is None and provider == "mono":
        from app.services.synthetic_feed_service import resume_live_feed_on_reconnect

        feed_resume = await resume_live_feed_on_reconnect(user_id, account_id)
    result = {
        "unarchived": unarchived,
        "orphaned_unarchived": orphaned,
        "legacy_relinked": legacy,
        "reconciliation_runs_relinked": relinked,
    }
    if feed_resume:
        result["live_feed_resumed"] = feed_resume.get("resumed", False)
    return result
