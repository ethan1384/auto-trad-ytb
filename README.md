# Dubbing Studio (auto-trad-ytb)

SaaS-oriented monorepo for translating and dubbing creator videos: ingest → transcribe → translate → rewrite → voice clone → render. The original picture is kept.

## Architecture (short)

```text
apps/web (Next.js)
    ↓ REST
services/api (FastAPI) ── enqueue ──► Redis/Celery ──► services/worker
    ↓                                    ↓
 PostgreSQL                           MinIO (S3)
```

Full write-up: [`docs/architecture.md`](docs/architecture.md).

## Stack (V1)

| Layer | Choice |
|---|---|
| Web | Next.js + TypeScript + Tailwind + TanStack Query |
| API | FastAPI + Pydantic + SQLAlchemy + Alembic |
| Jobs | Redis + Celery |
| Storage | MinIO |
| AI | Provider interfaces; **mock** by default (`faster-whisper`, Argos, Qwen3.8 27B rewrite, OmniVoice). The original picture is kept |

## Quick start

```bash
cp .env.example .env
cd services/api && python3 -m venv .venv && source .venv/bin/activate
pip install -e ../../packages/shared
pip install -r requirements-docker.txt pytest
cd ../../apps/web && npm install
cd ../..
chmod +x scripts/*.sh
./scripts/dev.sh
```

Then open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001

Or full compose (API + worker + web + infra). The compose worker uses CPU torch inside Linux, so voice cloning stays slow on a Mac:

```bash
docker compose up --build
```

## Mac: Voices on MPS

Docker cannot see the Apple GPU. Keep postgres, redis, s3, ollama, api, and web in compose, stop the CPU worker, and run Celery on the Mac so OmniVoice picks MPS. Clone settings stay the same (`num_step=32`, guidance 3, original speaker reference).

One-time, in `services/api/.venv` (default PyTorch wheel, not the CPU index from the worker Dockerfile):

```bash
source services/api/.venv/bin/activate
pip install torch torchaudio
pip install -r services/worker/requirements.txt
```

`ffmpeg` must be on the PATH (`brew install ffmpeg`). Then:

```bash
./scripts/worker-mac.sh
```

That stops the compose `worker` service (one Celery consumer) and starts a host worker with `--pool=solo --concurrency=1` and `PROVIDER_MODE=local`.

## Windows PC: Voices on an NVIDIA GPU

The worker can run on a Windows PC (Docker Desktop + WSL2) while the Mac keeps the API, web, Postgres, Redis, S3, and Ollama. On the Mac, run `./scripts/mac-host-gpu-worker.sh`. On the PC, run `MAC_HOST=<mac-ip> docker compose -f docker-compose.gpu-worker.yml up --build`. OmniVoice, Demucs, and Whisper then run on CUDA. Setup guide: [`docs/gpu-worker-windows.md`](docs/gpu-worker-windows.md).

Run migrations inside the API container if needed:

```bash
docker compose exec api alembic upgrade head
```

## Verification

```bash
./scripts/verify.sh
```

## What works vs mocked

| Piece | Status |
|---|---|
| Project CRUD, upload URL, job + stage tracking | Real |
| Celery pipeline orchestration | Real |
| Postgres / Redis / MinIO wiring | Real |
| ASR / translation / ffmpeg render | Real in the worker when `PROVIDER_MODE=local`; mock still available |
| Voice | Local mode clones every detected speaker with OmniVoice. A French accent does not replace that clone |
| Picture | Original frames are kept. The dubbed voice is mixed over the original music and room tone |
| Auth / Stripe | Deferred |

## Repo layout

- `apps/web` — dashboard
- `services/api` — FastAPI + domain + Celery tasks
- `services/worker` — worker image entry
- `packages/shared` — shared stage/job contracts
- `docs/` — architecture, plan, ADRs, progress log
- `AGENTS.md` — Cursor agent instructions
