# Security (Phase 0 baseline)

> Full security posture — threat model, data classification, redaction
> rules, sandbox guarantees — lands in Phase 6. This page documents what
> Phase 0 already enforces.

## Trust boundary

```
Internet  ─►  reverse proxy  ─►  api-gateway  (only public service)
                                      │
                                      ▼ internal network
                            other AgenticOS services
```

Only `api-gateway` is meant to be exposed publicly. All other services
are reachable only over the compose network (or, in K8s, over a
ClusterIP + NetworkPolicy).

## Authentication

- Browser users authenticate via **OIDC** against an external IdP
  (Keycloak in dev; Okta/Azure AD/etc. in prod).
- The api-gateway verifies the OIDC ID token (JWKS) and mints a short-lived
  internal HS256 JWT representing a `Principal` for service-to-service calls.
- API tokens (long-lived) land in Phase 1.

## Authorisation

- **RBAC** — workspace roles `owner`, `admin`, `builder`, `member`, `viewer`.
- **OPA** — Rego bundle in `policies/` evaluated for tool / data / model
  access. Sidecar at `http://opa:8181`.

## Audit

- Every mutating action and every LLM/tool call emits an `AuditEvent` to
  NATS subject `audit.events`.
- The worker persists events to the `audit_event` table (append-only,
  monthly-partitioned in Phase 6).

## Secret handling

- All secrets are read from env (`AGENTICOS_SECRET_KEY`, OIDC client
  secret, S3 keys, …). They are never logged.
- `agenticos_shared.audit.safe_payload` strips any key matching
  `secret|password|token|api_key` before logging.

## Network egress

- Built-in tools call only configured allow-listed endpoints.
- `tool-registry` will route HTTP tools through an egress proxy (Phase 4).

## Container hardening (Phase 6)

- Non-root user in Dockerfile (`app:app`).
- Read-only root FS, drop all capabilities.
- Trivy + Grype scans in release pipeline; SBOM via syft.
- Cosign-signed images; provenance attached.

## Known limitations (Phase 0)

- No code-execution sandbox (deferred to v1.5).
- No PII redaction in LLM payloads yet (Phase 4).
- No rate-limit middleware yet (Phase 1).
- Helm chart with NetworkPolicies arrives in Phase 6.
