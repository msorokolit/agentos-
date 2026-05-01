# API

Live OpenAPI is served by the running api-gateway. The summary below
tracks the API surface as it lands phase by phase.

## Live OpenAPI

Once `make dev` is running:

- Swagger UI:  http://localhost:8080/docs
- Raw JSON:    http://localhost:8080/openapi.json

## Authentication

Browsers authenticate via OIDC against the configured IdP (Keycloak in
dev). After a successful callback, the api-gateway sets a signed
HS256 JWT cookie called `agos_session` (HttpOnly, SameSite=Lax, 12h TTL).

SDKs and machine clients can also pass the session token as
`Authorization: Bearer <token>`.

## Endpoints (Phase 0–1)

### Health (every service)

| Method | Path        | Description |
|--------|-------------|-------------|
| GET    | `/healthz`  | Liveness probe |
| GET    | `/readyz`   | Readiness probe |
| GET    | `/version`  | Service version |

### Auth (api-gateway)

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/v1/auth/oidc/login` | Begin OIDC flow. Use `?return_to=URL` to choose post-login redirect; `?json=true` returns the URL instead of 302. |
| GET    | `/api/v1/auth/oidc/callback` | OIDC callback (set as `OIDC_REDIRECT_URI`). Sets the session cookie and 302s to `return_to` (or `WEB_UI_URL`). |
| POST   | `/api/v1/auth/logout` | Clears the session cookie. |

### Me

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/v1/me` | Current user, tenant, workspace memberships and roles. |

### Workspaces

| Method | Path | Permission |
|--------|------|------------|
| GET    | `/api/v1/workspaces` | authenticated |
| POST   | `/api/v1/workspaces` | authenticated → caller becomes `owner` |
| GET    | `/api/v1/workspaces/{id}` | `workspace:read` |
| PATCH  | `/api/v1/workspaces/{id}` | `workspace:write` (admin+) |
| DELETE | `/api/v1/workspaces/{id}` | `workspace:delete` (owner) |

### Members

| Method | Path | Permission |
|--------|------|------------|
| GET    | `/api/v1/workspaces/{id}/members` | `member:read` |
| POST   | `/api/v1/workspaces/{id}/members` | `member:write` (admin+); only owners may add owners |
| PATCH  | `/api/v1/workspaces/{id}/members/{user_id}` | `member:write`; owners-only for owner role changes |
| DELETE | `/api/v1/workspaces/{id}/members/{user_id}` | `member:write`; cannot remove the last owner |

## Error format

All non-2xx responses use **RFC-7807 problem+json**:

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "code": "forbidden",
  "detail": "role 'member' insufficient for 'workspace:write'",
  "instance": "/api/v1/workspaces/.../"
}
```

## Audit events

Every login, logout, and mutating workspace/member action emits an
`AuditEvent` to NATS subject `audit.events` and writes a row to the
`audit_event` table. Inspect from psql:

```sql
SELECT created_at, action, decision, actor_email, resource_id
FROM audit_event ORDER BY created_at DESC LIMIT 20;
```

## Phase 2 — LLM gateway

### Models admin (api-gateway → llm-gateway proxy)

All routes require `admin` or `owner` in any workspace (or superuser).

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/api/v1/admin/models` | List registered models |
| POST   | `/api/v1/admin/models` | Register a model (alias, provider, endpoint, model_name, kind) |
| PATCH  | `/api/v1/admin/models/{id}` | Update endpoint / model_name / capabilities / enabled |
| DELETE | `/api/v1/admin/models/{id}` | De-register a model |
| POST   | `/api/v1/admin/models/{id}/test` | Ping the upstream provider, return latency |

Audit actions emitted: `model.create`, `model.update`, `model.delete`.

### Inference (llm-gateway, OpenAI-compatible)

These endpoints are exposed by the **llm-gateway** service directly (port
8081). The api-gateway will proxy them in Phase 5; for now agents and
internal callers hit the gateway directly.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | OpenAI-shaped chat. Set `stream: true` for SSE. `model` is the **alias** (not the upstream model name). |
| POST | `/v1/embeddings` | OpenAI-shaped embeddings. |

Quotas: per-workspace daily token budget + RPM, enforced via Redis.
Configure with `DAILY_TOKEN_BUDGET_PER_WORKSPACE` and `RPM_PER_WORKSPACE`
env vars.

Token usage is recorded in the `token_usage` table for every call.

## Phase 3 — Knowledge

All routes are workspace-scoped and require the standard RBAC permissions.

