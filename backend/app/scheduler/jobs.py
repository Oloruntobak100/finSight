import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.scheduler.tasks import nightly_forecast_all, nightly_metrics_all, nightly_sync_all

scheduler = AsyncIOScheduler()


def register_jobs() -> None:
    scheduler.add_job(lambda: asyncio.create_task(nightly_sync_all()), "cron", hour=2, minute=0, id="nightly_sync")
    scheduler.add_job(
        lambda: asyncio.create_task(nightly_metrics_all()), "cron", hour=3, minute=0, id="nightly_metrics"
    )
    scheduler.add_job(
        lambda: asyncio.create_task(nightly_forecast_all()), "cron", hour=3, minute=30, id="nightly_forecast"
    )


def start_scheduler() -> None:
    register_jobs()
    if not scheduler.running:
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown()
