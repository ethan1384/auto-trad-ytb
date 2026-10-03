#!/bin/sh
# Celery worker on an NVIDIA card. Postgres, Redis, S3 and Ollama stay on the Mac.
set -eu

python - <<'PY'
import sys

import torch

if not torch.cuda.is_available():
    print(
        "CUDA is not visible in this container, so OmniVoice would clone on CPU. "
        "Check the NVIDIA driver and that Docker Desktop runs with the WSL2 backend.",
        file=sys.stderr,
    )
    sys.exit(1)
props = torch.cuda.get_device_properties(0)
print(f"OmniVoice device: cuda:0 {props.name}, {props.total_memory / 2**30:.1f} GiB (torch {torch.__version__})")
PY

python - <<'PY'
import os
import socket
import sys
from urllib.parse import urlparse

targets = {
    "Postgres": os.environ["DATABASE_URL"],
    "Redis": os.environ["REDIS_URL"],
    "S3": os.environ["S3_ENDPOINT_URL"],
}
failed = False
for name, url in targets.items():
    parsed = urlparse(url)
    try:
        socket.create_connection((parsed.hostname, parsed.port), timeout=5).close()
        print(f"{name} reachable at {parsed.hostname}:{parsed.port}")
    except OSError as exc:
        print(f"{name} unreachable at {parsed.hostname}:{parsed.port}: {exc}", file=sys.stderr)
        failed = True
if failed:
    print("Start the Mac stack and check MAC_HOST and the macOS firewall.", file=sys.stderr)
    sys.exit(1)
PY

# Prefork, not solo: the cancel button sends SIGKILL to the child running the job.
exec celery -A app.celery_app.celery worker --loglevel=INFO --concurrency=1 --hostname="gpu@%h"
