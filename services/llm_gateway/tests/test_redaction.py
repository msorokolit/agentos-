"""End-to-end: outbound payload PII scrub when LLM_GATEWAY_REDACT_OUTBOUND=true."""

from __future__ import annotations

import json

import respx


def _register_chat(client) -> None:
    r = client.post(
        "/admin/models",
        json={
            "alias": "chat-default",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "qwen",
            "kind": "chat",
        },
    )
    assert r.status_code == 201, r.text


def test_redact_outbound_when_enabled(monkeypatch, app, client):
    """When the flag is set, the message body forwarded to the provider
    must already have PII swapped for ``[REDACTED:*]`` tags."""

    monkeypatch.setenv("LLM_GATEWAY_REDACT_OUTBOUND", "true")
    from llm_gateway import settings as st

    st.get_settings.cache_clear()

    _register_chat(client)

    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://ollama:11434/api/chat").respond(
            json={
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 1,
                "eval_count": 1,
            }
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "chat-default",
                "messages": [{"role": "user", "content": "Email me at alice@example.com"}],
            },
        )
    assert r.status_code == 200, r.text

    sent = json.loads(route.calls[0].request.read())
    forwarded = sent["messages"][0]["content"]
    assert "alice@example.com" not in forwarded
    assert "[REDACTED:email]" in forwarded


def test_no_redact_by_default(client):
    _register_chat(client)
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://ollama:11434/api/chat").respond(
            json={
                "message": {"role": "assistant", "content": "ok"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 1,
                "eval_count": 1,
            }
        )
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "chat-default",
                "messages": [{"role": "user", "content": "Email me at alice@example.com"}],
            },
        )
    assert r.status_code == 200
    sent = json.loads(route.calls[0].request.read())
    assert "alice@example.com" in sent["messages"][0]["content"]
