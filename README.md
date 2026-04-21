# Evaluation Engine

Production-oriented FastAPI service that converts exam documents to markdown (OCR), evaluates student answers with an LLM, and stores full job lifecycle data in PostgreSQL.

This project demonstrates practical full-stack engineering skills recruiters look for: API design, external service integration, schema-backed persistence, frontend integration, and environment-driven deployment workflows.

## Why This Project Matters

- Solves a real workflow: document ingestion -> OCR extraction -> AI evaluation -> persisted results.
- Uses modern backend patterns: FastAPI, async SQLAlchemy, typed service layers, and explicit error handling.
- Built for extension: current architecture supports migration to queue-based workers without breaking API contracts.

## Core Features

- File conversion to markdown via Datalab SDK (`/convert/localhost`) and webhook mode (`/convert/webhook`).
- Secure Datalab webhook receiver with shared-secret validation (`/webhook/datalab`).
- LLM-based exam evaluation with strict JSON contract and deterministic score normalization (`/evaluate/{request_id}`).
- Persistent result lookup API (`/result/{request_id}`).
- OCR quality metrics endpoint with heuristic scoring (`/metrics/markdown`).
- Static frontend served from FastAPI for manual testing and demos (`/`).

## System Architecture

1. Client uploads an exam file.
2. Service sends file to Datalab for OCR/markdown conversion.
3. Extracted markdown is stored in PostgreSQL and written to `public/extracted`.
4. Evaluation endpoint sends extracted text to OpenRouter-compatible model.
5. Marks, remarks, and keyword coverage are persisted and returned through result APIs.

### High-Level Components

- `main.py`: FastAPI app, route handlers, startup lifecycle, static mount.
- `services/datalab.py`: OCR conversion and webhook submission integrations.
- `services/evaluator.py`: LLM prompt contract, JSON parsing, deterministic score derivation.
- `services/storage.py`: SQLAlchemy model, async DB session, upsert/result/metrics operations.
- `public/index.html`: lightweight UI for end-to-end manual verification.

## Tech Stack

- Python (async-first backend)
- FastAPI + Uvicorn
- SQLAlchemy 2.0 (async) + asyncpg
- PostgreSQL
- Datalab OCR API / SDK
- OpenAI Python SDK (OpenRouter endpoint)
- uv (dependency and environment management)

## Full-Stack Engineering Lens

- Backend: async FastAPI APIs, webhook handling, and PostgreSQL persistence.
- AI integration: strict JSON evaluation contract, deterministic post-processing, and robust validation.
- Frontend: browser UI in `public/index.html` for upload/evaluate/result workflows.
- Product flow: complete user journey from file ingestion to stored evaluation output.

## Project Structure

```text
evaluation-engine/
|- main.py
|- pyproject.toml
|- docker-compose.yml
|- Dockerfile
|- services/
|  |- datalab.py
|  |- evaluator.py
|  |- storage.py
|- public/
|  |- index.html
|  |- extracted/
```

## API Surface

### 1) Convert (Local SDK auto-poll)

- `POST /convert`
- `POST /convert/localhost`
- Accepts multipart file (`pdf`, `png`, `jpg`, `jpeg`, `webp`)
- Returns `request_id`, markdown metadata, and public markdown URL

### 2) Convert (Webhook mode)

- `POST /convert/webhook`
- Submits to Datalab with callback URL derived from `BASE_URL`
- Returns `request_id` and optional Datalab check URL

### 3) Datalab Webhook Receiver

- `POST /webhook/datalab`
- Validates `DATALAB_WEBHOOK_SECRET`
- Upserts extracted markdown and marks job as received

### 4) Evaluate Extracted Answer

- `POST /evaluate/{request_id}`
- Body: `max_marks` (int), `model` (string)
- Returns marks, remarks, matched/missing keywords, model used

### 5) Get Result

- `GET /result/{request_id}`
- Returns status + evaluation payload for a job

### 6) Markdown Quality Metrics

- `GET /metrics/markdown`
- Aggregates OCR quality heuristics across processed jobs

## Database Model

`evaluation_jobs` table fields include:

- `request_id` (PK)
- `status`
- `mode`
- `request_check_url`
- `extracted_text`
- `marks`
- `remarks`
- `matched_keywords` (JSON)
- `missing_keywords` (JSON)
- `model_name`
- `payload` (JSON)
- `created_at`, `updated_at`

