"""ReAct graph tests with all proxies stubbed."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agent_runtime.graphs.react import run_react
from agent_runtime.runner import run_agent
from agent_runtime.schemas import AgentSpec


def _agent(workspace_id=None, **kw) -> AgentSpec:
    return AgentSpec(
        id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        name="A",
        system_prompt=kw.get("system_prompt", "you are helpful"),
        model_alias="chat-default",
        graph_kind="react",
        config=kw.get("config", {}),
        tool_ids=kw.get("tool_ids", []),
        rag_collection_id=kw.get("rag_collection_id"),
    )


@pytest.mark.asyncio
async def test_react_finalises_without_tool_calls(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    llm = StubLLMCls(
        [
            {
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello!"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            }
        ]
    )
    events = [
        e
        async for e in run_react(
            agent=_agent(),
            session_id=uuid4(),
            user_message="hi",
            history=[],
            llm=llm,
            tools=StubToolsCls(),
            knowledge=StubKnowledgeCls(),
            max_iterations=3,
        )
    ]
    types = [e.type for e in events]
    assert "step" in types and types[-1] == "final"
    assert events[-1].payload["content"] == "Hello!"
    assert events[-1].payload["iterations"] == 1
    assert "tools" not in llm.calls[0]


@pytest.mark.asyncio
async def test_react_runs_tool_then_finalises(StubLLMCls, StubToolsCls, StubKnowledgeCls):
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
                                    "function": {"name": "echo", "arguments": '{"x": 1}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
            {
                "choices": [{"message": {"role": "assistant", "content": "Done."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
            },
        ]
    )
    tools = StubToolsCls(
        descriptors=[
            {
                "id": tool_id,
                "name": "echo",
                "kind": "builtin",
                "enabled": True,
                "description": "echo the args",
                "descriptor": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}},
                },
            }
        ]
    )
    spec = _agent(tool_ids=[tool_id])
    events = [
        e
        async for e in run_react(
            agent=spec,
            session_id=uuid4(),
            user_message="run the tool",
            history=[],
            llm=llm,
            tools=tools,
            knowledge=StubKnowledgeCls(),
            max_iterations=4,
        )
    ]
    types = [e.type for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "final"
    assert events[-1].payload["content"] == "Done."
    assert tools.invoked == [{"name": "echo", "args": {"x": 1}}]
    assert llm.calls[0]["tools"][0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_react_emits_citations_and_uses_rag_context(
    StubLLMCls, StubToolsCls, StubKnowledgeCls
):
    llm = StubLLMCls(
        [
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Per [1] the answer is 42."}}
                ],
                "usage": {},
            }
        ]
    )
    knowledge = StubKnowledgeCls(
        hits=[
            {
                "chunk_id": str(uuid4()),
                "document_id": str(uuid4()),
                "document_title": "Hitchhiker's Guide",
                "ord": 0,
                "text": "The answer is 42.",
                "score": 0.9,
                "meta": {},
            }
        ]
    )
    spec = _agent(config={"rag_enabled": True})
    events = [
        e
        async for e in run_react(
            agent=spec,
            session_id=uuid4(),
            user_message="what is the answer?",
            history=[],
            llm=llm,
            tools=StubToolsCls(),
            knowledge=knowledge,
            max_iterations=2,
        )
    ]
    assert any(e.type == "citations" for e in events)
    assert events[-1].type == "final"
    assert events[-1].payload["citations"]
    sys_msgs = [m for m in llm.calls[0]["messages"] if m["role"] == "system"]
    assert any("Hitchhiker" in m["content"] for m in sys_msgs)


@pytest.mark.asyncio
async def test_react_caps_iterations(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    looper = {
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
    }
    llm = StubLLMCls([dict(looper) for _ in range(10)])
    tools = StubToolsCls(
        descriptors=[
            {
                "id": "t-1",
                "name": "echo",
                "enabled": True,
                "kind": "builtin",
                "description": "echo",
                "descriptor": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    spec = _agent(tool_ids=["t-1"])
    events = [
        e
        async for e in run_react(
            agent=spec,
            session_id=uuid4(),
            user_message="x",
            history=[],
            llm=llm,
            tools=tools,
            knowledge=StubKnowledgeCls(),
            max_iterations=2,
        )
    ]
    assert events[-1].type == "error"
    assert "max_iterations" in events[-1].payload["message"]


@pytest.mark.asyncio
async def test_run_agent_collects_result(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    llm = StubLLMCls(
        [
            {
                "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }
        ]
    )
    spec = _agent()
    result, events = await run_agent(
        agent=spec,
        session_id=uuid4(),
        user_message="hello",
        history=[],
        llm=llm,
        tools=StubToolsCls(),
        knowledge=StubKnowledgeCls(),
        max_iterations=2,
    )
    assert result.final_message == "Hi"
    assert result.iterations == 1
    assert result.tokens_in == 3
    assert result.error is None
