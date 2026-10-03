#!/usr/bin/env bash
# Mac side of the Windows GPU worker: run the stack without any local worker,
# and expose Postgres, Redis, S3 and the host Ollama on the network.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "mac-host-gpu-worker.sh runs on the Mac. On the PC, use docker-compose.gpu-worker.yml." >&2
  exit 1
fi

if pgrep -f "celery -A app.celery_app.celery worker" >/dev/null 2>&1; then
  echo "A Celery worker is running on this Mac (worker-mac.sh or dev.sh). Stop it first," >&2
  echo "otherwise it takes jobs away from the GPU." >&2
  exit 1
fi

echo "==> Stopping the compose worker and the compose Ollama (0.5B only)"
"${COMPOSE[@]}" stop worker ollama >/dev/null 2>&1 || true

echo "==> Starting postgres, redis, s3, api, web"
"${COMPOSE[@]}" up -d postgres redis s3 api web

echo "==> Host Ollama"
listen="$(lsof -nP -iTCP:11434 -sTCP:LISTEN 2>/dev/null | awk 'NR > 1 {print $9}' | sort -u)"
if [[ -z "$listen" ]]; then
  echo "Ollama is not running. Start it with: OLLAMA_HOST=0.0.0.0:11434 ollama serve" >&2
elif ! grep -qE '^(\*|0\.0\.0\.0):11434$' <<<"$listen"; then
  echo "Ollama only listens on $listen, so the PC cannot reach it. Quit the Ollama app, then:" >&2
  echo "  launchctl setenv OLLAMA_HOST 0.0.0.0:11434 && open -a Ollama" >&2
fi
if ! curl -fsS http://127.0.0.1:11434/api/tags 2>/dev/null | grep -q '"qwen3.8:27b"'; then
  echo "qwen3.8:27b is missing from Ollama; lines would keep the literal Argos draft." >&2
fi

lan="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
tail_ip="$(command -v tailscale >/dev/null 2>&1 && tailscale ip -4 2>/dev/null | head -n 1 || true)"
echo
echo "Mac address on the LAN: ${lan:-unknown}"
[[ -n "$tail_ip" ]] && echo "Mac address on Tailscale: $tail_ip"
echo
echo "On the PC (WSL2 shell, repo root):"
echo "  MAC_HOST=${lan:-<mac-ip>} docker compose -f docker-compose.gpu-worker.yml up --build"
