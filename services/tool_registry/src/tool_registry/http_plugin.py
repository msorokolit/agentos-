"""HTTP / OpenAPI invoker.

The descriptor for an ``http`` tool looks like::

    {
        "endpoint": "https://api.example.com/v1/items",
        "method": "POST",          # default GET
        "headers": {"X-Api-Key": "{{env.MY_KEY}}"},  # interpolation supported in Phase 6
        "json_body_template": {"q": "{{args.query}}"},
        "query_template": {"limit": "{{args.limit}}"},
    }

For an ``openapi`` tool the descriptor *additionally* contains a parsed
``operation`` field with ``operationId``, ``method``, ``path``, and the
target ``server_url``.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from agenticos_shared.errors import ForbiddenError, ValidationError

_TEMPLATE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*}}")


def _resolve(value: Any, args: dict[str, Any], ctx: dict[str, Any]) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key.startswith("args."):
                return str(_lookup(args, key[len("args.") :]))
            if key.startswith("ctx."):
                return str(_lookup(ctx, key[len("ctx.") :]))
            return m.group(0)

        return _TEMPLATE.sub(repl, value)
    if isinstance(value, dict):
        return {k: _resolve(v, args, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, args, ctx) for v in value]
    return value


def _lookup(d: Any, dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
        if cur is None:
            return ""
    return cur


def _check_egress(host: str, allow: list[str]) -> None:
    if not allow:
        return
    h = host.lower()
    for entry in allow:
        e = entry.lower().strip()
        if not e:
            continue
        if e.startswith("*."):
            if h == e[2:] or h.endswith("." + e[2:]):
                return
        elif h == e:
            return
    raise ForbiddenError(f"egress to '{host}' not allowed", extras={"allow_hosts": allow})


async def invoke_http(
    descriptor: dict[str, Any], *, ctx: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    endpoint = descriptor.get("endpoint")
    if not endpoint:
        raise ValidationError("http tool descriptor missing 'endpoint'")
    method = (descriptor.get("method") or "GET").upper()
    headers = _resolve(descriptor.get("headers") or {}, args, ctx)
    json_body = (
        _resolve(descriptor["json_body_template"], args, ctx)
        if "json_body_template" in descriptor
        else None
    )
    query = _resolve(descriptor.get("query_template") or {}, args, ctx)

    settings = ctx.get("settings")
    timeout = float(getattr(settings, "invoke_timeout_seconds", 30.0) or 30.0)
    allow = list(getattr(settings, "egress_allow_hosts", []) or [])
    max_bytes = int(getattr(settings, "max_response_bytes", 64 * 1024) or 64 * 1024)

    host = urlparse(endpoint).hostname or ""
    _check_egress(host, allow)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.request(method, endpoint, headers=headers, json=json_body, params=query)
    body = r.content[:max_bytes]
    truncated = len(r.content) > max_bytes
    text: str | None
    try:
        text = body.decode(r.encoding or "utf-8", errors="replace")
    except Exception:
        text = None

    return {
        "status": r.status_code,
        "url": str(r.url),
        "text": text,
        "truncated": truncated,
        "bytes": len(body),
    }


async def invoke_openapi(
    descriptor: dict[str, Any], *, ctx: dict[str, Any], args: dict[str, Any]
) -> dict[str, Any]:
    op = descriptor.get("operation") or {}
    server_url = descriptor.get("server_url") or op.get("server_url")
    path = op.get("path")
    if not server_url or not path:
        raise ValidationError("openapi tool needs server_url + operation.path")
    full = urljoin(server_url.rstrip("/") + "/", path.lstrip("/"))
    new_descriptor = {
        "endpoint": full,
        "method": op.get("method", "GET"),
        "headers": descriptor.get("headers"),
        "json_body_template": descriptor.get("json_body_template"),
        "query_template": descriptor.get("query_template"),
    }
    return await invoke_http(new_descriptor, ctx=ctx, args=args)
