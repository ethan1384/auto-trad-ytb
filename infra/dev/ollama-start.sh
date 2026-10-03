#!/bin/sh
# Optional local server. The worker calls the host Ollama instead: the 0.5B
# model copied literal drafts and missed spoken formulas. A failed pull leaves
# this server up.
set -u
ollama serve &
pid=$!
i=0
while [ "$i" -lt 60 ]; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 1
done
ollama pull qwen2.5:0.5b || true
wait "$pid"
