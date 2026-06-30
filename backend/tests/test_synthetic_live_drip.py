"""Tests for synthetic live feed scheduling."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_start_live_feed_runs_immediate_drip():
    now = datetime.now(timezone.utc)
    profile = {
        "user_id": "user-1",
        "account_id": "acct-1",
        "live_interval_hours": 6,
        "persona_type": "small_business",
        "persona_config": {},
    }
    drip_result = {"created": 12, "next_live_run_at": (now).isoformat()}

    with patch(
        "app.services.synthetic_feed_service.get_or_create_profile",
        new=AsyncMock(side_effect=[profile, {**profile, "live_feed_enabled": True}]),
    ), patch(
        "app.services.synthetic_feed_service._upsert_profile_row",
        new=AsyncMock(return_value={**profile, "live_feed_enabled": True}),
    ), patch(
        "app.services.synthetic_feed_service.run_live_drip",
        new=AsyncMock(return_value=drip_result),
    ) as drip_mock, patch(
        "app.services.synthetic_feed_service._schedule_live_drip_retry",
        new=AsyncMock(),
    ):
        from app.services.synthetic_feed_service import start_live_feed

        result = await start_live_feed("user-1", "acct-1")

    drip_mock.assert_awaited_once()
    assert result["first_drip"]["created"] == 12
    assert result["profile"]["live_feed_enabled"] is True


@pytest.mark.asyncio
async def test_run_scheduled_live_drips_processes_due_profiles():
    due_profile = {
        "id": "prof-1",
        "user_id": "user-1",
        "account_id": "acct-1",
        "live_feed_enabled": True,
    }

    with patch(
        "app.services.synthetic_feed_service.synthetic_feed_allowed",
        return_value=True,
    ), patch("app.services.synthetic_feed_service.get_supabase"), patch(
        "app.services.synthetic_feed_service.run_db",
        new=AsyncMock(return_value=type("R", (), {"data": [due_profile]})()),
    ), patch(
        "app.services.synthetic_feed_service.run_live_drip",
        new=AsyncMock(return_value={"created": 5}),
    ) as drip_mock, patch(
        "app.services.synthetic_feed_service._schedule_live_drip_retry",
        new=AsyncMock(),
    ):
        from app.services.synthetic_feed_service import run_scheduled_live_drips

        result = await run_scheduled_live_drips()

    assert result["processed"] == 1
    assert result["failed"] == 0
    drip_mock.assert_awaited_once_with(due_profile)


@pytest.mark.asyncio
async def test_cron_live_drip_requires_secret():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    res = client.post("/synthetic-feed/cron/live-drip")
    assert res.status_code == 401
