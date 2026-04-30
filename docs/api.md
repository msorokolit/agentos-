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

## Coming next (Phase 2)

- `GET/POST /admin/models` and `POST /admin/models/{id}/test`
- `POST /llm/v1/chat/completions`, `POST /llm/v1/embeddings` (proxied to llm-gateway)
