# agenticos-shared

Shared building blocks used by every AgenticOS Python service:

- `settings` — Pydantic-Settings base, env loading.
- `db` — SQLAlchemy engine/session.
- `auth` — JWT verification, principal model.
- `audit` — `AuditEvent` model + emitter.
- `otel` — OpenTelemetry tracer/meter init.
- `errors` — RFC-7807 problem+json helpers.
- `logging` — structlog config.
