"""ReAct policy_check node — gate every tool call through OPA."""

from __future__ import annotations

from uuid import uuid4

import pytest
import respx
from agent_runtime.graphs.react import run_react
from agent_runtime.schemas import AgentSpec


def _agent(**kw) -> AgentSpec:
    return AgentSpec(
        id=uuid4(),
        workspace_id=uuid4(),
        name="A",
        system_prompt="be helpful",
        model_alias="chat-default",
        graph_kind="react",
        config=kw.get("config", {}),
        tool_ids=kw.get("tool_ids", []),
    )


def _tool_descriptor(tool_id: str, *, scopes: list[str] | None = None) -> dict:
    return {
        "id": tool_id,
        "name": "echo",
        "kind": "builtin",
        "enabled": True,
        "description": "echo",
        "scopes": scopes or [],
        "descriptor": {
            "name": "echo",
            "description": "echo",
            "parameters": {
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        },
    }


@pytest.mark.asyncio
async def test_deny_blocks_invocation_and_emits_deny_event(
    StubLLMCls, StubToolsCls, StubKnowledgeCls
):
    tool_id = str(uuid4())
    llm = StubLLMCls(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": '{"x":1}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "I cannot do that."}}],
                "usage": {},
            },
        ]
    )
    tools = StubToolsCls(descriptors=[_tool_descriptor(tool_id)])

    with respx.mock(assert_all_called=True) as router:
        router.post("http://opa:8181/v1/data/agenticos/tool_access").respond(
            json={"result": {"allow": False, "reason": "no scope match"}}
        )
        events = [
            ev
            async for ev in run_react(
                agent=_agent(tool_ids=[tool_id]),
                session_id=uuid4(),
                user_message="run echo",
                history=[],
                llm=llm,
                tools=tools,
                knowledge=StubKnowledgeCls(),
                max_iterations=3,
                opa_url="http://opa:8181",
                principal_roles=["member"],
            )
        ]

    types = [e.type for e in events]
    assert "tool_call" in types
    # tool_result with decision=deny is emitted, NOT a real tool invocation.
    deny_results = [e for e in events if e.type == "tool_result"]
    assert len(deny_results) == 1
    assert deny_results[0].payload["ok"] is False
    assert deny_results[0].payload.get("decision") == "deny"
    assert "policy denied" in deny_results[0].payload["error"]
    # The model never reached the actual tool invoker.
    assert tools.invoked == []
    # And the agent finalised cleanly.
    assert events[-1].type == "final"
    assert events[-1].payload["content"] == "I cannot do that."


@pytest.mark.asyncio
async def test_allow_runs_tool_and_finalises(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    tool_id = str(uuid4())
    llm = StubLLMCls(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": '{"x":1}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "Done."}}],
                "usage": {},
            },
        ]
    )
    tools = StubToolsCls(descriptors=[_tool_descriptor(tool_id, scopes=["safe"])])

    with respx.mock(assert_all_called=True) as router:
        router.post("http://opa:8181/v1/data/agenticos/tool_access").respond(
            json={"result": {"allow": True}}
        )
        events = [
            ev
            async for ev in run_react(
                agent=_agent(tool_ids=[tool_id]),
                session_id=uuid4(),
                user_message="run echo",
                history=[],
                llm=llm,
                tools=tools,
                knowledge=StubKnowledgeCls(),
                max_iterations=3,
                opa_url="http://opa:8181",
                principal_roles=["builder"],
            )
        ]
    assert tools.invoked == [{"name": "echo", "args": {"x": 1}}]
    assert events[-1].type == "final"
    assert events[-1].payload["content"] == "Done."


@pytest.mark.asyncio
async def test_no_opa_url_skips_policy_check(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    """Backwards-compatible: callers that don't pass ``opa_url`` get the
    pre-policy behaviour (every tool runs)."""

    tool_id = str(uuid4())
    llm = StubLLMCls(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tc",
                                    "type": "function",
                                    "function": {"name": "echo", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {},
            },
        ]
    )
    tools = StubToolsCls(descriptors=[_tool_descriptor(tool_id)])

    events = [
        ev
        async for ev in run_react(
            agent=_agent(tool_ids=[tool_id]),
            session_id=uuid4(),
            user_message="x",
            history=[],
            llm=llm,
            tools=tools,
            knowledge=StubKnowledgeCls(),
            max_iterations=3,
            opa_url=None,
        )
    ]
    assert tools.invoked == [{"name": "echo", "args": {}}]
    assert events[-1].type == "final"
