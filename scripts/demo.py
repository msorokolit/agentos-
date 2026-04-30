"""End-to-end demo (Definition of Done, PLAN §16).

Walks through the full happy path:

1. Authenticate as the seeded ``alice`` superuser using a session cookie
   that we mint locally with the same ``AGENTICOS_SECRET_KEY`` the
   running api-gateway is using.
2. Create a workspace.
3. Upload a tiny markdown document (RAG ingestion → embedding → ready).
4. Register a built-in tool (``http_get``, scope ``safe``).
5. Register a chat model alias if one isn't present (skipped if it is).
6. Create an agent with the tool bound + RAG enabled.
7. Run the agent with a prompt and print the final answer + citations.
8. Pull and pretty-print the audit log for the workspace.

Run after ``make dev && make seed`` so a real Ollama is reachable. Pass
``--mock`` to skip the actual /run step (still creates the agent, useful
in CI smoke tests where no model is downloaded).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin
from uuid import UUID, uuid4

import httpx

# Reuse the gateway's session encoder so we don't depend on a live OIDC.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api_gateway" / "src"))
from api_gateway.auth.session import SessionPayload, encode_session


def _mint_cookie(user_id: UUID, tenant_id: UUID, *, secret: str, ttl: int = 3600) -> str:
    now = int(time.time())
    return encode_session(
        SessionPayload(
            user_id=user_id,
            tenant_id=tenant_id,
            email="alice@agenticos.local",
            display_name="Alice",
            issued_at=now,
            expires_at=now + ttl,
        ),
        secret=secret,
    )


def _say(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8080"))
    p.add_argument("--secret", default=os.environ.get("AGENTICOS_SECRET_KEY", ""))
    p.add_argument("--user-id", required=True, help="alice's user UUID from the seed")
    p.add_argument("--tenant-id", required=True, help="acme tenant UUID from the seed")
    p.add_argument(
        "--workspace-slug",
        default=f"demo-{uuid4().hex[:6]}",
        help="slug for the demo workspace",
    )
    p.add_argument("--mock", action="store_true", help="skip the /run step")
    args = p.parse_args()

    if not args.secret:
        print("ERROR: AGENTICOS_SECRET_KEY required", file=sys.stderr)
        return 2

    cookie = _mint_cookie(UUID(args.user_id), UUID(args.tenant_id), secret=args.secret)
    cookies = {"agos_session": cookie}
    base = args.api.rstrip("/") + "/api/v1"

    with httpx.Client(timeout=120.0, cookies=cookies) as c:
        _say("/me")
        r = c.get(urljoin(base + "/", "me"))
        r.raise_for_status()
        me = r.json()
        print(f"   logged in as {me['email']}; superuser={me['is_superuser']}")

        _say("create workspace")
        r = c.post(
            urljoin(base + "/", "workspaces"),
            json={"name": "Demo", "slug": args.workspace_slug},
        )
        r.raise_for_status()
        ws = r.json()
        ws_id = ws["id"]
        print(f"   workspace {ws_id} ({ws['slug']})")

        _say("upload document")
        r = c.post(
            f"{base}/workspaces/{ws_id}/documents",
            files={
                "file": (
                    "founding.md",
                    b"# AgenticOS\n\nAgenticOS was started in 2026 as the first\n"
                    b"local-LLM-first agent platform for enterprises.\n",
                    "text/markdown",
                )
            },
        )
        r.raise_for_status()
        doc = r.json()
        print(f"   document {doc['id']} status={doc['status']} chunks={doc['chunk_count']}")

        _say("register http_get tool")
        builtins = c.get(f"{base}/builtins").json()
        http_get_descriptor = next(b for b in builtins if b["name"] == "http_get")
        r = c.post(
            f"{base}/workspaces/{ws_id}/tools",
            json={
                "name": "http_get",
                "kind": "builtin",
                "descriptor": http_get_descriptor,
                "scopes": ["safe"],
            },
        )
        r.raise_for_status()
        tool = r.json()
        print(f"   tool {tool['id']} ({tool['name']})")

        _say("ensure chat model alias")
        models = c.get(f"{base}/admin/models").json()
        chat_alias = next(
            (m["alias"] for m in models if m.get("kind") == "chat"),
            None,
        )
        if chat_alias is None:
            r = c.post(
                f"{base}/admin/models",
                json={
                    "alias": "chat-default",
                    "provider": "ollama",
                    "endpoint": os.environ.get("OLLAMA_URL", "http://ollama:11434"),
                    "model_name": os.environ.get("CHAT_MODEL", "qwen2.5:7b-instruct"),
                    "kind": "chat",
                },
            )
            r.raise_for_status()
            chat_alias = r.json()["alias"]
        print(f"   chat alias = {chat_alias}")

        _say("create agent")
        r = c.post(
            f"{base}/workspaces/{ws_id}/agents",
            json={
                "name": "Demo Agent",
                "slug": "demo-agent",
                "system_prompt": "You are concise and cite sources.",
                "model_alias": chat_alias,
                "tool_ids": [tool["id"]],
                "config": {"rag_enabled": True},
            },
        )
        r.raise_for_status()
        agent = r.json()
        print(f"   agent {agent['id']} ({agent['slug']})")

        if not args.mock:
            _say("run the agent")
            try:
                r = c.post(
                    f"{base}/workspaces/{ws_id}/agents/{agent['id']}/run",
                    json={"user_message": "When was AgenticOS founded?"},
                    timeout=300.0,
                )
                r.raise_for_status()
                out = r.json()
                print(f"   answer: {out['final_message']!r}")
                if out.get("citations"):
                    for i, ct in enumerate(out["citations"], start=1):
                        print(f"     [{i}] {ct.get('document_title')}")
            except httpx.HTTPStatusError as exc:
                print(f"   /run failed (model probably not pulled): {exc.response.text[:200]}")

        _say("audit log (last 10)")
        r = c.get(f"{base}/workspaces/{ws_id}/audit", params={"limit": 10})
        if r.status_code == 200:
            for row in r.json():
                print(
                    "   {when}  {actor:<25}  {action:<18}  {decision}".format(
                        when=row["created_at"],
                        actor=row.get("actor_email") or "-",
                        action=row["action"],
                        decision=row["decision"],
                    )
                )
        else:
            print(f"   audit fetch failed: {r.status_code}")

    print("\nDemo complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