## Clone and Setup (Quick Start)

### 1) Clone the repository

```bash
git clone https://github.com/<your-org-or-username>/evaluation-engine.git
cd evaluation-engine
```

### 2) Install uv (if needed)

```bash
pip install uv
```

### 3) Install project dependencies

```bash
uv sync
```

### 4) Create `.env` file

```env
# App
APP_NAME=evaluation-engine
BASE_URL=http://localhost:8000

# Database
DATABASE_URL=postgresql+asyncpg://myuser:mypassword@localhost:5432/mydb

# OCR
DATALAB_API_KEY=your_datalab_api_key
DATALAB_WEBHOOK_SECRET=your_webhook_secret

# LLM (OpenRouter)
OPEN_ROUTER_API_KEY=your_openrouter_api_key
```

### 5) Start PostgreSQL

Using Docker Compose:

```bash
docker compose up -d db
```

Or run your own local PostgreSQL instance and point `DATABASE_URL` to it.

### 6) Run the API

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 7) Verify the app

- Open `http://localhost:8000/` for the web UI.
- Use `http://localhost:8000/docs` for interactive API docs.

## Local Setup (Detailed)

### Prerequisites

- Python 3.14+ (as declared in `pyproject.toml`)
- `uv`
- PostgreSQL running locally (or Docker)

### 1) Install dependencies

```bash
uv sync
```

### 2) Configure environment variables

Create a `.env` file in project root:

```env
# App
APP_NAME=evaluation-engine
BASE_URL=http://localhost:8000

# Database
DATABASE_URL=postgresql+asyncpg://myuser:mypassword@localhost:5432/mydb

# OCR
DATALAB_API_KEY=your_datalab_api_key
DATALAB_WEBHOOK_SECRET=your_webhook_secret

# LLM (OpenRouter)
OPEN_ROUTER_API_KEY=your_openrouter_api_key
```

### 3) Start PostgreSQL (optional via Docker)

```bash
docker compose up -d db
```

### 4) Run API

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 5) Open UI

- `http://localhost:8000/`

## cURL Examples

### Convert (localhost mode)

```bash
curl -X POST http://localhost:8000/convert/localhost \
	-F "file=@sample_exam.pdf"
```

### Convert (webhook mode)

```bash
curl -X POST http://localhost:8000/convert/webhook \
	-F "file=@sample_exam.pdf"
```

### Evaluate

```bash
curl -X POST http://localhost:8000/evaluate/<request_id> \
	-H "Content-Type: application/json" \
	-d '{"max_marks": 100, "model": "openai/gpt-oss-120b:free"}'
```

### Result

```bash
curl http://localhost:8000/result/<request_id>
```

## Engineering Decisions

- Async IO for external API calls and DB operations to improve throughput.
- Job lifecycle persistence first, evaluation second, ensuring auditability.
- Deterministic score derived from keyword coverage to reduce LLM variance.
- Structured prompt contract and strict JSON parsing to harden model output handling.

## Reliability and Security Notes

- Webhook secret verification enforced for callback ingestion.
- Missing or malformed upstream responses return explicit HTTP errors.
- Upload validation includes empty file checks and content-type handling.
- Data persists in PostgreSQL for traceability and debugging.

## Recruiter-Focused Highlights

- End-to-end ownership: API design, DB modeling, third-party integrations, and UX demo page.
- AI-in-production mindset: schema validation, deterministic post-processing, and failure handling.
- Clean separation of concerns through service modules.
- Ready for scale evolution: straightforward path to background worker queue in next iteration.
- Full-stack delivery signal: backend services plus browser-accessible workflow for demos and stakeholder reviews.

## Current Limitations

- Database schema is auto-created at startup; migrations are not yet added.
- No dedicated background worker yet; evaluation is API-triggered.
- No automated tests committed yet.

## Suggested Next Iteration

1. Add Alembic migrations and environment-specific config.
2. Introduce worker process with DB locking or queue backend.
3. Add integration tests for OCR/evaluation/result flow.
4. Add structured logging, tracing IDs, and health/readiness endpoints.

## License

This project is provided for educational and portfolio demonstration purposes.
