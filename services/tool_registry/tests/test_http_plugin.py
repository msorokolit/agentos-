"""HTTP / OpenAPI invoker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import respx
from agenticos_shared.errors import ForbiddenError
from tool_registry.http_plugin import invoke_http, invoke_openapi


@pytest.mark.asyncio
async def test_invoke_http_substitutes_template():
    settings = SimpleNamespace(
        egress_allow_hosts=[], invoke_timeout_seconds=5.0, max_response_bytes=4096
    )
    descriptor = {
        "endpoint": "https://api.example.com/items",
        "method": "POST",
        "headers": {"X-Q": "{{args.q}}"},
        "json_body_template": {"q": "{{args.q}}", "n": "{{args.n}}"},
    }
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.example.com/items").respond(200, json={"ok": 1})
        out = await invoke_http(descriptor, ctx={"settings": settings}, args={"q": "hello", "n": 3})
    body = route.calls[0].request.read().decode()
    headers = route.calls[0].request.headers
    import json as _json

    payload = _json.loads(body)
    assert payload == {"q": "hello", "n": "3"}  # numbers stringified by templating
    assert headers.get("x-q") == "hello"
    assert out["status"] == 200


@pytest.mark.asyncio
async def test_invoke_http_egress_blocks():
    settings = SimpleNamespace(
        egress_allow_hosts=["only.example.com"],
        invoke_timeout_seconds=5.0,
        max_response_bytes=1024,
    )
    with pytest.raises(ForbiddenError):
        await invoke_http(
            {"endpoint": "https://other.example.com/x"},
            ctx={"settings": settings},
            args={},
        )


@pytest.mark.asyncio
async def test_invoke_openapi_builds_full_url():
    settings = SimpleNamespace(
        egress_allow_hosts=[], invoke_timeout_seconds=5.0, max_response_bytes=1024
    )
    descriptor = {
        "server_url": "https://api.example.com/v1",
        "operation": {"path": "items/list", "method": "GET"},
    }
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.example.com/v1/items/list").respond(200, json={"ok": True})
        out = await invoke_openapi(descriptor, ctx={"settings": settings}, args={})
    assert out["status"] == 200
