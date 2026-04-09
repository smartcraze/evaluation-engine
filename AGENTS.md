## Plan: V1 Postgres-Backed Evaluation Pipeline

Build a queue-less V1 for ~100 users by using PostgreSQL as the source of truth and lightweight job dispatcher: FastAPI accepts upload requests, Datalab webhook stores extracted text and returns immediately, and a separate worker process pulls pending rows from PostgreSQL with locking to run LLM evaluation. This keeps webhook/API non-blocking while preserving clean API-worker separation and an easy upgrade path to Redis/BullMQ later.

**Steps**
1. Phase 1 - Foundation and project bootstrap
2. Add FastAPI app bootstrap in `main.py` with lifespan hooks and versioned API routing in `app/v1` structure.
3. Extend settings in `core/config.py` for Postgres DSN, OpenAI API key/model, Datalab webhook secret, worker polling interval, retry limits, and timeout values.
4. Add Python dependencies via uv workflow: FastAPI, Uvicorn, SQLAlchemy async, asyncpg/psycopg, Pydantic settings, Alembic, OpenAI SDK, HTTP client (httpx), and structured logging.
5. Phase 2 - Data model and persistence
6. Create a single evaluation-job table with fields: `job_id` (unique), `status`, `source_file_url/path`, `expected_answer`, `extracted_text`, `marks`, `remarks`, `attempt_count`, `last_error`, `created_at`, `updated_at`, `processed_at`, plus lock columns (`locked_at`, `locked_by`) for worker coordination.
7. Add status state machine in DB/service layer: `uploaded -> ocr_processing -> ready_for_evaluation -> evaluating -> completed | failed` with idempotent transitions (only legal next states).
8. Add repository/service methods for: create job, upsert webhook text by `job_id`, fetch result by `job_id`, lock-next-pending-job (`FOR UPDATE SKIP LOCKED`), mark success/failure with retries.
9. Phase 3 - API endpoints (non-blocking)
10. Add `POST /v1/upload` to register a job, save metadata+expected answer, call Datalab async, persist returned `job_id`, and return acceptance payload.
11. Add `POST /v1/webhook/datalab` to verify webhook signature, persist extracted text, set status to `ready_for_evaluation`, and return immediately (no LLM call).
12. Add `GET /v1/result/{job_id}` to return status + marks + remarks + timestamps.
13. Keep endpoint logic thin; move all business rules into service layer to preserve clean API/worker separation.
14. Phase 4 - Worker process (no external queue)
15. Build a separate worker entrypoint process (different command from API server) that loops: claim one pending row atomically, set `evaluating`, run LLM evaluation, persist JSON output, set terminal status.
16. Enforce idempotency by guarding duplicate completion updates and never reprocessing `completed` jobs; use unique `job_id` constraint + transactional state checks.
17. Add retry policy for transient failures (OpenAI/network): bounded retries with exponential backoff columns in DB (`next_retry_at`), then `failed` after max attempts.
18. Phase 5 - LLM evaluation contract and safety
19. Define strict system prompt template and user content format (student answer + expected answer when present).
20. Force structured JSON output `{marks:number, remarks:string}` via response-format parsing and strict schema validation before DB write.
21. Add deterministic fallback behavior: if parse fails, retry once with a repair prompt; else mark failed with parse error details.
22. Phase 6 - Ops, observability, and readiness for 100 users
23. Add request/job correlation IDs in logs (`job_id`) across upload, webhook, and worker stages.
24. Add health endpoints: API health and worker health (last successful cycle + queue depth from DB count).
25. Add Docker compose profile for API + worker + Postgres (Valkey remains unused in V1 but can stay for future migration).
26. Add migration notes documenting seamless switch path to BullMQ/Valkey in V2 while preserving the same DB schema and statuses.

**Relevant files**
- `d:/project/evaluation-engine/main.py` — replace hello-world entrypoint with FastAPI app bootstrap and router inclusion.
- `d:/project/evaluation-engine/core/config.py` — centralize environment-driven settings for API, DB, Datalab, OpenAI, and worker tuning.
- `d:/project/evaluation-engine/pyproject.toml` — add runtime and dev dependencies and optional script entrypoints (`api`, `worker`).
- `d:/project/evaluation-engine/docker-compose.yml` — keep Postgres; add API/worker services and environment wiring.
- `d:/project/evaluation-engine/app/` — host API routes, dependencies, services, and DB session wiring.
- `d:/project/evaluation-engine/app/v1/` — versioned endpoints (`upload`, `webhook`, `result`) and router module.
- `d:/project/evaluation-engine/model/` — SQLAlchemy models for evaluation jobs and status transitions.
- `d:/project/evaluation-engine/schema/` — Pydantic request/response schemas and strict LLM output schema.
- `d:/project/evaluation-engine/README.md` — setup/runbook (API + worker commands, env vars, sample cURL flow).

**Verification**
1. Start stack and run DB migration; confirm API and worker processes boot with no startup errors.
2. Call `POST /v1/upload`; verify job row exists with `ocr_processing` and valid `job_id`.
3. Simulate Datalab webhook payload; verify immediate HTTP response and row transitions to `ready_for_evaluation`.
4. Confirm worker claims job and transitions `ready_for_evaluation -> evaluating -> completed`.
5. Call `GET /v1/result/{job_id}` and verify marks/remarks populated in strict JSON contract.
6. Force LLM transient failure and confirm retry increments, backoff scheduling, and eventual `failed` after retry cap.
7. Re-send same webhook for same `job_id`; verify idempotent behavior (no duplicate processing or duplicate row).
8. Run concurrent load test for ~100 users with staggered webhook callbacks; verify stable latency and no deadlocks.

**Decisions**
- Included scope: No Redis/BullMQ in V1; PostgreSQL-backed worker only.
- Included scope: Webhook is persist-and-return only; no LLM/OCR heavy logic inside webhook handler.
- Included scope: Real OpenAI integration now, with strict JSON parsing and validation.
- Included scope: Expected answer provided in request and used by evaluator prompt.
- Excluded scope: Per-question rubric scoring, streaming partial output, caching, and cost optimizer.
- Excluded scope: 1000-user horizontal scale target; this V1 is tuned for ~100 concurrent users.

**Further Considerations**
1. Worker runtime choice recommendation: use a separate Python process managed by container command instead of in-app background tasks for better crash isolation.
2. OpenAI model recommendation for V1: a balanced-cost reasoning model with JSON response-format support to reduce parse failures.
3. DB retention recommendation: keep extracted text + remarks for auditability; add cleanup policy later if storage grows quickly.