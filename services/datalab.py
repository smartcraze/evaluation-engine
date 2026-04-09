import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx
from datalab_sdk import AsyncDatalabClient, ConvertOptions
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


def _get_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    return getattr(result, key, default)


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


def _extract_markdown(result: Any) -> str:
    markdown = _get_value(result, "markdown") or _get_value(result, "output_markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown

    pages = _get_value(result, "pages")
    if isinstance(pages, list):
        collected: list[str] = []
        for page in pages:
            if isinstance(page, dict):
                text = page.get("markdown") or page.get("text")
            else:
                text = getattr(page, "markdown", None) or getattr(page, "text", None)
            if isinstance(text, str) and text.strip():
                collected.append(text)
        if collected:
            return "\n\n".join(collected)

    raise RuntimeError("Datalab response did not include markdown text")


async def convert_to_markdown_via_sdk(
    file: UploadFile,
    mode: str = "accurate",
) -> dict[str, Any]:
    """Convert file using Datalab SDK and wait for markdown result."""
    api_key = _required_env("DATALAB_API_KEY")

    file_bytes = await file.read()
    if not file_bytes:
        raise ValueError("Uploaded file is empty")

    suffix = ".pdf"
    if file.filename and "." in file.filename:
        suffix = f".{file.filename.rsplit('.', 1)[-1]}"

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            temp_path = tmp.name

        options = ConvertOptions(
            output_format="markdown",
            mode=mode,
            paginate=True,
            max_pages=10,
            page_range="0-5,10",
        )

        async_client = AsyncDatalabClient(
            api_key=api_key,
            base_url="https://www.datalab.to",
            timeout=300,
        )

        async with async_client as client:
            result = await client.convert(temp_path, options=options)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

    request_id = _get_value(result, "request_id") or str(uuid.uuid4())
    markdown = _extract_markdown(result)

    return {
        "request_id": str(request_id),
        "markdown": markdown,
    }


async def submit_for_webhook_processing(
    file: UploadFile,
    output_format: str = "markdown",
) -> dict[str, str]:
    """Submit uploaded file to Datalab and return request metadata for webhook mode."""
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
    result = response.json()

    request_id = result.get("request_id")
    request_check_url = result.get("request_check_url")
    if not request_id:
        raise RuntimeError("Datalab response missing request_id")

    return {
        "request_id": str(request_id),
        "request_check_url": str(request_check_url or ""),
    }




