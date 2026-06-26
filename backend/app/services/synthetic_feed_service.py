"""Synthetic Data Feed — profile management, history fill, and live drip."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.database import get_supabase, run_db
from app.services.books_service import classify_user_transactions
from app.services.synthetic_narration_templates import (
    PERSONA_PRESETS,
    drip_batch_size,
    generate_charge_sibling,
    generate_mono_payload,
    merge_persona_config,
    spread_dates,
)
from app.services.transaction_enrichment import build_mono_transaction_row, load_user_category_rules

logger = logging.getLogger(__name__)


def synthetic_feed_allowed() -> bool:
    return settings.synthetic_feed_allowed


async def _get_mono_account(user_id: str, account_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("connected_accounts")
        .select("*")
        .eq("id", account_id)
        .eq("user_id", user_id)
        .eq("provider", "mono")
        .eq("status", "active")
        .single()
        .execute()
    )
    if not res.data:
        raise ValueError("Mono bank account not found or inactive")
    return res.data


async def _upsert_profile_row(user_id: str, account_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    sb = get_supabase()
    existing = await run_db(
        lambda: sb.table("synthetic_feed_profiles")
        .select("*")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .maybe_single()
        .execute()
    )
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    if existing.data:
        res = await run_db(
            lambda: sb.table("synthetic_feed_profiles")
            .update(patch)
            .eq("id", existing.data["id"])
            .execute()
        )
        return res.data[0]
    patch.update({"user_id": user_id, "account_id": account_id})
    res = await run_db(lambda: sb.table("synthetic_feed_profiles").insert(patch).execute())
    return res.data[0]


async def get_or_create_profile(user_id: str, account_id: str) -> dict[str, Any]:
    sb = get_supabase()
    res = await run_db(
        lambda: sb.table("synthetic_feed_profiles")
        .select("*")
        .eq("user_id", user_id)
        .eq("account_id", account_id)
        .maybe_single()
        .execute()
    )
    if res.data:
        return res.data
    return await _upsert_profile_row(
        user_id,
        account_id,
        {
            "persona_type": "individual",
            "persona_config": PERSONA_PRESETS["individual"],
            "daily_tx_target": PERSONA_PRESETS["individual"]["daily_tx_target"],
            "status": "draft",
        },
    )


async def save_profile(
    user_id: str,
    account_id: str,
    *,
    persona_type: str,
    persona_config: dict[str, Any] | None = None,
    daily_tx_target: int | None = None,
    live_interval_hours: int | None = None,
    auto_classify: bool | None = None,
    historical_start: str | None = None,
    historical_end: str | None = None,
) -> dict[str, Any]:
    await _get_mono_account(user_id, account_id)
    merged = merge_persona_config(persona_type, persona_config or {})
    patch: dict[str, Any] = {
        "persona_type": persona_type,
        "persona_config": merged,
        "status": "draft",
    }
    if daily_tx_target is not None:
        patch["daily_tx_target"] = daily_tx_target
    else:
        patch["daily_tx_target"] = merged.get("daily_tx_target", 15)
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
    return res.data[0]


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

        res = await run_db(
            lambda r=row: sb.table("transactions")
            .upsert(r, on_conflict="source_provider,external_id,user_id")
            .execute()
        )
        if res.data:
            created_ids.append(res.data[0]["id"])

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
        imported = await sync_mono_transactions(user_id, account_id, start=start, end=end)
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
    daily = int(profile.get("daily_tx_target") or 15)

    start_dt = datetime.strptime(start[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(end[:10], "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
    days = max(1, (end_dt - start_dt).days + 1)

    if count is None:
        count = min(500, max(10, int(days * daily * 0.3)))

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

        created_ids = await _insert_synthetic_transactions(
            user_id, account_id, payloads, external_prefix="syn-hist-"
        )

        await _upsert_profile_row(
            user_id,
            account_id,
            {"last_backfill_at": datetime.now(timezone.utc).isoformat(), "status": "active"},
        )
        await _finish_run(run["id"], status="completed", transactions_created=len(created_ids))

        classified = 0
        if profile.get("auto_classify", True) and created_ids:
            result = await classify_user_transactions(user_id, created_ids)
            classified = result.get("classified", 0)

        return {
            "created": len(created_ids),
            "classified": classified,
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
    daily = int(profile.get("daily_tx_target") or 15)
    interval = int(profile.get("live_interval_hours") or 6)
    batch = drip_batch_size(daily, interval)

    run = await _start_run(profile, "live_drip", {"batch_size": batch})
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

        classified = 0
        if profile.get("auto_classify", True) and created_ids:
            result = await classify_user_transactions(user_id, created_ids)
            classified = result.get("classified", 0)

        return {
            "created": len(created_ids),
            "classified": classified,
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
    return {"profile": updated, "interval_hours": interval}


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
    accounts = []
    for acct in accounts_res.data or []:
        prof = profile_map.get(acct["id"])
        accounts.append(
            {
                **acct,
                "profile": prof,
                "live_feed_enabled": bool(prof and prof.get("live_feed_enabled")),
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
    return {"profile": profile, "runs": runs_res.data or [], "presets": PERSONA_PRESETS}


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


async def synthetic_feed_drip_all() -> int:
    if not synthetic_feed_allowed():
        return 0
    sb = get_supabase()
    now_iso = datetime.now(timezone.utc).isoformat()
    res = await run_db(
        lambda: sb.table("synthetic_feed_profiles")
        .select("*")
        .eq("live_feed_enabled", True)
        .lte("next_live_run_at", now_iso)
        .execute()
    )
    processed = 0
    for profile in res.data or []:
        try:
            await run_live_drip(profile)
            processed += 1
        except Exception:
            logger.exception("Live drip failed for profile %s", profile.get("id"))
    return processed
