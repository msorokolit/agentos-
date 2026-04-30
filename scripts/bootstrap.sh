#!/usr/bin/env bash
# One-shot dev bootstrap: copy .env, build images, bring stack up,
# run migrations, pull default models.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

docker compose up -d --build
echo "Waiting for postgres..."
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-agenticos}" >/dev/null 2>&1; do
  sleep 1
done

docker compose run --rm api-gateway alembic upgrade head

if [ "${PULL_MODELS:-1}" = "1" ]; then
  bash scripts/pull_models.sh
fi

bash scripts/smoke.sh
echo
echo "AgenticOS dev stack ready. Open http://localhost:${WEB_UI_PORT:-3000}"
