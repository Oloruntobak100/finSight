import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.database import get_supabase, run_db
from app.services.analytics_service import calculate_metrics
from app.services.books_service import auto_post_approved_transactions
from app.services.fingerprint_service import recalculate_all_fingerprints
from app.services.forecasting_service import generate_forecast
from app.services import mono_service, plaid_service
from app.services.notification_service import create_notification

logger = logging.getLogger(__name__)


async def nightly_sync_all() -> None:
    sb = get_supabase()
    accounts_res = await run_db(
        lambda: sb.table("connected_accounts").select("id, user_id, provider").eq("status", "active").execute()
    )
    for account in accounts_res.data or []:
        try:
            if account["provider"] == "plaid":
                await plaid_service.sync_plaid_transactions(account["user_id"], account["id"])
            elif account["provider"] == "mono":
                if settings.skip_mono_sandbox_sync:
                    continue
                await mono_service.sync_mono_transactions(account["user_id"], account["id"])
        except Exception:
            continue


async def nightly_auto_post() -> None:
    try:
        result = await auto_post_approved_transactions()
        logger.info("Auto-post completed: %s", result)
    except Exception:
        logger.exception("Auto-post job failed")


async def nightly_fingerprint_confidence() -> None:
    try:
        count = await recalculate_all_fingerprints()
        logger.info("Recalculated fingerprint confidence for %s rows", count)
    except Exception:
        logger.exception("Fingerprint confidence job failed")


async def nightly_metrics_all() -> None:
    sb = get_supabase()
    users_res = await run_db(lambda: sb.table("users").select("id").execute())
    for user in users_res.data or []:
        try:
            await calculate_metrics(user["id"])
        except Exception:
            continue


async def nightly_forecast_all() -> None:
    sb = get_supabase()
    users_res = await run_db(lambda: sb.table("users").select("id").execute())
    for user in users_res.data or []:
        try:
            await generate_forecast(user["id"])
        except Exception:
            continue


async def daily_books_digest() -> None:
    sb = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    users_res = await run_db(
        lambda: sb.table("users").select("id, digest_enabled").eq("digest_enabled", True).execute()
    )
    for user in users_res.data or []:
        uid = user["id"]
        try:
            posted_res = await run_db(
                lambda: sb.table("transactions")
                .select("id", count="exact")
                .eq("user_id", uid)
                .eq("qb_sync_status", "posted")
                .gte("qb_posted_at", since)
                .execute()
            )
            pending_res = await run_db(
                lambda: sb.table("transactions")
                .select("id", count="exact")
                .eq("user_id", uid)
                .in_("qb_sync_status", ["pending", "needs_review"])
                .execute()
            )
            failed_res = await run_db(
                lambda: sb.table("transactions")
                .select("id", count="exact")
                .eq("user_id", uid)
                .eq("qb_sync_status", "failed")
                .execute()
            )
            posted = posted_res.count or 0
            pending = pending_res.count or 0
            failed = failed_res.count or 0
            if posted == 0 and pending == 0 and failed == 0:
                continue
            body = (
                f"Posted {posted} transaction(s) in the last 24h. "
                f"{pending} awaiting approval. {failed} failed."
            )
            await create_notification(uid, "books_digest", "Books daily digest", body)
        except Exception:
            logger.exception("Digest failed for user %s", uid)


async def synthetic_feed_drip_all() -> None:
    from app.services.synthetic_feed_service import run_scheduled_live_drips

    try:
        result = await run_scheduled_live_drips()
        if result.get("processed") or result.get("failed"):
            logger.info("Synthetic feed drip: %s", result)
    except Exception:
        logger.exception("Synthetic feed drip job failed")
