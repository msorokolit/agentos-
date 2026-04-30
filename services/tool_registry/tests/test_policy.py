"""Policy client unit tests (offline = test default-allow)."""

from __future__ import annotations

import pytest
import respx
from tool_registry.policy import PolicyClient, decide_tool_access


@pytest.mark.asyncio
async def test_offline_in_test_env_defaults_allow(monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    client = PolicyClient(opa_url="http://nope:9999")
    allow, reason = await decide_tool_access(
        client=client,
        principal_roles=["builder"],
        workspace_ids=["00000000-0000-0000-0000-000000000001"],
        tool_id="t",
        tool_scopes=[],
    )
    assert allow is True
    assert reason == "opa_offline_test_default_allow"


@pytest.mark.asyncio
async def test_offline_in_prod_fails_closed(monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "production")
    client = PolicyClient(opa_url="http://nope:9999")
    allow, _ = await decide_tool_access(
        client=client,
        principal_roles=["builder"],
        workspace_ids=["00000000-0000-0000-0000-000000000001"],
        tool_id="t",
        tool_scopes=[],
    )
    assert allow is False


@pytest.mark.asyncio
async def test_opa_returns_allow_dict():
    client = PolicyClient(opa_url="http://opa:8181")
    with respx.mock() as router:
        router.post("http://opa:8181/v1/data/agenticos/tool_access").respond(
            json={"result": {"allow": True}}
        )
        allow, _ = await decide_tool_access(
            client=client,
            principal_roles=["admin"],
            workspace_ids=["00000000-0000-0000-0000-000000000001"],
            tool_id="t",
            tool_scopes=["safe"],
        )
    assert allow is True


@pytest.mark.asyncio
async def test_opa_returns_allow_bool():
    client = PolicyClient(opa_url="http://opa:8181")
    with respx.mock() as router:
        router.post("http://opa:8181/v1/data/agenticos/tool_access").respond(json={"result": False})
        allow, _ = await decide_tool_access(
            client=client,
            principal_roles=["viewer"],
            workspace_ids=["00000000-0000-0000-0000-000000000001"],
            tool_id="t",
            tool_scopes=[],
        )
    assert allow is False
