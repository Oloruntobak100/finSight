from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.scheduler.tasks import (
    daily_books_digest,
    nightly_auto_post,
    nightly_fingerprint_confidence,
    nightly_forecast_all,
    nightly_metrics_all,
    nightly_sync_all,
    synthetic_feed_drip_all,
)

scheduler = AsyncIOScheduler()


def register_jobs() -> None:
    job_defaults = {"replace_existing": True, "max_instances": 1, "coalesce": True}
    scheduler.add_job(
        nightly_sync_all, "cron", hour=2, minute=0, id="nightly_sync", **job_defaults
    )
    scheduler.add_job(
        nightly_auto_post, "cron", hour=2, minute=30, id="nightly_auto_post", **job_defaults
    )
    scheduler.add_job(
        nightly_metrics_all, "cron", hour=3, minute=0, id="nightly_metrics", **job_defaults
    )
    scheduler.add_job(
        nightly_fingerprint_confidence,
        "cron",
        hour=3,
        minute=15,
        id="nightly_fingerprint_confidence",
        **job_defaults,
    )
    scheduler.add_job(
        nightly_forecast_all, "cron", hour=3, minute=30, id="nightly_forecast", **job_defaults
    )
    scheduler.add_job(
        daily_books_digest, "cron", hour=7, minute=0, id="daily_books_digest", **job_defaults
    )
    # Check every 15 minutes for profiles whose next_live_run_at is due (default interval: 6h).
    scheduler.add_job(
        synthetic_feed_drip_all,
        "interval",
        minutes=15,
        id="synthetic_feed_drip",
        **job_defaults,
    )


def start_scheduler() -> None:
    register_jobs()
    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