| Method | Path | Permission |
|--------|------|------------|
| GET    | `/api/v1/workspaces/{id}/collections` | `document:read` |
| POST   | `/api/v1/workspaces/{id}/collections` | `document:write` (builder+) |
| GET    | `/api/v1/workspaces/{id}/documents` | `document:read` |
| POST   | `/api/v1/workspaces/{id}/documents` (multipart) | `document:write` |
| POST   | `/api/v1/workspaces/{id}/documents?async_ingest=true` (multipart) ⇒ **202** + job_id | `document:write` |
| GET    | `/api/v1/workspaces/{id}/documents/{doc_id}/status` | `document:read` |
| DELETE | `/api/v1/workspaces/{id}/documents/{doc_id}` | `document:write` |
| GET    | `/api/v1/documents/{document_id}` (top-level) | `document:read` on its workspace |
| POST   | `/api/v1/workspaces/{id}/search` | `document:read` |
| POST   | `/api/v1/collections/{collection_id}/search` (top-level) | `document:read` on its workspace |

Search request body:
```json
{ "query": "what is X?", "top_k": 8, "collection_id": "<uuid>?" }
```

Search response:
```json
{
  "query": "what is X?",
  "hits": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "document_title": "Whitepaper.pdf",
      "ord": 12,
      "text": "...chunk text...",
      "score": 0.123,
      "meta": {}
    }
  ]
}
```

On PostgreSQL we use `pgvector` (cosine ivfflat) **and** a generated
`tsvector` GIN index, fused via reciprocal-rank fusion. On SQLite (tests)
we fall back to in-Python cosine + keyword counting.

Audit actions: `collection.create`, `document.upload`, `document.delete`.

## Phase 4 — Tools

| Method | Path | Permission |
|--------|------|------------|
| GET    | `/api/v1/builtins` | authenticated |
| GET    | `/api/v1/workspaces/{id}/tools` | `tool:read` (member+) |
| POST   | `/api/v1/workspaces/{id}/tools` | `tool:write` (builder+) |
| PATCH  | `/api/v1/workspaces/{id}/tools/{tool_id}` | `tool:write` |
| DELETE | `/api/v1/workspaces/{id}/tools/{tool_id}` | `tool:write` |
| POST   | `/api/v1/workspaces/{id}/tools/{tool_id}/invoke` | `tool:read` |

### Tool kinds

| Kind | Descriptor shape |
|------|------------------|
| `builtin` | `{ name, description, parameters: <JSON-Schema> }` — name must match a shipped built-in (`http_get`, `rag_search`). |
| `http`    | `{ endpoint, method, headers, json_body_template, query_template }` — `{{args.x}}` and `{{ctx.x}}` interpolation supported. |
| `openapi` | `{ server_url, operation: { path, method }, ... }` — translated to `endpoint` at invoke time. |
| `mcp`     | `{ endpoint, headers? }` — JSON-RPC over HTTP/SSE; calls `tools/call` with `{name, arguments}`. |

### Built-ins

* `http_get { url, headers? }` — egress allow-list, drops Set-Cookie & Authorization, truncates body.
* `rag_search { query, top_k?, collection_id? }` — hybrid search via knowledge-svc; per-hit text capped.

### OPA policy

The Rego bundle in `policies/tool_access.rego` decides **allow / deny**.
The default is deny; rules let workspace admins/builders use any
agent-bound tool, and members invoke any tool tagged `safe`.

In **test** mode (`AGENTICOS_ENV=test`) we default-allow if OPA is
unreachable. In **prod** we fail-closed.

Audit actions: `tool.create`, `tool.update`, `tool.delete`, `tool.invoke`.

## Phase 5 — Agents + chat

| Method | Path | Permission |
|--------|------|------------|
| GET    | `/api/v1/workspaces/{id}/agents` | `agent:read` |
| POST   | `/api/v1/workspaces/{id}/agents` | `agent:write` (builder+) |
| PATCH  | `/api/v1/workspaces/{id}/agents/{agent_id}` | `agent:write` |
| DELETE | `/api/v1/workspaces/{id}/agents/{agent_id}` | `agent:delete` (admin+) |
| POST   | `/api/v1/workspaces/{id}/agents/{agent_id}/sessions` | `agent:read` |
| POST   | `/api/v1/sessions` (top-level: ``{"agent_id":...}``) | derived from agent's workspace |
| GET    | `/api/v1/agents/{agent_id}` (top-level) | `agent:read` on its workspace |
| PATCH  | `/api/v1/agents/{agent_id}` (top-level) | `agent:write` on its workspace |
| DELETE | `/api/v1/agents/{agent_id}` (top-level) | `agent:delete` on its workspace |
| POST   | `/api/v1/agents/{agent_id}/run` (top-level) | `agent:read` on its workspace |
| GET    | `/api/v1/workspaces/{id}/sessions/{session_id}/messages` | `agent:read` |
| GET    | `/api/v1/sessions/{session_id}/messages` (top-level) | derived from session's workspace |
| POST   | `/api/v1/workspaces/{id}/agents/{agent_id}/run` | `agent:read` |
| WS     | `/api/v1/chat/{agent_id}/ws` | session cookie or `?token=` |

