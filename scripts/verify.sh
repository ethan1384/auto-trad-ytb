#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Shared package import"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -c "from dubbing_shared import PIPELINE_ORDER; assert len(PIPELINE_ORDER) == 10"
)

echo "==> Backend tests"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH=.
  pytest -q
)

echo "==> Backend critical imports"
(
  cd "$ROOT/services/api"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export PYTHONPATH=.
  python -c "from app.main import app; from app.celery_app import celery, run_pipeline_job; print(app.title)"
)

echo "==> Frontend typecheck + build"
(
  cd "$ROOT/apps/web"
  npx tsc --noEmit
  npm run build
)

echo "==> docker compose config"
docker compose -f "$ROOT/docker-compose.yml" config >/dev/null

echo "OK: all verification checks passed"
