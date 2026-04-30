# API

Phase 0 only exposes health endpoints; full REST/WS surface is documented
inline in OpenAPI as it lands phase by phase.

## Live OpenAPI

Once `make dev` is running:

- Swagger UI:  http://localhost:8080/docs
- Raw JSON:    http://localhost:8080/openapi.json

## Phase 0 endpoints (all services)

| Method | Path        | Description |
|--------|-------------|-------------|
| GET    | `/healthz`  | Liveness probe |
| GET    | `/readyz`   | Readiness probe |
| GET    | `/version`  | Service version |
| GET    | `/openapi.json` | OpenAPI schema |
| GET    | `/docs`     | Swagger UI |

## Phase 1 (planned)

- `POST /api/v1/auth/oidc/login`
- `GET  /api/v1/auth/oidc/callback`
- `GET  /api/v1/me`
- `GET/POST /api/v1/workspaces`
- `GET/POST/DELETE /api/v1/workspaces/{id}/members`

See the PLAN for the full API surface.
