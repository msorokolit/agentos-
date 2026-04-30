"""Ping job — used by smoke tests."""

from __future__ import annotations

from typing import Any

from agenticos_shared.logging import get_logger

log = get_logger(__name__)


async def ping(ctx: dict[str, Any], message: str = "pong") -> dict[str, Any]:
    """Return the message echoed back; logs at INFO."""

    log.info("worker.ping", message=message)
    return {"ok": True, "message": message}
