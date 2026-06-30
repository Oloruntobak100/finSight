"""Smoke tests for Books router imports used at runtime."""

import inspect

from app.routers import books


def test_books_router_resolves_sync_chart_of_accounts():
    source = inspect.getsource(books.list_coa)
    assert "sync_chart_of_accounts" in source
    assert hasattr(books, "sync_chart_of_accounts")
