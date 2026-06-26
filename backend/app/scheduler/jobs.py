import asyncio

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
    scheduler.add_job(lambda: asyncio.create_task(nightly_sync_all()), "cron", hour=2, minute=0, id="nightly_sync")
    scheduler.add_job(lambda: asyncio.create_task(nightly_auto_post()), "cron", hour=2, minute=30, id="nightly_auto_post")
    scheduler.add_job(lambda: asyncio.create_task(nightly_metrics_all()), "cron", hour=3, minute=0, id="nightly_metrics")
    scheduler.add_job(
        lambda: asyncio.create_task(nightly_fingerprint_confidence()),
        "cron",
        hour=3,
        minute=15,
        id="nightly_fingerprint_confidence",
    )
    scheduler.add_job(
        lambda: asyncio.create_task(nightly_forecast_all()), "cron", hour=3, minute=30, id="nightly_forecast"
    )
    scheduler.add_job(
        lambda: asyncio.create_task(daily_books_digest()), "cron", hour=7, minute=0, id="daily_books_digest"
    )
    scheduler.add_job(
        lambda: asyncio.create_task(synthetic_feed_drip_all()),
        "cron",
        minute=0,
        id="synthetic_feed_drip",
    )


def start_scheduler() -> None:
    register_jobs()
    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
