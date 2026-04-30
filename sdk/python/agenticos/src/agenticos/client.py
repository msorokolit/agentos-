"""Minimal Python client for AgenticOS."""

from __future__ import annotations

from typing import Any

import httpx


class AgenticOSClient:
    """Tiny synchronous + async client.

    Full surface area (agents, chat, knowledge, tools) lands in Phase 5 alongside
    the public API.
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": "agenticos-python-sdk/0.1.0"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def health(self) -> dict[str, Any]:
        with httpx.Client(timeout=self._timeout, headers=self._headers) as c:
            r = c.get(f"{self.base_url}/healthz")
            r.raise_for_status()
            return r.json()

    async def ahealth(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as c:
            r = await c.get(f"{self.base_url}/healthz")
            r.raise_for_status()
            return r.json()
