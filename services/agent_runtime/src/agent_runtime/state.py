"""Process-wide state for agent-runtime: NATS bus + proxies."""

from __future__ import annotations

from typing import Any

import nats
from agenticos_shared.logging import get_logger

from .proxies import KnowledgeProxy, LLMProxy, ToolProxy
from .settings import Settings

log = get_logger(__name__)


class _NatsBus:
    def __init__(self, url: str) -> None:
        self.url = url
        self._nc: Any | None = None

    async def connect(self) -> None:
        if self._nc is not None:
            return
        try:
            self._nc = await nats.connect(self.url, allow_reconnect=True, max_reconnect_attempts=-1)
            log.info("nats.connected", url=self.url)
        except Exception as exc:
            log.warning("nats.connect_failed", error=str(exc))

    async def publish(self, subject: str, payload: bytes) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.publish(subject, payload)
        except Exception as exc:
            log.warning("nats.publish_failed", error=str(exc), subject=subject)

    async def close(self) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.drain()
        except Exception:
            pass


_bus: _NatsBus | None = None
_llm: LLMProxy | None = None
_tools: ToolProxy | None = None
_knowledge: KnowledgeProxy | None = None


async def init_state(s: Settings) -> None:
    global _bus, _llm, _tools, _knowledge
    _bus = _NatsBus(s.nats_url)
    await _bus.connect()
    _llm = LLMProxy(s.llm_gateway_url)
    _tools = ToolProxy(s.tool_registry_url)
    _knowledge = KnowledgeProxy(s.knowledge_svc_url)


async def shutdown_state() -> None:
    if _bus is not None:
        await _bus.close()


def get_publish():
    if _bus is None:
        return None
    return _bus.publish


def get_proxies() -> tuple[LLMProxy, ToolProxy, KnowledgeProxy]:
    if _llm is None or _tools is None or _knowledge is None:
        s = Settings()
        return (
            LLMProxy(s.llm_gateway_url),
            ToolProxy(s.tool_registry_url),
            KnowledgeProxy(s.knowledge_svc_url),
        )
    return _llm, _tools, _knowledge
