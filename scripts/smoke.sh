#!/usr/bin/env bash
# Smoke-test every AgenticOS service by hitting /healthz.
# Used by `make smoke` after `make dev`.

set -euo pipefail

# Each entry: "service-name|host-port"
SERVICES=(
  "api-gateway|${API_GATEWAY_PORT:-8080}"
  "llm-gateway|${LLM_GATEWAY_PORT:-8081}"
  "agent-runtime|${AGENT_RUNTIME_PORT:-8082}"
  "tool-registry|${TOOL_REGISTRY_PORT:-8083}"
  "knowledge-svc|${KNOWLEDGE_PORT:-8084}"
  "memory-svc|${MEMORY_PORT:-8085}"
)

fail=0
for entry in "${SERVICES[@]}"; do
    name="${entry%%|*}"
    port="${entry##*|}"
    url="http://localhost:${port}/healthz"
    if out="$(curl -fsS --max-time 5 "$url" 2>/dev/null)"; then
        printf "  ✔ %-15s %s\n" "$name" "$out"
    else
        printf "  ✘ %-15s (%s) FAILED\n" "$name" "$url"
        fail=1
    fi
done

# Datastores (just TCP/HTTP probes).
probe() {
    local name="$1" url="$2"
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
        printf "  ✔ %-15s %s\n" "$name" "$url"
    else
        printf "  ✘ %-15s %s FAILED\n" "$name" "$url"
        fail=1
    fi
}
probe "minio"    "http://localhost:9000/minio/health/ready"
probe "keycloak" "http://localhost:8090/health/ready"
probe "ollama"   "http://localhost:11434/"
probe "opa"      "http://localhost:8181/health"
probe "prom"     "http://localhost:9090/-/ready"
probe "loki"     "http://localhost:3100/ready"

if [ "$fail" -eq 0 ]; then
    echo
    echo "All services healthy."
fi
exit "$fail"
