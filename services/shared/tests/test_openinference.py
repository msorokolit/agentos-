"""OpenInference span attribute helpers.

We capture spans with an in-memory exporter rather than a no-op tracer
so we can assert the conventional attribute names actually got set.
"""

from __future__ import annotations

import pytest
from agenticos_shared import openinference as oi
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


@pytest.fixture
def memory_tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter, provider.get_tracer("test")
    exporter.shutdown()


def test_annotate_llm_call_sets_canonical_keys(memory_tracer):
    exporter, tracer = memory_tracer
    with tracer.start_as_current_span("chat-completions"):
        oi.annotate_llm_call(
            provider="ollama",
            model="qwen2.5:7b",
            alias="chat-default",
            kind="chat",
            invocation_parameters={"temperature": 0.2, "max_tokens": 64},
            input_messages=[{"role": "user", "content": "hi"}],
            output_text="hello",
            prompt_tokens=4,
            completion_tokens=2,
            workspace_id="ws-1",
        )
    span = exporter.get_finished_spans()[0]
    a = span.attributes
    assert a[oi.OPENINFERENCE_SPAN_KIND] == "LLM"
    assert a[oi.LLM_PROVIDER] == "ollama"
    assert a[oi.LLM_MODEL_NAME] == "qwen2.5:7b"
    assert a["llm.alias"] == "chat-default"
    assert a[oi.LLM_TOKEN_COUNT_PROMPT] == 4
    assert a[oi.LLM_TOKEN_COUNT_COMPLETION] == 2
    assert a[oi.LLM_TOKEN_COUNT_TOTAL] == 6
    assert "temperature" in a[oi.LLM_INVOCATION_PARAMETERS]
    assert a[oi.LLM_OUTPUT_MESSAGES] == "hello"


def test_annotate_embedding_uses_embedding_kind(memory_tracer):
    exporter, tracer = memory_tracer
    with tracer.start_as_current_span("embed"):
        oi.annotate_llm_call(
            provider="ollama",
            model="nomic",
            alias="embed-default",
            kind="embedding",
            prompt_tokens=10,
            completion_tokens=0,
        )
    a = exporter.get_finished_spans()[0].attributes
    assert a[oi.OPENINFERENCE_SPAN_KIND] == "EMBEDDING"


def test_annotate_tool_call_records_inputs_and_outputs(memory_tracer):
    exporter, tracer = memory_tracer
    with tracer.start_as_current_span("tool"):
        oi.annotate_tool_call(
            tool_name="http_get",
            tool_kind="builtin",
            args={"url": "https://example.com"},
            result={"status": 200},
            ok=True,
            description="HTTP GET",
        )
    a = exporter.get_finished_spans()[0].attributes
    assert a[oi.OPENINFERENCE_SPAN_KIND] == "TOOL"
    assert a[oi.TOOL_NAME] == "http_get"
    assert a["tool.kind"] == "builtin"
    assert a["tool.ok"] is True
    assert "https://example.com" in a[oi.TOOL_INPUT]
    assert "200" in a[oi.TOOL_OUTPUT]


def test_annotate_retrieval_truncates_huge_docs(memory_tracer):
    exporter, tracer = memory_tracer
    docs = [{"id": str(i), "title": "x" * 1000} for i in range(50)]
    with tracer.start_as_current_span("rag"):
        oi.annotate_retrieval(query="huge", documents=docs)
    a = exporter.get_finished_spans()[0].attributes
    assert a[oi.OPENINFERENCE_SPAN_KIND] == "RETRIEVER"
    assert a["retrieval.documents.count"] == 50
    # 4096-char cap with the trailing marker.
    assert a[oi.RETRIEVAL_DOCUMENTS].endswith("<truncated>")


def test_helpers_are_safe_without_active_span():
    # No active span — must not raise. We don't touch the tracer provider
    # because OTel only allows setting it once per process.
    oi.annotate_llm_call(provider="x", model="y", alias="z", kind="chat", prompt_tokens=0)
    oi.annotate_tool_call(tool_name="t", tool_kind="builtin", ok=True)
    oi.annotate_agent_run(agent_name="a", session_id="s")
