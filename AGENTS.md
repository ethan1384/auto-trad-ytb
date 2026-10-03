# AGENTS.md

## Project overview
This repository contains a SaaS platform for translating and dubbing creator videos with transcription, translation, natural script rewriting, voice cloning, lip sync, and final video rendering. Keep the architecture modular, production-oriented, and realistic for a small startup team. Cursor reads `AGENTS.md` automatically from the project root, so this file should stay concise and repo-wide. [web:63][web:54]

## Product scope
Primary workflow:
1. Ingest video.
2. Transcribe with timestamps.
3. Translate.
4. Rewrite into natural target-language script.
5. Generate dubbed speech from creator voice.
6. Align timing.
7. Lip sync the face track.
8. Render final export and subtitles.

V1 priorities:
- Local dev must run reliably.
- Architecture must support real providers later even if some integrations are mocked first.
- Prefer a modular monorepo over premature microservices.
- Favor clear interfaces around ASR, translation, rewriting, voice, lip sync, and rendering.

## Preferred stack
Use these defaults unless there is a strong codebase-local reason not to:
- Frontend: Next.js + TypeScript + Tailwind + shadcn/ui.
- Backend API: Python + FastAPI + Pydantic.
- DB: PostgreSQL + SQLAlchemy + Alembic.
- Async jobs: Redis + Celery.
- Storage: S3-compatible storage, MinIO for local dev.
- Media processing: FFmpeg.
- ASR: faster-whisper.
- Translation: Argos Translate first, NLLB later if justified.
- Naturalization: self-hosted LLM abstraction.
- Voice cloning: OmniVoice.
- Picture: keep the original frames. Mux the dubbed audio at render.

Avoid for V1:
- Kubernetes.
- Premature microservices.
- Real-time live dubbing.
- Mouth redraw (MuseTalk, Wav2Lip, or any other lip sync). The original picture stays.

## Repository structure target
- `apps/web` → user-facing dashboard.
- `services/api` → FastAPI app, orchestration, REST endpoints.
- `services/worker` → Celery workers and long-running jobs.
- `packages/shared` → shared schemas, types, contracts, helpers.
- `infra/dev` → local infra config.
- `docs` → architecture, ADRs, progress log.
- `scripts` → developer automation and validation.

## Working style
Always work in this order:
1. Understand the task.
2. Inspect existing files and patterns.
3. Update architecture or plan if the change is structural.
4. Implement in small coherent steps.
5. Run validations.
6. Fix failures before moving on.

For larger work, start with a short plan in `docs/implementation-plan.md` or update it if it already exists. Cursor’s agent best practices recommend planning first, keeping rules focused, and using readable repo-level instructions rather than bloated always-on guidance. [web:47][web:71]

## Parallel work
Parallel agents are allowed only for clearly isolated areas such as frontend, backend, workers, docs, or local infra. Do not assign parallel tasks that heavily edit the same files. Nested instructions can live in subdirectory `AGENTS.md` files later if a subtree needs special rules. [web:64][web:69]

## Architecture constraints
- Keep business logic out of route handlers.
- Use service layers and provider abstractions.
- Keep provider-specific code behind stable interfaces.
- Design every pipeline stage as retryable and observable.
- Record pipeline/job state in the database.
- Prefer idempotent operations for workers.
- Every long-running step must expose clear status and error details.
- Mock external AI providers only behind the same interfaces used by real implementations.

## Code style
- TypeScript strict mode for web code.
- Python type hints for backend and workers.
- Small modules, explicit names, minimal cleverness.
- Do not introduce a dependency unless it removes real complexity.
- Follow existing patterns before inventing new ones.
- Keep comments high-signal; explain why, not the obvious what.

## Verification
Before considering a task complete, run the relevant checks that exist in the repo, for example:
- dependency install,
- lint,
- typecheck,
- unit tests,
- DB migrations,
- backend startup,
- frontend build,
- worker import smoke tests,
- `docker-compose` local boot if infra changed.

If something fails, fix it and rerun. Do not claim success without actual verification. Cursor’s docs emphasize being explicit about what the agent should check, change, and produce. [web:67][web:70]

## Files to maintain
Prefer keeping these updated when relevant:
- `README.md`
- `docs/architecture.md`
- `docs/implementation-plan.md`
- `docs/progress-log.md`
- `docs/adr/`

## Voice cloning
Voice cloning of the original speakers is a required product feature, not an optional mode.
- Every dubbed line is spoken by OmniVoice from a sample of the person who said it in the source video.
- A French accent (France, Québec, Belgium, Switzerland) may change wording. It must not replace the clone with edge-tts, espeak, or any other catalog voice.
- Speedups may batch OmniVoice calls. They still pass that speaker's reference audio and clone prompt.
- If the original reference is missing, fail the stage. Do not fall back to a generic voice.
- Do not remove, bypass, or gate the clone path.

## Safety and compliance
This project touches voice cloning and face/video manipulation.
- Require explicit user consent for voice cloning.
- Preserve auditability of who uploaded and generated assets.
- Keep commercial-license risks visible in docs.
- Do not add unsafe deepfake-like features without product-level guardrails.

## Model usage guidance for Cursor
If the agent can choose models, use:
- strongest reasoning model for architecture, planning, provider choices, migrations, concurrency, and debugging;
- balanced/fast model for repetitive scaffolding, routine edits, and secondary docs;
- strongest model again for final debugging and verification.
Do not assume fixed model IDs if the environment exposes different names; inspect what is available first. [web:51][web:55]
