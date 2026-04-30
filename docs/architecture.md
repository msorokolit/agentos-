# AgenticOS — Architecture

> Self-hosted, on-prem agent platform that runs entirely on **local LLMs**.
>
> Status: **Phase 4 — Tool registry + Policy** complete. Next: Phase 5 (Agent runtime + chat).

---

## 1. High-level diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Web UI (Next.js)        Admin Console        SDK (Py / TS)      │
└───────────────┬──────────────────┬──────────────────┬────────────┘
                │  REST/WebSocket  │                  │
┌───────────────▼──────────────────▼──────────────────▼────────────┐
│                     API Gateway (FastAPI)                        │
│  AuthN (OIDC) · AuthZ (RBAC + OPA) · Rate limit · Audit          │
└───┬─────────────┬──────────────┬──────────────┬──────────────┬───┘
    │             │              │              │              │
┌───▼───┐  ┌──────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
│Agent  │  │ LLM        │  │ Tool      │  │ Knowledge │  │ Memory    │
│Runtime│  │ Gateway    │  │ Registry  │  │  (RAG)    │  │ Service   │
│LangGr.│  │Ollama/vLLM │  │MCP + HTTP │  │ pgvector  │  │ pg+redis  │
└───┬───┘  └────────────┘  └─────┬─────┘  └───────────┘  └───────────┘
    │                            │
    │                      ┌─────▼─────┐
    │                      │  Sandbox  │   (gVisor; v1.5)
    │                      └───────────┘
    │
┌───▼──────────────────────────────────────────────────────────────┐
│ Event bus (NATS) · Postgres+pgvector · Redis · MinIO · OTel/Prom │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Components

| Component | Tech | Responsibility |
|---|---|---|
| **api-gateway** | FastAPI 3.12 | REST + WS public surface; OIDC, RBAC, audit, rate limit |
| **agent-runtime** | Python + LangGraph | Executes agent workflows; node = LLM call / tool call / observe |
| **llm-gateway** | FastAPI | OpenAI-compatible router across Ollama, vLLM, llama.cpp |
| **tool-registry** | Python | MCP client + HTTP/OpenAPI plugins; built-ins (HTTP, SQL, RAG, file) |
| **knowledge-svc** | Python | Document ingest, chunking, embedding, hybrid search |
| **memory-svc** | Python | Short-term (Redis) + long-term (pgvector) memory per agent/user |
| **policy-svc** | OPA sidecar | Rego policies for tool/data/model access |
| **sandbox-svc** | gVisor | Code execution sandbox (Phase 1.5) |
| **worker** | Arq (Redis) | Background jobs: ingestion, embeddings, summaries |
| **web-ui** | Next.js 14 | Chat, agents, knowledge, admin |
| **postgres** | pgvector/pg16 | Relational + vector store |
| **redis** | Redis 7 | Cache, rate-limit, queues, short-term memory |
| **nats** | NATS JetStream | Event bus (audit, agent steps) |
| **minio** | MinIO | S3-compatible object storage |
| **keycloak** (dev) | Keycloak 25 | OIDC provider for local development |
| **opa** | OPA 0.68 | Policy decisions |
| **otel-collector / prometheus / grafana** | — | Observability |

## 3. Repo layout

```
services/        Python microservices + shared lib
web-ui/          Next.js 14 web app
sdk/             Python + TypeScript SDKs
migrations/      Alembic migrations
policies/        OPA Rego bundles
deploy/          docker-compose, Helm, air-gapped bundler
docs/            Architecture, deployment, security
scripts/         bootstrap.sh, smoke.sh, pull_models.sh
tests/           Integration, e2e, load (added in later phases)
```

## 4. Cross-service contracts

* **AuthN**: `api-gateway` exchanges OIDC tokens for an internal HS256 JWT
  carrying a `Principal`. Internal calls use that token. See
  `agenticos_shared.auth`.
* **Audit**: any mutating action emits an `AuditEvent` to NATS subject
  `audit.events`. Persisted to `audit_event` table by the worker.
* **OTel**: every service initialises a tracer at startup; spans propagate
  via W3C tracecontext on HTTP headers.
* **Errors**: services return RFC-7807 `application/problem+json`. See
  `agenticos_shared.errors`.

## 5. Data model (Phase 0)

`tenant`, `workspace`, `user_account`, `workspace_member`, `audit_event`.
Full schema lives in `migrations/versions/0001_initial.py`. Subsequent
phases add `agent`, `tool`, `model`, `document`, `chunk`, `session`,
`message`, `memory_item`, `api_key`, `policy_bundle`.

## 6. Local development

```bash
make dev           # build + start everything, run migrations, pull default models
make smoke         # hit /healthz on every service
make logs          # tail logs
make test          # python unit tests
make down          # stop the stack
```

Default exposed ports:

| Service        | Port  |
|----------------|-------|
| api-gateway    | 8080  |
| llm-gateway    | 8081  |
| agent-runtime  | 8082  |
| tool-registry  | 8083  |
| knowledge-svc  | 8084  |
| memory-svc     | 8085  |
| web-ui         | 3000  |
| keycloak       | 8090  |
| postgres       | 5432  |
| redis          | 6379  |
| minio (S3/UI)  | 9000 / 9001 |
| nats           | 4222  |
| ollama         | 11434 |
| opa            | 8181  |
| prometheus     | 9090  |
| grafana        | 3001  |

## 7. Milestones

See [`PLAN`](https://github.com/msorokolit/agentos-/blob/main/docs/architecture.md) for the full plan; this doc tracks the current state.

| Phase | Goal | Status |
|-------|------|--------|
| **0** | Repo skeleton, shared lib, service stubs, compose stack, migrations, CI | ✅ done |
| **1** | OIDC + RBAC + workspaces + audit emitter | ✅ done |
| **2** | LLM gateway + models admin (Ollama/vLLM/openai-compat) + quotas | ✅ done |
| **3** | Knowledge ingest + hybrid search (pgvector + tsvector + RRF) | ✅ done |
| **4** | Tool registry + OPA policy (built-ins, HTTP/OpenAPI/MCP) | ✅ done |
| 5 | Agent runtime + chat (LangGraph ReAct, streaming) | ⏳ next |
| 6 | Hardening + Helm chart | — |
| 7 (v1.5) | Code sandbox, multi-agent, SAML/SCIM, evals, air-gapped bundler | — |

## 8. Security posture

See [`docs/security.md`](security.md) (added in Phase 6).

Highlights baked in from Phase 0:

- All secrets read from env; **never** logged (`safe_payload` redacts on key).
- Audit table is append-only; partitioned monthly in Phase 6.
- OIDC by default — no local password DB.
- OPA sidecar — policies live in source, hot-reloaded.
- Containers run as non-root, read-only FS in Phase 6.

## 9. Glossary

* **Workspace** — the unit of multi-user collaboration (≈ "team").
* **Tenant** — top-level isolation boundary (one customer org).
* **Agent** — a configured LLM + tools + system prompt + graph.
* **Tool** — a callable exposed to an agent (MCP server, HTTP endpoint, builtin).
* **Memory item** — a key-value pair (optionally embedded) stored per-user/agent/session.
