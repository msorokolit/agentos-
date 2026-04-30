# Load tests (k6)

Scripts here are run with [k6](https://k6.io/). They target a running
AgenticOS stack — typically `make dev` for development or a real
deployment for stress testing.

## Authentication

Most scripts need a workspace-scoped API key. Mint one through the UI
(Workspace → API keys) or with curl:

```bash
TOKEN=$(curl -s -b cookies.txt -H "Content-Type: application/json" \
  -d '{"name":"k6","scopes":["read","write","admin"]}' \
  http://localhost:8080/api/v1/workspaces/$WS_ID/api-keys | jq -r .token)
```

Then export it:

```bash
export AGENTICOS_API=http://localhost:8080
export AGENTICOS_TOKEN=$TOKEN
export AGENTICOS_WORKSPACE_ID=$WS_ID
export AGENTICOS_AGENT_ID=$AGENT_ID
```

## Running

```bash
# Healthz baseline (no auth, no model)
k6 run tests/load/healthz.js

# /me readback under realistic auth
k6 run tests/load/me_smoke.js

# Chat throughput (mocks an Ollama provider, see test plan in PLAN §10).
k6 run -e VUS=10 -e DURATION=30s tests/load/agent_run.js
```

## Targets (PLAN §10)

* p95 first-token latency:
  - `qwen2.5:7b-instruct` on CPU (8 vCPU): < 4s
  - `llama3.1:8b-instruct` on a single L4 GPU: < 1.2s
* /healthz p99 < 50ms at 100 RPS (gateway).
