import pytest

from worker.jobs.ping import ping


@pytest.mark.asyncio
async def test_ping_echoes() -> None:
    out = await ping({}, "hello")
    assert out == {"ok": True, "message": "hello"}
