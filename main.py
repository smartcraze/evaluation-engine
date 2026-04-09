import os

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from dotenv import load_dotenv

from services.datalab import submit_and_get_request_id
from services.evaluator import DEFAULT_MAX_MARKS, DEFAULT_MODEL, EvaluationError, evaluate_exam_text

load_dotenv()

app = FastAPI()

# Temporary in-memory store for webhook payloads in V1.
# Replace with PostgreSQL persistence in the next step.
WEBHOOK_RESULTS: dict[str, dict] = {}




@app.post("/convert")
async def convert(file: UploadFile = File(...)):
    try:
        result = await submit_and_get_request_id(file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "submitted",
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
    WEBHOOK_RESULTS[str(request_id)] = {
        "payload": data,
        "extracted_text": extracted_text,
        "status": "received",
    }

    return {"status": "received"}


@app.get("/result/{request_id}")
async def get_result(request_id: str):
    data = WEBHOOK_RESULTS.get(request_id)
    if not data:
        raise HTTPException(status_code=404, detail="request_id not found")

    return {
        "request_id": request_id,
        "status": data.get("status", "unknown"),
        "marks": data.get("marks"),
        "remarks": data.get("remarks"),
        "matched_keywords": data.get("matched_keywords"),
        "missing_keywords": data.get("missing_keywords"),
        "model": data.get("model"),
    }


@app.post("/evaluate/{request_id}")
async def evaluate_extracted_answer(
    request_id: str,
    request: Request,
):
    data = WEBHOOK_RESULTS.get(request_id)
    if not data:
        raise HTTPException(status_code=404, detail="request_id not found")

    try:
        body = await request.json()
    except Exception:
        body = {}

    extracted_exam_text = (data.get("extracted_text") or "").strip()
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

    WEBHOOK_RESULTS[request_id]["status"] = "completed"
    WEBHOOK_RESULTS[request_id]["marks"] = evaluation["marks"]
    WEBHOOK_RESULTS[request_id]["remarks"] = evaluation["remarks"]
    WEBHOOK_RESULTS[request_id]["matched_keywords"] = evaluation["matched_keywords"]
    WEBHOOK_RESULTS[request_id]["missing_keywords"] = evaluation["missing_keywords"]
    WEBHOOK_RESULTS[request_id]["model"] = evaluation["model"]

    return {
        "request_id": request_id,
        "status": "completed",
        **evaluation,
    }