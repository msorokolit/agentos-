"""Token-level streaming + thoughts events in the ReAct graph."""

from __future__ import annotations

from uuid import uuid4

import pytest
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


def _delta_chunk(content: str) -> dict:
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion.chunk",
        "model": "chat-default",
        "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }


@pytest.mark.asyncio
async def test_streaming_emits_token_level_deltas(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    llm = StubLLMCls(
        stream_chunks=[
            [
                {"choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                _delta_chunk("Hi "),
                _delta_chunk("there"),
                _delta_chunk("!"),
            ]
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
            max_iterations=2,
        )
    ]
    deltas = [e for e in events if e.type == "delta"]
    contents = [d.payload["content"] for d in deltas]
    assert contents == ["Hi ", "there", "!"]
    final = events[-1]
    assert final.type == "final"
    assert final.payload["content"] == "Hi there!"
    # No fall-through to non-streaming ``chat()`` happened.
    assert llm.calls == []
    assert len(llm.stream_calls) == 1


@pytest.mark.asyncio
async def test_streaming_skipped_when_tools_bound(StubLLMCls, StubToolsCls, StubKnowledgeCls):
    """When tools are registered we need the whole assistant message in
    one piece, so the graph must NOT use streaming."""

    tool_id = str(uuid4())
    llm = StubLLMCls(
        responses=[
            {
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {},
            }
        ],
    )
    tools = StubToolsCls(
        descriptors=[
            {
                "id": tool_id,
                "name": "echo",
                "kind": "builtin",
                "enabled": True,
                "description": "echo",
                "descriptor": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    events = [
        e
        async for e in run_react(
            agent=_agent(tool_ids=[tool_id]),
            session_id=uuid4(),
            user_message="hi",
            history=[],
            llm=llm,
            tools=tools,
            knowledge=StubKnowledgeCls(),
            max_iterations=2,
        )
    ]
    assert events[-1].type == "final"
    assert llm.stream_calls == []  # never streamed
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_thoughts_emitted_when_assistant_narrates_before_tool_call(
    StubLLMCls, StubToolsCls, StubKnowledgeCls
):
    """The model can narrate before a tool call; that text should be a
    ``thoughts`` event, not the final answer."""

    tool_id = str(uuid4())
    llm = StubLLMCls(
        responses=[
            # Round 1: thoughts + tool call.
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I'll fetch the weather first.",
                            "tool_calls": [
                                {
                                    "id": "tc1",
                                    "type": "function",
                                    "function": {
                                        "name": "echo",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {},
            },
            # Round 2: clean answer.
            {
                "choices": [{"message": {"role": "assistant", "content": "It's sunny."}}],
                "usage": {},
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
                "description": "echo",
                "descriptor": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    events = [
        e
        async for e in run_react(
            agent=_agent(tool_ids=[tool_id]),
            session_id=uuid4(),
            user_message="weather?",
            history=[],
            llm=llm,
            tools=tools,
            knowledge=StubKnowledgeCls(),
            max_iterations=4,
        )
    ]
    types = [e.type for e in events]
    # The narration becomes a thoughts event before the tool_call.
    assert "thoughts" in types
    thoughts_idx = types.index("thoughts")
    tool_call_idx = types.index("tool_call")
    assert thoughts_idx < tool_call_idx
    # And the final answer is the second-round message, not the narration.
    assert events[-1].type == "final"
    assert events[-1].payload["content"] == "It's sunny."
