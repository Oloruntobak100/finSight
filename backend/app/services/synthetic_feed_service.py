"""Synthetic Data Feed — profile management, history fill, and live drip."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.database import get_supabase, run_db
from app.services.books_service import classify_user_transactions
from app.services.synthetic_narration_templates import (
    PERSONA_PRESETS,
    drip_batch_size_for_profile,
    merge_persona_config,
    resolve_daily_tx_range,
    sample_daily_tx_target,
    spread_dates,
    generate_charge_sibling,
    generate_mono_payload,
)
from app.services.transaction_enrichment import build_mono_transaction_row, load_user_category_rules

logger = logging.getLogger(__name__)

DEFAULT_SYNTHETIC_OPENING_BALANCE_NAIRA = 2_000_000.0


def apply_running_balances(payloads: list[dict[str, Any]], *, opening_naira: float = DEFAULT_SYNTHETIC_OPENING_BALANCE_NAIRA) -> list[dict[str, Any]]:
    """Assign coherent running balances in kobo on synthetic Mono payloads."""
    sorted_payloads = sorted(payloads, key=lambda p: p.get("date") or "")
    balance_naira = opening_naira
    for raw in sorted_payloads:
        amount_naira = float(raw.get("amount", 0)) / 100.0
        if raw.get("type") == "credit":
            balance_naira += amount_naira
        else:
            balance_naira -= amount_naira
        raw["balance"] = int(round(balance_naira * 100))
    return sorted_payloads


async def _classify_created_transactions(user_id: str, created_ids: list[str]) -> None:
    try:
        await classify_user_transactions(user_id, created_ids)
    except Exception:
        logger.exception("Background classify failed for %d synthetic transactions", len(created_ids))


def _schedule_classify(user_id: str, created_ids: list[str]) -> bool:
    if not created_ids:
        return False
    asyncio.create_task(_classify_created_transactions(user_id, created_ids))
    return True


def _rows(res: Any) -> list[dict[str, Any]]:
    """Safe extract rows from Supabase execute() — handles None and maybe_single quirks."""
    if res is None:
        return []
    data = getattr(res, "data", None)
    if not data:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _first_row(res: Any) -> dict[str, Any] | None:
    rows = _rows(res)
    return rows[0] if rows else None


async def _select_one(
    sb: Any,
    table: str,
    *,
    filters: list[tuple[str, str, Any]],
) -> dict[str, Any] | None:
    def _query() -> Any:
        q = sb.table(table).select("*")
        for op, col, val in filters:
            if op == "eq":
                q = q.eq(col, val)
        return q.limit(1).execute()

    return _first_row(await run_db(_query))


def synthetic_feed_allowed() -> bool:
    return settings.synthetic_feed_allowed


async def _get_mono_account(user_id: str, account_id: str) -> dict[str, Any]:
    sb = get_supabase()
    row = await _select_one(
        sb,
        "connected_accounts",
        filters=[
            ("eq", "id", account_id),
            ("eq", "user_id", user_id),
            ("eq", "provider", "mono"),
            ("eq", "status", "active"),
        ],
    )
    if not row:
        raise ValueError("Mono bank account not found or inactive")
    return row


async def _upsert_profile_row(user_id: str, account_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    existing_row = await _select_one(
        sb,
        "synthetic_feed_profiles",
        filters=[
            ("eq", "user_id", user_id),
            ("eq", "account_id", account_id),
        ],
    )
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    if existing_row:
        await run_db(
            lambda: sb.table("synthetic_feed_profiles")
            .update(patch)
            .eq("id", existing_row["id"])
            .execute()
        )
        row = await _select_one(
            sb,
            "synthetic_feed_profiles",
            filters=[("eq", "id", existing_row["id"])],
        )
    else:
        patch.update({"user_id": user_id, "account_id": account_id})
        await run_db(lambda: sb.table("synthetic_feed_profiles").insert(patch).execute())
        row = await _select_one(
            sb,
            "synthetic_feed_profiles",
            filters=[
                ("eq", "user_id", user_id),
                ("eq", "account_id", account_id),
            ],
        )
    if not row:
        raise ValueError("Could not upsert synthetic feed profile")
    return row


async def get_or_create_profile(user_id: str, account_id: str) -> dict[str, Any]:
    sb = get_supabase()
    row = await _select_one(
        sb,
        "synthetic_feed_profiles",
        filters=[
            ("eq", "user_id", user_id),
            ("eq", "account_id", account_id),
        ],
    )
    if row:
        return row
    return await _upsert_profile_row(
        user_id,
        account_id,
        {
            "persona_type": "individual",
            "persona_config": PERSONA_PRESETS["individual"],
            "daily_tx_min": PERSONA_PRESETS["individual"]["daily_tx_min"],
            "daily_tx_max": PERSONA_PRESETS["individual"]["daily_tx_max"],
            "daily_tx_target": 14,
            "status": "draft",
        },
    )


async def save_profile(
    user_id: str,
    account_id: str,
    *,
    persona_type: str,
    persona_config: dict[str, Any] | None = None,
    daily_tx_min: int | None = None,
    daily_tx_max: int | None = None,
    daily_tx_target: int | None = None,
    live_interval_hours: int | None = None,
    auto_classify: bool | None = None,
    historical_start: str | None = None,
    historical_end: str | None = None,
) -> dict[str, Any]:
    await _get_mono_account(user_id, account_id)
    merged = merge_persona_config(persona_type, persona_config or {})
    if daily_tx_min is not None:
        merged["daily_tx_min"] = daily_tx_min
    if daily_tx_max is not None:
        merged["daily_tx_max"] = daily_tx_max

    lo, hi = resolve_daily_tx_range(
        {
            "persona_type": persona_type,
            "persona_config": merged,
            "daily_tx_min": daily_tx_min,
            "daily_tx_max": daily_tx_max,
            "daily_tx_target": daily_tx_target,
        }
    )

    patch: dict[str, Any] = {
        "persona_type": persona_type,
        "persona_config": merged,
        "daily_tx_min": lo,
        "daily_tx_max": hi,
        "daily_tx_target": (lo + hi) // 2,
        "status": "draft",
    }
    if daily_tx_target is not None:
        patch["daily_tx_target"] = daily_tx_target
    if live_interval_hours is not None:
        patch["live_interval_hours"] = live_interval_hours
    if auto_classify is not None:
        patch["auto_classify"] = auto_classify
    if historical_start:
        patch["historical_start"] = historical_start
    if historical_end:
        patch["historical_end"] = historical_end
    return await _upsert_profile_row(user_id, account_id, patch)


async def _start_run(
    profile: dict[str, Any],
    run_type: str,
    persona_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    row = {
        "profile_id": profile["id"],
        "user_id": profile["user_id"],
        "account_id": profile["account_id"],
        "run_type": run_type,
        "persona_snapshot": persona_snapshot or {},
        "status": "running",
    }
    res = await run_db(lambda: sb.table("synthetic_feed_runs").insert(row).execute())
    created = _first_row(res)
    if not created:
        raise ValueError("Could not start synthetic feed run")
    return created


async def _finish_run(
    run_id: str,
    *,
    status: str,
    transactions_created: int = 0,
    transactions_archived: int = 0,
    error: str | None = None,
) -> None:
    sb = get_supabase()
    await run_db(
        lambda: sb.table("synthetic_feed_runs")
        .update(
            {
                "status": status,
                "transactions_created": transactions_created,
                "transactions_archived": transactions_archived,
                "error": error,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", run_id)
        .execute()
    )


async def _insert_synthetic_transactions(
    user_id: str,
    account_id: str,
    payloads: list[dict[str, Any]],
    *,
    external_prefix: str,
) -> list[str]:
    sb = get_supabase()
    user_rules = await load_user_category_rules(user_id, sb)
    created_ids: list[str] = []
    rows: list[dict[str, Any]] = []

    for raw in payloads:
        amount = float(raw.get("amount", 0)) / 100
        txn_type = "debit" if raw.get("type") == "debit" else "credit"
        ext_id = raw.get("id") or f"{external_prefix}missing"
        row = build_mono_transaction_row(
            raw,
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            txn_type=txn_type,
            currency="NGN",
            external_id=ext_id,
            user_rules=user_rules,
        )
        if not row.get("transaction_date"):
            row["transaction_date"] = str(date.today())
        row["is_synthetic"] = True
        row["discovered_date"] = datetime.now(timezone.utc).isoformat()
        rows.append(row)

    batch_size = 50
    for offset in range(0, len(rows), batch_size):
        chunk = rows[offset : offset + batch_size]
        res = await run_db(
            lambda c=chunk: sb.table("transactions")
            .upsert(c, on_conflict="source_provider,external_id,user_id")
            .execute()
        )
        for inserted in _rows(res):
            if inserted.get("id"):
                created_ids.append(inserted["id"])

    return created_ids


async def import_mono_history(
    user_id: str,
    account_id: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    from app.services.mono_service import sync_mono_transactions

    profile = await get_or_create_profile(user_id, account_id)
    run = await _start_run(profile, "mono_import", {"start": start, "end": end})
    try:
        imported = await sync_mono_transactions(
            user_id,
            account_id,
            start=start,
            end=end,
            skip_enrichment=True,
            data_wait_attempts=3,
        )
        await _upsert_profile_row(
            user_id,
            account_id,
            {"historical_start": start, "historical_end": end},
        )
        await _finish_run(run["id"], status="completed", transactions_created=imported)
        return {"imported": imported, "start": start, "end": end, "run_id": run["id"]}
    except Exception as exc:
        await _finish_run(run["id"], status="failed", error=str(exc))
        raise


async def fill_sparse_history(
    user_id: str,
    account_id: str,
    start: str,
    end: str,
    count: int | None = None,
) -> dict[str, Any]:
    profile = await get_or_create_profile(user_id, account_id)
    persona_type = profile.get("persona_type") or "individual"
    persona_config = profile.get("persona_config") or {}
    daily_avg = sum(resolve_daily_tx_range(profile)) // 2

    start_dt = datetime.strptime(start[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end[:10], "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
    days = max(1, (end_dt - start_dt).days + 1)

    if count is None:
        count = min(500, max(10, int(days * daily_avg * 0.3)))

    run = await _start_run(
        profile,
        "history_fill",
        {"start": start, "end": end, "count": count, "persona_type": persona_type},
    )

    try:
        dates = spread_dates(count, start_dt, end_dt)
        payloads: list[dict[str, Any]] = []
        for when in dates:
            gen = generate_mono_payload(
                persona_type=persona_type,
                persona_config=persona_config,
                when=when,
                external_prefix="syn-hist-",
            )
            gen.raw["date"] = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            payloads.append(gen.raw)
            sibling = generate_charge_sibling(gen, when, "syn-hist-")
            if sibling:
                payloads.append(sibling.raw)

        payloads = apply_running_balances(payloads)
        created_ids = await _insert_synthetic_transactions(
            user_id, account_id, payloads, external_prefix="syn-hist-"
        )

        await _upsert_profile_row(
            user_id,
            account_id,
            {"last_backfill_at": datetime.now(timezone.utc).isoformat(), "status": "active"},
        )
        await _finish_run(run["id"], status="completed", transactions_created=len(created_ids))

        classify_pending = False
        if profile.get("auto_classify", True) and created_ids:
            classify_pending = _schedule_classify(user_id, created_ids)

        return {
            "created": len(created_ids),
            "classified": 0,
            "classify_pending": classify_pending,
            "run_id": run["id"],
        }
    except Exception as exc:
        await _finish_run(run["id"], status="failed", error=str(exc))
        raise


async def run_live_drip(profile: dict[str, Any]) -> dict[str, Any]:
    user_id = profile["user_id"]
    account_id = profile["account_id"]
    persona_type = profile.get("persona_type") or "individual"
    persona_config = profile.get("persona_config") or {}
    interval = int(profile.get("live_interval_hours") or 6)
    batch = drip_batch_size_for_profile(profile)
    daily_sample = sample_daily_tx_target(profile)

    run = await _start_run(
        profile,
        "live_drip",
        {"batch_size": batch, "daily_tx_sample": daily_sample},
    )
    now = datetime.now(timezone.utc)

    try:
        payloads: list[dict[str, Any]] = []
        for i in range(batch):
            jitter = timedelta(minutes=random_jitter_minutes(i, batch))
            when = now - jitter
            gen = generate_mono_payload(
                persona_type=persona_type,
                persona_config=persona_config,
                when=when,
                external_prefix="syn-live-",
            )
            payloads.append(gen.raw)
            sibling = generate_charge_sibling(gen, when, "syn-live-")
            if sibling:
                payloads.append(sibling.raw)

        payloads = apply_running_balances(payloads)
        created_ids = await _insert_synthetic_transactions(
            user_id, account_id, payloads, external_prefix="syn-live-"
        )

        next_run = now + timedelta(hours=interval)
        await _upsert_profile_row(
            user_id,
            account_id,
            {
                "last_live_run_at": now.isoformat(),
                "next_live_run_at": next_run.isoformat(),
                "status": "active",
            },
        )
        await _finish_run(run["id"], status="completed", transactions_created=len(created_ids))

        classify_pending = False
        if profile.get("auto_classify", True) and created_ids:
            classify_pending = _schedule_classify(user_id, created_ids)

        return {
            "created": len(created_ids),
            "classified": 0,
            "classify_pending": classify_pending,
            "next_live_run_at": next_run.isoformat(),
            "run_id": run["id"],
        }
    except Exception as exc:
        await _finish_run(run["id"], status="failed", error=str(exc))
        raise


def random_jitter_minutes(index: int, batch: int) -> int:
    span = max(30, min(360, batch * 45))
    return min(span, index * (span // max(1, batch)) + (index * 7) % 30)


async def start_live_feed(user_id: str, account_id: str) -> dict[str, Any]:
    profile = await get_or_create_profile(user_id, account_id)
    now = datetime.now(timezone.utc)
    interval = int(profile.get("live_interval_hours") or 6)
    updated = await _upsert_profile_row(
        user_id,
        account_id,
        {
            "live_feed_enabled": True,
            "status": "active",
            "next_live_run_at": now.isoformat(),
        },
    )

    first_drip: dict[str, Any] | None = None
    first_drip_error: str | None = None
    try:
        first_drip = await run_live_drip(updated)
    except Exception as exc:
        logger.exception("Initial live drip failed for account %s", account_id)
        first_drip_error = str(exc)[:500]
        await _schedule_live_drip_retry(user_id, account_id, minutes=15)

    refreshed = await get_or_create_profile(user_id, account_id)
    result: dict[str, Any] = {"profile": refreshed, "interval_hours": interval}
    if first_drip:
        result["first_drip"] = first_drip
    if first_drip_error:
        result["first_drip_error"] = first_drip_error
    return result


async def pause_live_feed(user_id: str, account_id: str) -> dict[str, Any]:
    updated = await _upsert_profile_row(
        user_id,
        account_id,
        {"live_feed_enabled": False, "status": "paused"},
    )
    return {"profile": updated}


async def run_live_drip_now(user_id: str, account_id: str) -> dict[str, Any]:
    profile = await get_or_create_profile(user_id, account_id)
    return await run_live_drip(profile)


MONO_SANDBOX_DUMMY_MARKERS = ("Samuel Olamide",)


async def _fetch_transaction_ids(
    sb: Any,
    *,
    user_id: str,
    account_id: str | None = None,
    is_synthetic: bool | None = None,
    source_provider: str | None = None,
    name_markers: tuple[str, ...] | None = None,
) -> list[str]:
    """Collect IDs to archive (Supabase update alone does not return row counts reliably)."""
    ids: list[str] = []
    page_size = 500
    offset = 0
    while True:
        def _page(off: int = offset) -> Any:
            q = (
                sb.table("transactions")
                .select("id")
                .eq("user_id", user_id)
                .is_("archived_at", "null")
            )
            if account_id is not None:
                q = q.eq("account_id", account_id)
            if is_synthetic is not None:
                q = q.eq("is_synthetic", is_synthetic)
            if source_provider:
                q = q.eq("source_provider", source_provider)
            if name_markers:
                or_filters = ",".join(
                    f"merchant_name.ilike.%{marker}%,description.ilike.%{marker}%"
                    for marker in name_markers
                )
                q = q.or_(or_filters)
            return q.range(off, off + page_size - 1).execute()

        batch = _rows(await run_db(_page))
        if not batch:
            break
        ids.extend(row["id"] for row in batch if row.get("id"))
        if len(batch) < page_size:
            break
        offset += page_size
    return ids


async def _archive_transaction_ids(sb: Any, ids: list[str]) -> int:
    if not ids:
        return 0
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


async def user_transaction_stats(user_id: str) -> dict[str, int]:
    sb = get_supabase()
    total_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .is_("archived_at", "null")
        .execute()
    )
    syn_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("is_synthetic", True)
        .is_("archived_at", "null")
        .execute()
    )
    mono_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("source_provider", "mono")
        .eq("is_synthetic", False)
        .is_("archived_at", "null")
        .execute()
    )
    total = total_res.count or 0
    synthetic = syn_res.count or 0
    return {
        "total": total,
        "synthetic": synthetic,
        "mono_imported": mono_res.count or 0,
        "non_synthetic": total - synthetic,
    }


async def keep_synthetic_only_user(user_id: str) -> dict[str, Any]:
    """Archive every non-synthetic transaction across all accounts (Mono dummy cleanup)."""
    sb = get_supabase()
    ids = await _fetch_transaction_ids(sb, user_id=user_id, is_synthetic=False)
    archived = await _archive_transaction_ids(sb, ids)
    stats = await user_transaction_stats(user_id)
    return {
        "archived": archived,
        "remaining_total": stats["total"],
        "remaining_synthetic": stats["synthetic"],
    }


async def purge_mono_imports_user(user_id: str) -> dict[str, Any]:
    """Archive all non-synthetic Mono imports across all accounts."""
    sb = get_supabase()
    ids = await _fetch_transaction_ids(
        sb,
        user_id=user_id,
        is_synthetic=False,
        source_provider="mono",
    )
    archived = await _archive_transaction_ids(sb, ids)
    stats = await user_transaction_stats(user_id)
    return {
        "archived": archived,
        "remaining_total": stats["total"],
        "remaining_synthetic": stats["synthetic"],
    }


async def transaction_stats(user_id: str, account_id: str) -> dict[str, int]:
    sb = get_supabase()

    def _count(**filters: Any) -> Any:
        q = (
            sb.table("transactions")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("account_id", account_id)
            .is_("archived_at", "null")
        )
        for key, val in filters.items():
            q = q.eq(key, val)
        return q.execute()

    total_res = await run_db(lambda: _count())
    syn_res = await run_db(lambda: _count(is_synthetic=True))
    mono_res = await run_db(
        lambda: sb.table("transactions")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .eq("source_provider", "mono")
        .eq("is_synthetic", False)
        .is_("archived_at", "null")
        .execute()
    )
    return {
        "total": total_res.count or 0,
        "synthetic": syn_res.count or 0,
        "mono_imported": mono_res.count or 0,
        "non_synthetic": (total_res.count or 0) - (syn_res.count or 0),
    }


async def purge_mono_sandbox_dummies(user_id: str, account_id: str) -> dict[str, Any]:
    """Soft-delete all non-synthetic Mono rows for this account (sandbox cleanup)."""
    await _get_mono_account(user_id, account_id)
    sb = get_supabase()
    ids = await _fetch_transaction_ids(
        sb,
        user_id=user_id,
        account_id=account_id,
        is_synthetic=False,
        source_provider="mono",
    )
    archived = await _archive_transaction_ids(sb, ids)
    stats = await transaction_stats(user_id, account_id)
    return {
        "archived": archived,
        "remaining_total": stats["total"],
        "remaining_synthetic": stats["synthetic"],
    }


async def keep_synthetic_only(user_id: str, account_id: str) -> dict[str, Any]:
    """Archive every non-synthetic transaction for this account."""
    await _get_mono_account(user_id, account_id)
    sb = get_supabase()
    ids = await _fetch_transaction_ids(
        sb,
        user_id=user_id,
        account_id=account_id,
        is_synthetic=False,
    )
    archived = await _archive_transaction_ids(sb, ids)
    stats = await transaction_stats(user_id, account_id)
    return {
        "archived": archived,
        "remaining_total": stats["total"],
        "remaining_synthetic": stats["synthetic"],
    }


async def reset_synthetic_transactions(user_id: str, account_id: str) -> dict[str, Any]:
    """Archive all synthetic rows so Fill history can start clean (avoids duplicate stacks)."""
    await _get_mono_account(user_id, account_id)
    sb = get_supabase()
    ids = await _fetch_transaction_ids(
        sb,
        user_id=user_id,
        account_id=account_id,
        is_synthetic=True,
    )
    archived = await _archive_transaction_ids(sb, ids)
    stats = await transaction_stats(user_id, account_id)
    return {
        "archived": archived,
        "remaining_total": stats["total"],
        "remaining_synthetic": stats["synthetic"],
    }


async def list_status(user_id: str) -> dict[str, Any]:
    sb = get_supabase()
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("id, account_name, provider, status, last_synced_at")
        .eq("user_id", user_id)
        .eq("provider", "mono")
        .neq("status", "disconnected")
        .execute()
    )
    profiles_res = await run_db(
        lambda: sb.table("synthetic_feed_profiles")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )
    profile_map = {p["account_id"]: p for p in (profiles_res.data or [])}
    latest_drips = await _latest_live_drip_runs(user_id)
    accounts = []
    for acct in accounts_res.data or []:
        prof = profile_map.get(acct["id"])
        drip = latest_drips.get(acct["id"])
        accounts.append(
            {
                **acct,
                "profile": prof,
                "live_feed_enabled": bool(prof and prof.get("live_feed_enabled")),
                "next_live_run_at": prof.get("next_live_run_at") if prof else None,
                "last_live_run_at": prof.get("last_live_run_at") if prof else None,
                "last_live_drip": drip,
            }
        )
    return {
        "enabled": synthetic_feed_allowed(),
        "accounts": accounts,
    }


async def get_account_detail(user_id: str, account_id: str) -> dict[str, Any]:
    await _get_mono_account(user_id, account_id)
    profile = await get_or_create_profile(user_id, account_id)
    sb = get_supabase()
    runs_res = await run_db(
        lambda: sb.table("synthetic_feed_runs")
        .select("*")
        .eq("account_id", account_id)
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"profile": profile, "runs": runs_res.data or [], "presets": PERSONA_PRESETS, "stats": await transaction_stats(user_id, account_id)}


async def list_runs(user_id: str, account_id: str, page: int = 1, limit: int = 20) -> dict[str, Any]:
    sb = get_supabase()
    offset = (page - 1) * limit
    res = await run_db(
        lambda: sb.table("synthetic_feed_runs")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    total = res.count or 0
    return {
        "items": res.data or [],
        "total": total,
        "page": page,
        "limit": limit,
    }


async def _schedule_live_drip_retry(user_id: str, account_id: str, *, minutes: int = 30) -> None:
    next_run = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    await _upsert_profile_row(
        user_id,
        account_id,
        {"next_live_run_at": next_run.isoformat(), "status": "active"},
    )


async def _latest_live_drip_runs(user_id: str) -> dict[str, dict[str, Any]]:
    """Most recent live_drip run per account for status display."""
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("synthetic_feed_runs")
        .select("account_id, status, error, transactions_created, started_at, finished_at")
        .eq("user_id", user_id)
        .eq("run_type", "live_drip")
        .order("started_at", desc=True)
        .limit(200)
        .execute()
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in res.data or []:
        aid = row.get("account_id")
        if aid and aid not in latest:
            latest[aid] = row
    return latest


async def run_scheduled_live_drips() -> dict[str, Any]:
    """Run all due synthetic live drips. Safe to call from scheduler, startup, or HTTP cron."""
    if not synthetic_feed_allowed():
        return {"processed": 0, "failed": 0, "skipped": True, "errors": []}

    sb = get_supabase()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    res = await run_db(
        lambda: sb.table("synthetic_feed_profiles")
        .select("*")
        .eq("live_feed_enabled", True)
        .lte("next_live_run_at", now_iso)
        .execute()
    )

    processed = 0
    failed = 0
    errors: list[dict[str, str]] = []
    for profile in res.data or []:
        account_id = str(profile.get("account_id") or "")
        user_id = str(profile.get("user_id") or "")
        try:
            await run_live_drip(profile)
            processed += 1
        except Exception as exc:
            failed += 1
            err = str(exc)[:500]
            errors.append({"account_id": account_id, "error": err})
            logger.exception("Live drip failed for profile %s", profile.get("id"))
            if user_id and account_id:
                await _schedule_live_drip_retry(user_id, account_id, minutes=30)

    return {"processed": processed, "failed": failed, "skipped": False, "errors": errors}


async def synthetic_feed_drip_all() -> dict[str, Any]:
    """Backward-compatible alias used by scheduler tasks."""
    return await run_scheduled_live_drips()
