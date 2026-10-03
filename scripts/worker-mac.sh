#!/usr/bin/env bash
# Native Celery worker on Apple Silicon so OmniVoice uses MPS.
# Docker Linux cannot see the Mac GPU; the compose worker stays on CPU torch.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "worker-mac.sh is for macOS. On Linux, use the Docker worker." >&2
  exit 1
fi

echo "==> Stopping the Docker CPU worker (one Celery consumer only)"
docker compose -f "$ROOT/docker-compose.yml" stop worker

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg is not on PATH. Install it (brew install ffmpeg) before dubbing." >&2
  exit 1
fi

cd "$ROOT/services/api"
# shellcheck disable=SC1091
source .venv/bin/activate
export PYTHONPATH=.
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
# Root .env is mock for unit tests. Compose already forces local inside Docker.
export PROVIDER_MODE=local
# Unsupported MPS ops fall back to CPU instead of crashing the clone.
export PYTORCH_ENABLE_MPS_FALLBACK=1

python - <<'PY'
import sys

try:
    import torch
except ImportError:
    print(
        "torch is not installed in services/api/.venv. "
        "Install the Mac wheel (not the CPU index) plus services/worker/requirements.txt.",
        file=sys.stderr,
    )
    sys.exit(1)

if not torch.backends.mps.is_available():
    print(
        "MPS is not available. OmniVoice would run on CPU. "
        "Use a Mac with Apple Silicon and a default PyTorch build.",
        file=sys.stderr,
    )
    sys.exit(1)
print(f"OmniVoice device: mps (torch {torch.__version__})")
PY

echo "==> Celery worker (pool=solo, concurrency=1)"
exec celery -A app.celery_app.celery worker --pool=solo --concurrency=1 --loglevel=INFO
