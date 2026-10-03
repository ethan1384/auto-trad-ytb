#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Starting infra (postgres, redis, s3/localstack, ollama)"
docker compose -f "$ROOT/docker-compose.yml" up -d postgres redis s3 ollama

echo "==> Waiting for postgres"
until docker compose -f "$ROOT/docker-compose.yml" exec -T postgres pg_isready -U dubbing -d dubbing >/dev/null 2>&1; do
  sleep 1
done

echo "==> Migrations"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH=.
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  alembic upgrade head
)

echo "==> API (background) on :8000"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH=.
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
) &

echo "==> Worker (background)"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH=.
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
  celery -A app.celery_app.celery worker --loglevel=INFO
) &

echo "==> Web on :3000"
(
  cd "$ROOT/apps/web"
  npm run dev -- -p 3000
)
