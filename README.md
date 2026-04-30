# AgenticOS

> Self-hosted, on-prem **Agentic OS for Enterprise** that runs entirely on **local LLMs**.
>
> Build, run, and govern AI agents with full audit, RBAC/SSO, policy, and RAG — without sending any data outside your network.

[![CI](https://github.com/msorokolit/agentos-/actions/workflows/ci.yml/badge.svg)](https://github.com/msorokolit/agentos-/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## What it is

AgenticOS is a platform for enterprises to deploy AI agents that:

- 🏠 **Run on local LLMs** — Ollama, vLLM, llama.cpp, or any OpenAI-compatible endpoint. No cloud calls required.
- 🛠️ **Use tools safely** — Built-in HTTP/SQL/RAG tools, MCP servers, and OpenAPI plugins; every call gated by policy.
- 📚 **Know your docs** — Upload PDFs/Office/HTML; hybrid retrieval (BM25 + vector) with citations.
- 🔐 **Are governed** — OIDC SSO, RBAC, OPA policy, append-only audit, PII redaction.
- 👁️ **Are observable** — OpenTelemetry traces, Prometheus metrics, structured logs out of the box.
- 📦 **Deploy anywhere** — `docker compose up` for dev; Helm chart for prod; air-gapped bundle for restricted networks.

## Architecture (one-liner)

`Web UI / SDK → API Gateway (Auth+RBAC+Audit) → Agent Runtime (LangGraph) → { LLM Gateway · Tool Registry · Knowledge · Memory · Policy }`

See [docs/architecture.md](docs/architecture.md) for details.

## Quickstart

> Requires: Docker + Docker Compose, ~16 GB RAM, ~20 GB disk for default models.

```bash
git clone https://github.com/msorokolit/agentos- agenticos
cd agenticos
cp .env.example .env
make dev          # builds images, starts stack, runs migrations, pulls default model
make smoke        # curl healthz for every service
open http://localhost:3000
```

Default credentials are seeded via Keycloak; see `docs/deployment.md`.

## Repo layout

```
services/        Python microservices (api_gateway, agent_runtime, llm_gateway, ...)
web-ui/          Next.js 14 web app
sdk/             Python + TypeScript SDKs
deploy/          docker-compose, Helm chart, air-gapped bundler
migrations/      Alembic migrations (Postgres)
policies/        OPA Rego bundles
tests/           Integration, e2e, load
docs/            Architecture, deployment, security, API
scripts/         bootstrap, seed, model pull, smoke
```

## Status

🚧 **Phase 0 — Foundations.** See [PLAN summary](docs/architecture.md) and [milestones](docs/architecture.md#milestones).

## License

Apache-2.0 — see [LICENSE](LICENSE).