Agent body:
```json
{
  "name": "Helper",
  "slug": "helper",
  "system_prompt": "You are helpful.",
  "model_alias": "chat-default",
  "tool_ids": ["<uuid>", "..."],
  "rag_collection_id": "<uuid>",
  "config": { "rag_enabled": true, "temperature": 0.2 }
}
```

### WebSocket protocol (`/chat/{agent_id}/ws`)

Client → server:
```json
{"type":"user_message","content":"..."}
{"type":"ping"}
```

Server → client (per-message JSON):
```json
{"type":"session","payload":{"session_id":"...","agent_id":"..."}}
{"type":"step","payload":{"node":"plan"}}
{"type":"citations","payload":{"hits":[...]}}
{"type":"tool_call","payload":{"id":"...","name":"...","args":{...}}}
{"type":"tool_result","payload":{"id":"...","name":"...","ok":true,"result":...}}
{"type":"delta","payload":{"content":"..."}}
{"type":"final","payload":{"content":"...","citations":[...],"iterations":N,"tokens_in":..,"tokens_out":..}}
{"type":"error","payload":{"message":"..."}}
{"type":"done","payload":{}}
```

Audit actions: `agent.create`, `agent.update`, `agent.delete`, `agent.run`.

## Phase 6 — Audit explorer

| Method | Path | Permission |
|--------|------|------------|
| GET | `/api/v1/workspaces/{id}/audit` | `admin:read` |
| GET | `/api/v1/admin/health` | tenant admin |
| GET | `/api/v1/admin/metrics` | tenant admin |

`GET /admin/metrics` returns a roll-up of selected counters
(`http_requests_total`, `tokens_total`, `llm_cost_usd_total`,
`tool_invocations_total`, `policy_decisions_total`, `audit_events_total`,
…) across every downstream service. Use Prometheus directly for
histograms / per-label slices.

Query params: `actor`, `action`, `decision`, `since`, `until`, `limit`,
`offset`. Results are sorted descending by `created_at`.

Web UI: `/workspaces/[id]/audit` — filterable table.

## Memory service (`memory-svc`, internal)

Used by `agent-runtime` and any future SDK code; not currently exposed
through the api-gateway.

| Method | Path | Description |
|--------|------|-------------|
| POST   | `/short-term/append` | Append a turn to the per-session Redis buffer |
| GET    | `/short-term/{ws}/{session}` | Get the recent buffer |
| DELETE | `/short-term/{ws}/{session}` | Clear it |
| POST   | `/items` | Upsert a long-term memory item (optional embedding) |
| GET    | `/items?workspace_id=...&scope=...` | List/filter items |
| DELETE | `/items/{id}` | Delete |
| POST   | `/search` | Vector-similarity search (pgvector on PG, Python cosine fallback on SQLite) |

## Rate limiting

`api-gateway` applies a per-principal Redis token-bucket
(`AGENTICOS_SECRET_KEY`-derived identity → 60-second windows, default
600 req/min from `rate_limit_per_minute`). Health/openapi/docs/WS upgrade
paths are skipped. When Redis is unreachable, the middleware passes
everything through.

429 responses include `Retry-After`, `X-RateLimit-Limit`, and
`X-RateLimit-Remaining` headers.

## Error format

All non-2xx responses are RFC-7807 `application/problem+json`. The
gateway maps `AgenticOSError`, `HTTPException`, and
`RequestValidationError` to a consistent shape:

```json
{
  "type": "about:blank",
  "title": "Validation Error",
  "status": 422,
  "code": "validation_error",
  "detail": "request validation failed",
  "instance": "/api/v1/workspaces",
  "extras": { "errors": [ {"loc": ["body","slug"], "msg": "...", "type": "..."} ] }
}
```

## v1 complete

All phases 0–6 (+6.5) shipped. Helm chart lives at `deploy/helm/agenticos`;
see `docs/deployment.md` for installation. Tagged releases publish signed
images to GHCR with SBOMs, Trivy scans, and a packaged Helm chart.
