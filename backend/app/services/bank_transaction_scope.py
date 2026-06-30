"""Active connected-bank scope and transaction archival for bank-linked rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import get_supabase, run_db

BANK_PROVIDERS = ("plaid", "mono")
SCOPE_PAGE_SIZE = 500


async def get_active_bank_accounts(user_id: str) -> tuple[list[dict[str, Any]], set[str]]:
    """Connected Plaid/Mono accounts (not disconnected)."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, provider, account_name, status, last_synced_at")
        .eq("user_id", user_id)
        .execute()
    )
    accounts = [
        a
        for a in (res.data or [])
        if a.get("provider") in BANK_PROVIDERS and a.get("status") != "disconnected"
    ]
    return accounts, {a["id"] for a in accounts}


def apply_active_bank_scope(
    query: Any,
    active_bank_ids: set[str],
    *,
    bank_providers_only: bool = True,
) -> Any:
    """Non-archived rows tied to active connected bank accounts only."""
    query = query.is_("archived_at", "null")
    if bank_providers_only:
        query = query.in_("source_provider", list(BANK_PROVIDERS))
    if not active_bank_ids:
        return query.eq("account_id", "00000000-0000-0000-0000-000000000000")
    return query.in_("account_id", list(active_bank_ids))


async def _fetch_scoped_transaction_ids(
    user_id: str,
    *,
    account_id: str | None = None,
    is_synthetic: bool | None = None,
    detached_only: bool = False,
    active_bank_ids: set[str] | None = None,
) -> list[str]:
    """Paginate ID collection for archive operations."""
    sb = get_supabase()
    if detached_only:
        accounts, active_ids = await get_active_bank_accounts(user_id)
        _ = accounts
    else:
        active_ids = active_bank_ids

    ids: list[str] = []
    offset = 0
    while True:
        def _page(off: int = offset) -> Any:
            q = (
                sb.table("transactions")
                .select("id, account_id")
                .eq("user_id", user_id)
                .is_("archived_at", "null")
                .in_("source_provider", list(BANK_PROVIDERS))
            )
            if account_id is not None:
                q = q.eq("account_id", account_id)
            if is_synthetic is not None:
                q = q.eq("is_synthetic", is_synthetic)
            return q.range(off, off + SCOPE_PAGE_SIZE - 1).execute()

        batch = (await run_db(_page)).data or []
        if not batch:
            break
        for row in batch:
            tid = row.get("id")
            if not tid:
                continue
            aid = row.get("account_id")
            if detached_only:
                if aid is None or (active_ids and aid not in active_ids):
                    ids.append(tid)
            else:
                ids.append(tid)
        if len(batch) < SCOPE_PAGE_SIZE:
            break
        offset += SCOPE_PAGE_SIZE
    return ids


async def _archive_ids(ids: list[str]) -> int:
    if not ids:
        return 0
    sb = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    archived = 0
    for offset in range(0, len(ids), 50):
        chunk = ids[offset : offset + 50]
        await run_db(
            lambda c=chunk: sb.table("transactions")
            .update({"archived_at": now_iso})
            .in_("id", c)
            .execute()
        )
        archived += len(chunk)
    return archived


async def archive_transactions_for_account(user_id: str, account_id: str) -> int:
    """Archive all non-archived bank transactions for a connected account."""
    ids = await _fetch_scoped_transaction_ids(user_id, account_id=account_id)
    return await _archive_ids(ids)


async def archive_detached_bank_transactions(user_id: str) -> int:
    """Archive bank rows with no account or account no longer connected."""
    ids = await _fetch_scoped_transaction_ids(user_id, detached_only=True)
    return await _archive_ids(ids)


async def count_scoped_transactions(
    user_id: str,
    active_bank_ids: set[str],
    *,
    qb_sync_status: str | None = None,
    unclassified: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    sb = get_supabase()
    query = (
        sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
    )
    query = apply_active_bank_scope(query, active_bank_ids)
    if unclassified:
        query = query.is_("qb_sync_status", "null")
    elif qb_sync_status is not None:
        query = query.eq("qb_sync_status", qb_sync_status)
    if date_from:
        query = query.gte("transaction_date", date_from[:10])
    if date_to:
        query = query.lte("transaction_date", date_to[:10])
    res = await run_db(lambda: query.execute())
    return res.count or 0


async def iter_scoped_transactions(
    user_id: str,
    active_bank_ids: set[str],
    *,
    extra_filter: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch all scoped transaction rows with pagination."""
    sb = get_supabase()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        def _page(off: int = offset) -> Any:
            q = sb.table("transactions").select("*").eq("user_id", user_id)
            q = apply_active_bank_scope(q, active_bank_ids)
            if extra_filter:
                q = extra_filter(q)
            return q.range(off, off + SCOPE_PAGE_SIZE - 1).execute()

        batch = (await run_db(_page)).data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < SCOPE_PAGE_SIZE:
            break
        offset += SCOPE_PAGE_SIZE
    return rows
