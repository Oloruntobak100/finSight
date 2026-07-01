import pytest

from app import database


@pytest.mark.asyncio
async def test_run_db_retries_transient_connection_error(monkeypatch):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("ConnectionTerminated error_code:1, last_stream_id:69")
        return "ok"

    monkeypatch.setattr(database, "reset_supabase_client", lambda: None)
    result = await database.run_db(flaky)
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_run_db_does_not_retry_permanent_errors():
    def fail():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await database.run_db(fail)
