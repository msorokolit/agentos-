"""http_get built-in tool.

* Honours the egress allow-list (``settings.egress_allow_hosts``).
* Truncates body to ``max_response_bytes``.
* Drops Set-Cookie and Authorization headers from the response payload.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from agenticos_shared.errors import ForbiddenError, ValidationError

_DROP_RESPONSE_HEADERS = {"set-cookie", "authorization"}


async def http_get(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    settings = ctx.get("settings")
    url = args.get("url")
    if not url:
        raise ValidationError("url is required")
    headers = args.get("headers") or {}

    host = urlparse(url).hostname or ""
    allow = list(getattr(settings, "egress_allow_hosts", []) or [])
    if allow and not _host_allowed(host, allow):
        raise ForbiddenError(
            f"egress to '{host}' not allowed",
            extras={"allow_hosts": allow},
        )

    timeout = float(getattr(settings, "invoke_timeout_seconds", 30.0) or 30.0)
    max_bytes = int(getattr(settings, "max_response_bytes", 64 * 1024) or 64 * 1024)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url, headers=headers)

    body = r.content[:max_bytes]
    truncated = len(r.content) > max_bytes
    safe_headers = {k: v for k, v in r.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}

    text: str | None
    try:
        text = body.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        text = None

    return {
        "status": r.status_code,
        "url": str(r.url),
        "headers": safe_headers,
        "text": text,
        "truncated": truncated,
        "bytes": len(body),
    }


def _host_allowed(host: str, allow: list[str]) -> bool:
    h = host.lower()
    for entry in allow:
        e = entry.lower().strip()
        if not e:
            continue
        if e.startswith("*."):
            if h == e[2:] or h.endswith("." + e[2:]):
                return True
        elif h == e:
            return True
    return False
