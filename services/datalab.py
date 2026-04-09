import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import UploadFile


DATALAB_CONVERT_URL = "https://www.datalab.to/api/v1/convert"
SUPPORTED_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _build_webhook_url() -> str:
    base_url = _required_env("BASE_URL").rstrip("/")
    return f"{base_url}/webhook/datalab"


def _resolve_content_type(file: UploadFile) -> str:
    if file.content_type:
        return file.content_type

    suffix = Path(file.filename or "").suffix.lower()
    content_type = SUPPORTED_CONTENT_TYPES.get(suffix)
    if not content_type:
        raise ValueError(
            "Unsupported file type. Use one of: .jpg, .jpeg, .png, .webp, .pdf"
        )

    return content_type


async def submit_document_for_conversion(
    file: UploadFile,
    output_format: str = "markdown",
) -> dict[str, Any]:
    """Submit uploaded file directly to Datalab without saving it locally."""
    api_key = _required_env("DATALAB_API_KEY")
    webhook_url = _build_webhook_url()
    content_type = _resolve_content_type(file)

    file_bytes = await file.read()
    if not file_bytes:
        raise ValueError("Uploaded file is empty")

    payload_files = {
        "file": (file.filename or "upload.bin", file_bytes, content_type),
    }
    payload_data = {
        "output_format": output_format,
        "mode": "accurate",
        "paginate": "true",
        "max_pages": "10",
        "page_range": "0-5,10",
        "webhook_url": webhook_url,
    }

    headers = {"X-API-Key": api_key}

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DATALAB_CONVERT_URL,
            files=payload_files,
            data=payload_data,
            headers=headers,
        )

    response.raise_for_status()
    return response.json()


async def submit_and_get_request_id(file: UploadFile) -> dict[str, str]:
    """Return only request metadata needed by API clients."""
    result = await submit_document_for_conversion(file=file)

    request_id = result.get("request_id")
    request_check_url = result.get("request_check_url")
    if not request_id:
        raise RuntimeError("Datalab response missing request_id")

    return {
        "request_id": str(request_id),
        "request_check_url": str(request_check_url or ""),
    }




