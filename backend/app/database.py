import asyncio
import logging
from functools import partial
from typing import Any, Callable, TypeVar

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

_client: Client | None = None
_DB_MAX_ATTEMPTS = 3


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("Supabase URL and service role key must be configured")
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


def reset_supabase_client() -> None:
    """Drop cached client so the next call opens a fresh HTTP connection."""
    global _client
    _client = None


def _is_transient_db_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    transient_markers = (
        "connectionterminated",
        "connection reset",
        "remoteprotocolerror",
        "readtimeout",
        "connecterror",
        "broken pipe",
        "server disconnected",
    )
    return any(marker in msg for marker in transient_markers)


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run sync Supabase client calls in a thread pool with transient retry."""
    last_exc: BaseException | None = None
    for attempt in range(1, _DB_MAX_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(partial(fn, *args, **kwargs))
        except Exception as exc:
            last_exc = exc
            if attempt >= _DB_MAX_ATTEMPTS or not _is_transient_db_error(exc):
                raise
            logger.warning(
                "Transient Supabase error (attempt %d/%d): %s",
                attempt,
                _DB_MAX_ATTEMPTS,
                exc,
            )
            reset_supabase_client()
            await asyncio.sleep(0.25 * attempt)
    assert last_exc is not None
    raise last_exc
