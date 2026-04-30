# Security Policy

We take security seriously and welcome reports from the community.

## Supported Versions

We support the latest tagged minor version on `main`. Older versions may
receive critical fixes at maintainer discretion.

| Version | Status            |
|---------|-------------------|
| `0.1.x` | ✅ supported       |
| < 0.1   | ❌ not supported   |

## Reporting a Vulnerability

**Please do not file a public GitHub issue for security reports.**

Instead use one of:

1. **GitHub Private Vulnerability Reporting** — preferred. Open
   [a private advisory](https://github.com/msorokolit/agentos-/security/advisories/new)
   from the *Security* tab.
2. Email **security@agenticos.example.invalid** (rotate the address as
   appropriate for your fork) with PGP-encrypted contents.

Please include:

- Affected version / commit / Helm chart version.
- A clear description of the vulnerability and its impact.
- Reproduction steps or a proof-of-concept.
- Whether you require a coordinated-disclosure window.

We will acknowledge receipt within **two business days** and aim to
provide a fix or detailed mitigation plan within **30 days** for HIGH or
CRITICAL severity. Lower-severity issues are handled in normal release
cycles.

## What's in scope

- **AgenticOS source code** (this repository).
- **Built container images** published to the project's registry.
- **The shipped Helm chart** in `deploy/helm/agenticos`.

## Out of scope

- Findings that require an attacker who already controls a tenant admin
  account or the underlying host.
- Self-DoS via misconfiguration documented in `docs/deployment.md`.
- Issues in third-party services we deploy (Postgres, Redis, NATS,
  Ollama, Keycloak) — please report those upstream.
- Vulnerabilities in unreleased branches.

## Hardening posture

- Containers run as a non-root user with a read-only root filesystem and
  all capabilities dropped (see Helm chart values).
- All secrets are read from env / sealed secrets / KMS adapters; never
  logged. The shared audit emitter strips ``secret`` / ``password`` /
  ``token`` / ``api_key`` keys before logging.
- Cookies are `HttpOnly`, `SameSite=Lax`; HSTS, strict CSP, no-referrer,
  X-Frame-Options DENY are set on every response.
- API keys are stored as `sha256` only — the plaintext is returned
  exactly once.
- Tool egress is gated by an allow-list and OPA policy.

## Coordinated disclosure

Once a fix is ready and a CVE is assigned (when applicable) we publish a
GitHub Security Advisory and a release note with mitigation/upgrade
guidance. Thank you for helping keep AgenticOS secure.
