# Architecture V1 — YouTube Dubbing Platform

## 1. Product intent

SaaS for creators to ingest a video, transcribe it, translate + naturalize the script, clone the creator voice, lip-sync, and export a dubbed video with subtitles.

V1 goal: a **locally runnable modular monorepo** with real orchestration and provider interfaces. Heavy AI providers may be mocked behind the same interfaces.

## 2. High-level topology

```text
┌──────────────┐     REST/JSON      ┌─────────────────┐
│  apps/web    │ ◄────────────────► │  services/api   │
│  Next.js     │                    │  FastAPI        │
└──────────────┘                    └────────┬────────┘
                                             │ enqueue
                                             ▼
                                    ┌─────────────────┐
                                    │ Redis + Celery  │
                                    │ services/worker │
                                    └────────┬────────┘
                     ┌───────────────┬───────┴────────┬──────────────┐
                     ▼               ▼                ▼              ▼
               PostgreSQL      MinIO (S3)      Provider mocks   FFmpeg
               jobs/assets     media blobs     (ASR/TTS/…)     render
```

### Services

| Unit | Role |
|---|---|
| `apps/web` | Creator dashboard: projects, upload, job status, pipeline steps |
| `services/api` | Auth-light API, project/job CRUD, signed upload URLs, job kickoff |
| `services/worker` | Celery workers executing pipeline stages |
| `packages/shared` | Shared contracts (job statuses, stage names, DTOs) |
| Postgres | Users (optional V1), projects, jobs, stages, assets |
| Redis | Celery broker/backend |
| MinIO | Local S3 for source/intermediate/final media |

## 3. Pipeline stages

Each job is a row with ordered stages. Stages are retryable and idempotent where possible.

1. `ingest` — persist source video object key
2. `extract_audio` — FFmpeg extract WAV/PCM
3. `transcribe` — faster-whisper (mockable)
4. `translate` — Argos Translate (mockable)
5. `rewrite` — Qwen3.8 27B via the host Ollama turns each source line into one spoken sentence. Greetings, farewells, and idioms are said as a native speaker would, not glossed from the Argos draft. If the model is absent, the Argos line is kept. vLLM remains the later serving path.
6. `synthesize` — OmniVoice clones every detected speaker and speaks their translated lines (mockable). A French accent changes wording only and never swaps in a catalog voice.
7. `align` — duration/timing adjust (FFmpeg time-stretch)
8. `lipsync` — keep the original picture (no mouth redraw)
9. `render` — mux dubbed voice over the original music and room tone, on the original picture, with optional subtitles
10. `complete` — mark job done, expose download URLs

Job status: `pending | queued | running | failed | completed | cancelled`  
Stage status: `pending | running | succeeded | failed | skipped`

## 4. Data model (core)

- **Project**: id, name, source_language, target_language, created_at
- **Asset**: id, project_id, kind (`source_video`, `audio`, `transcript`, `script`, `voice`, `render`, …), storage_key, mime, meta JSON
- **Job**: id, project_id, status, current_stage, error, created_at, updated_at
- **JobStage**: id, job_id, name, status, attempt, started_at, finished_at, detail JSON
- **Consent** (minimal): project_id or job_id flag that voice cloning consent was recorded

## 5. Provider abstractions

Stable interfaces in `services/api` / `services/worker` (shared package preferred):

- `TranscriptionProvider`
- `TranslationProvider`
- `RewriteProvider`
- `VoiceSynthesisProvider`
- `LipSyncProvider`
- `MediaRenderer` (FFmpeg)

Config selects `mock` or real implementation via env (`PROVIDER_MODE=mock|real`).

## 6. API surface (V1)

- `GET /health`
- `GET /projects` / `POST /projects` / `GET /projects/{id}`
- `POST /projects/{id}/assets/upload-url` — MinIO presigned PUT
- `POST /projects/{id}/assets/confirm`
- `POST /projects/{id}/jobs` — start dubbing job
- `GET /jobs/{id}` — status + stages
- `GET /jobs/{id}/artifacts` — output asset URLs

Auth V1: simple header/dev token or stub session (Clerk/Auth.js deferred). Not a blocker for local pipeline demos.

## 7. Frontend (V1)

- Dashboard list of projects
- Create project (name + languages)
- Upload / attach source video (presigned or local stub)
- Job detail with stage timeline + polling (TanStack Query)
- Mock login gate optional

## 8. Choices retained vs deferred

**Retained:** Next.js, FastAPI, Postgres, SQLAlchemy+Alembic, Redis+Celery, MinIO, FFmpeg, provider interfaces for faster-whisper / Argos / LLM / OmniVoice. The original picture is kept.

**Deferred:** Stripe billing UI, production auth (Clerk/Auth.js), Kubernetes, WhisperX, pyannote.audio, NLLB (unless Argos insufficient), vLLM serving, Prometheus/Grafana full stack, live dubbing.

Local dubbing finds who is speaking with sherpa-onnx: a pyannote segmentation model cuts the turns, and a 3D-Speaker embedding clusters them. Each transcript line takes the turn that covers it. When one person cuts in on the other, that line is split at the interruption so each speaker keeps their own words. Titanet-small, then pitch and timbre, remain the fallback when those models are missing. OmniVoice clones every detected speaker. The clone hears a 24 kHz extract of the original; transcription stays at 16 kHz. Full pyannote.audio stays out of V1.

**Avoided:** Wav2Lip (commercial restriction), premature microservices.

## 9. Risks

| Risk | Mitigation |
|---|---|
| GPU provider cost/latency | Mock mode + cloud GPU later |
| Mouth redraw looks wrong on this footage | Original picture is kept; dubbed voice is mixed over the original accompaniment at render |
| Dub loses music and room tone | Demucs removes the original voice; render keeps that accompaniment under the new voice |
| License/compliance voice+face | Consent flag + audit fields |
| Long pipeline failures | Per-stage retries, DB state, Celery acks |
| Monorepo coupling | Clear package boundaries, shared contracts only |

## 10. Local boot target

`docker compose up` brings Postgres, Redis, MinIO.  
API + worker + web run via compose or `scripts/dev.sh`.  
The worker can also run on another machine on the LAN with an NVIDIA GPU (`docker-compose.gpu-worker.yml`). It reaches the Mac's Redis, Postgres, S3, and Ollama over the network. Only one worker should consume at a time. See `docs/gpu-worker-windows.md`.  
`scripts/verify.sh` runs install/lint/typecheck/tests/health smoke.
