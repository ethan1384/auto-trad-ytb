# Implementation plan

## Stack decisions (locked for V1)

| Layer | Choice | Why |
|---|---|---|
| Web | Next.js + TS + Tailwind + shadcn | SaaS dashboard speed; matches reference |
| State | TanStack Query (+ light local state) | Job polling; Zustand only if needed |
| API | FastAPI + Pydantic | AI/media Python ecosystem |
| DB | Postgres + SQLAlchemy 2 + Alembic | Durable jobs/assets |
| Queue | Redis + Celery | Chains for pipeline stages |
| Storage | MinIO (S3 API) | Local-prod parity |
| ASR / MT / rewrite / voice / lipsync | Interfaces + mock defaults | Runnable without GPUs |
| Media | FFmpeg | Extract/align/mux |
| Auth / Stripe | Stub / deferred | Not needed to prove pipeline |

Translation: **Argos Translate** path first (econ V1); NLLB later if quality insufficient.  
Rewrite: abstraction with mock; real = self-hosted LLM / vLLM later.

## Execution order

### Block A — scaffolding (sequential, blocking)
1. Root README, `.env.example`, `docker-compose.yml`
2. `packages/shared` contracts (statuses, stage names)
3. `services/api` skeleton + health
4. `services/worker` Celery app skeleton
5. `apps/web` Next.js skeleton
6. `scripts/dev.sh` + `scripts/verify.sh`

### Block B — backend domain (sequential after A)
7. SQLAlchemy models + Alembic migration
8. Repositories/services (projects, assets, jobs)
9. API routes
10. Storage client (MinIO)
11. Pipeline orchestrator + Celery tasks (mock providers)
12. Backend unit tests

### Block C — frontend (parallelizable with late B once API contracts exist)
13. Layout + dashboard
14. Project create/detail
15. Upload + job start + stage polling

### Block D — verification & polish (sequential)
16. Compose boot + migration
17. verify script green
18. Docs/ADR/progress log update

## Parallelization map

| Task | Mode | Notes |
|---|---|---|
| A1–A6 scaffolding | sequential | Shared roots |
| B7–B12 backend | sequential | Same Python tree |
| C13–C15 frontend | parallelizable vs B after shared contracts | No overlap with `services/*` |
| Docs polish | parallelizable | Avoid fighting README mid-scaffold |

## Task tags

- **S** sequential  
- **P** parallelizable  
- **B** blocking for later work  
- **O** optional V1

1. Monorepo + compose — **S/B**  
2. Shared contracts — **S/B**  
3. API + models + migrations — **S/B**  
4. Worker pipeline mocks — **S/B**  
5. Web dashboard — **P** (after contracts)  
6. Stripe / Clerk — **O**  
7. Real faster-whisper / OmniVoice — **O** (interfaces ready). Mouth redraw stays out.
