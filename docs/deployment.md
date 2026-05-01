# Deployment

AgenticOS supports two deployment modes:

* **Docker Compose** for local dev / SMB / single-host evaluation.
* **Kubernetes (Helm)** for production / multi-tenant / HA.

---

## Docker Compose (dev / single-host)

### Prerequisites

- Docker 24+ and Docker Compose v2.
- ~16 GB RAM (more with larger models).
- ~20 GB free disk for default models.
- Optional: NVIDIA GPU + nvidia-container-toolkit.

### First run

```bash
git clone https://github.com/msorokolit/agentos- agenticos
cd agenticos
cp .env.example .env

make dev          # build images, bring stack up, run migrations
make pull-models  # pulls default qwen2.5:7b-instruct + nomic-embed-text
make seed         # creates acme tenant + default workspace + alice/bob
make smoke        # hits /healthz on every service
```

Then open:

| URL | Service |
|-----|---------|
| http://localhost:3000  | Web UI |
| http://localhost:8080/docs | API gateway Swagger UI |
| http://localhost:8090  | Keycloak admin (admin/admin) |
| http://localhost:9001  | MinIO console (agenticos / agenticos-minio) |
| http://localhost:3001  | Grafana (admin/admin) |

### Updating

```bash
git pull
make down && make dev
```

### Reset

```bash
make nuke    # deletes all named volumes
```

### GPU (Ollama)

Add to the `ollama` service in `docker-compose.yml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

---

## Kubernetes (Helm)

The chart lives at [`deploy/helm/agenticos`](../deploy/helm/agenticos).

### Quick install (kind / minikube)

```bash
kind create cluster --name agenticos
helm install agenticos ./deploy/helm/agenticos \
  --set ingress.host=agenticos.local \
  --set oidc.issuer=http://idp.example.com/realms/agenticos \
  --set oidc.clientId=agenticos-web \
  --set oidc.clientSecret=$IDP_SECRET \
  --set oidc.redirectUri=http://agenticos.local/api/v1/auth/oidc/callback
```

### What gets installed

```
agenticos-postgres        (StatefulSet, pgvector/pg16)   — disable with postgres.external=true
agenticos-redis           (StatefulSet)
agenticos-nats            (Deployment)
agenticos-minio           (StatefulSet)                  — disable with minio.enabled=false
agenticos-opa             (Deployment)
agenticos-ollama          (StatefulSet)                  — disable with ollama.enabled=false
agenticos-api-gateway     (Deployment, 2 replicas)
agenticos-llm-gateway     (Deployment)
agenticos-agent-runtime   (Deployment, 2 replicas)
agenticos-tool-registry   (Deployment)
agenticos-knowledge-svc   (Deployment)
agenticos-memory-svc      (Deployment)
agenticos-worker          (Deployment, runs arq)
agenticos-web-ui          (Deployment)

agenticos-migrate-N        (Job, helm post-install hook running `alembic upgrade head`)

Ingress (nginx by default, websocket-aware)
NetworkPolicy: only same-chart pods + ingress controller can reach pods
ServiceAccount: agenticos
PodSecurityContext: runAsNonRoot: true, fsGroup, seccomp RuntimeDefault
ContainerSecurityContext: drop ALL caps, readOnlyRootFilesystem, no privilege escalation
```

### Key values

```yaml
secretKey: <32+ bytes>           # signs session cookies + internal JWTs
embedDim: 768

oidc:
  issuer: ...
  clientId: agenticos-web
  clientSecret: ...
  redirectUri: https://agenticos.example.com/api/v1/auth/oidc/callback

postgres:
  external: false                # set true to point at managed PG
  url: postgresql+psycopg://...

ingress:
  enabled: true
  className: nginx
  host: agenticos.example.com
  tls: { enabled: true, secretName: agenticos-tls }

services:
  apiGateway: { replicas: 2 }
  agentRuntime: { replicas: 2 }
```

See [`values.yaml`](../deploy/helm/agenticos/values.yaml) for the full surface.

### After install

1. The `agenticos-migrate-N` job runs Alembic. Confirm with
   `kubectl logs job/agenticos-migrate-1`.
2. Pull a model into Ollama:
   `kubectl exec -it sts/agenticos-ollama -- ollama pull qwen2.5:7b-instruct`.
3. From the Web UI, log in as a tenant admin → Admin → Models → register the
   alias `chat-default` against `ollama` / `qwen2.5:7b-instruct`.
4. Repeat for an embedding model alias `embed-default` (e.g. `nomic-embed-text`).
5. Create agents, upload documents, register tools.

### Production hardening checklist

- [ ] `secretKey` set to a 32-byte random value (use a sealed-secrets / KMS adapter).
- [ ] `oidc.clientSecret` provided via Sealed Secrets / external-secrets-operator.
- [ ] TLS terminated at ingress; `oidc.redirectUri` is `https://`.
- [ ] `postgres.external=true` pointing to a managed/HA Postgres with pgvector.
- [ ] `OPENAI_*` and other outbound endpoints blocked at the network layer.
- [ ] Trivy / Grype scans in your CI; chart's image tags pinned by digest.
- [ ] `tool_registry`'s `EGRESS_ALLOW_HOSTS` populated for HTTP tools.
- [ ] Backups: nightly `pg_dump`; MinIO bucket lifecycle for old documents.

---

## Air-gapped install

Two scripts under [`deploy/airgap/`](../deploy/airgap/) implement
PLAN §12.3:

- **`bundle.sh`** runs on a connected build host. It pulls every
  service image (and optionally an Ollama model) by version, packages
  the Helm chart and the default OPA Rego, writes a SHA-256 manifest,
  and produces a single `agenticos-airgap-<version>.tar.zst` tarball.
- **`install.sh`** runs on the air-gapped target. It verifies the
  bundle's checksum, loads the images via `docker load`, retags + pushes
  them into your internal registry, and `helm upgrade --install`s the
  bundled chart pointing at that registry.

Quickstart:

```bash
# On the connected host:
./deploy/airgap/bundle.sh -v 0.1.0 -o /tmp -m qwen2.5:1.5b-instruct
# → /tmp/agenticos-airgap-0.1.0.tar.zst (~3-5 GB)

# Copy the tarball + .sha256 onto the air-gapped network. Then:
./deploy/airgap/install.sh /tmp/agenticos-airgap-0.1.0.tar.zst \
    --registry registry.internal.example.com:5000 \
    --values ./deploy/helm/agenticos/values-prod.yaml
```

The full reference (manifest layout, `--skip-push`, `--dry-run`, model
bundling) is in [`deploy/airgap/README.md`](../deploy/airgap/README.md).
