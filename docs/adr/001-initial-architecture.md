# ADR 001 — Initial V1 architecture

## Status

Accepted

## Context

We need a YouTube dubbing SaaS MVP: ingest → transcribe → translate → rewrite → voice clone → lip sync → render. The team is small; GPU infra should stay optional at first. A technology shortlist is documented in `docs/technologies-reference.md`.

## Decision

Adopt a **modular monorepo**:

- `apps/web` — Next.js dashboard
- `services/api` — FastAPI orchestration API
- `services/worker` — Celery workers
- `packages/shared` — cross-service contracts
- Docker Compose for Postgres, Redis, MinIO
- Provider interfaces with **mock implementations by default**
- Original picture kept. Mouth redraw (MuseTalk, Wav2Lip) is out.
- Argos Translate as first translation provider; NLLB deferred
- Auth and Stripe deferred behind stubs

## Consequences

- Local demo works without GPUs.
- Swapping mocks for real models does not rewrite orchestration.
- Slightly more structure than a single Flask script, but keeps a clear path to production.
- Billing and production auth remain follow-up ADRs.
