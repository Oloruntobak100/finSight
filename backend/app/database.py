import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

from supabase import Client, create_client

from app.config import settings

T = TypeVar("T")

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("Supabase URL and service role key must be configured")
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run sync Supabase client calls in a thread pool."""
    return await asyncio.to_thread(partial(fn, *args, **kwargs))
