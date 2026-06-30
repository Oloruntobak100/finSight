"""Shared secret auth for scheduled HTTP cron hooks."""

from fastapi import Header, HTTPException

from app.config import settings


def verify_cron_secret(x_cron_secret: str | None = Header(None, alias="X-Cron-Secret")) -> None:
    expected = (settings.cron_secret or settings.secret_key or "").strip()
    if not expected or (x_cron_secret or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
