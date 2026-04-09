import os
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from dotenv import load_dotenv
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.datalab import convert_to_markdown_via_sdk, submit_for_webhook_processing
from services.evaluator import DEFAULT_MAX_MARKS, DEFAULT_MODEL, EvaluationError, evaluate_exam_text
from services.storage import get_job, init_db, save_evaluation, upsert_job

load_dotenv()

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"

app.mount("/public", StaticFiles(directory=str(PUBLIC_DIR)), name="public")


@app.on_event("startup")
async def startup() -> None:
    await init_db()


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(str(PUBLIC_DIR / "index.html"))




async def _convert_localhost(file: UploadFile) -> dict:
    try:
        result = await convert_to_markdown_via_sdk(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    request_id = result["request_id"]
    markdown = result["markdown"]
    await upsert_job(
        request_id=request_id,
        status="received",
        mode="localhost-sdk-auto-poll",
        extracted_text=markdown,
        payload={"source": "datalab-sdk-auto-poll"},
    )

    return {
        "status": "received",
        "request_id": request_id,
        "markdown_length": len(markdown),
        "mode": "localhost-sdk-auto-poll",
    }


@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    return await _convert_localhost(file)


@app.post("/convert/localhost")
async def convert_localhost(file: UploadFile = File(...)):
    return await _convert_localhost(file)


@app.post("/convert/webhook")
async def convert_webhook(file: UploadFile = File(...)):
    try:
        result = await submit_for_webhook_processing(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    request_id = result["request_id"]
    await upsert_job(
        request_id=request_id,
        status="submitted",
        mode="deployed-webhook",
        request_check_url=result.get("request_check_url"),
        extracted_text=None,
        payload={"source": "datalab-webhook-mode", **result},
    )

    return {
        "status": "submitted",
        "mode": "deployed-webhook",
        **result,
    }
    

@app.post("/webhook/datalab")
async def datalab_webhook(request: Request):
    data = await request.json()

    expected_secret = os.getenv("DATALAB_WEBHOOK_SECRET")
    received_secret = data.get("webhook_secret") or request.headers.get("x-webhook-secret")

    if received_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    request_id = data.get("request_id") or data.get("job_id")
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id or job_id is required")

    extracted_text = data.get("markdown") or data.get("extracted_text")
    await upsert_job(
        request_id=str(request_id),
        status="received",
        extracted_text=extracted_text,
        payload=data,
    )

    return {"status": "received"}


@app.get("/result/{request_id}")
async def get_result(request_id: str):
    job = await get_job(request_id)
    if not job:
        raise HTTPException(status_code=404, detail="request_id not found")

    return {
        "request_id": request_id,
        "status": job.status,
        "marks": job.marks,
        "remarks": job.remarks,
        "matched_keywords": job.matched_keywords,
        "missing_keywords": job.missing_keywords,
        "model": job.model_name,
    }


@app.post("/evaluate/{request_id}")
async def evaluate_extracted_answer(
    request_id: str,
    request: Request,
):
    job = await get_job(request_id)
    if not job:
        raise HTTPException(status_code=404, detail="request_id not found")

    try:
        body = await request.json()
    except Exception:
        body = {}

    extracted_exam_text = (job.extracted_text or "").strip()
    if not extracted_exam_text:
        raise HTTPException(status_code=400, detail="No extracted text received for this request_id")

    max_marks = int(body.get("max_marks", DEFAULT_MAX_MARKS))
    model = str(body.get("model", DEFAULT_MODEL))

    try:
        evaluation = await evaluate_exam_text(
            extracted_exam_text=extracted_exam_text,
            max_marks=max_marks,
            model=model,
        )
    except EvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}") from exc

    await save_evaluation(
        request_id=request_id,
        marks=evaluation["marks"],
        remarks=evaluation["remarks"],
        matched_keywords=evaluation["matched_keywords"],
        missing_keywords=evaluation["missing_keywords"],
        model_name=evaluation["model"],
    )

    return {
        "request_id": request_id,
        "status": "completed",
        **evaluation,
    }