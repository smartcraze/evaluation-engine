import json
import os
import re
from typing import Any

from openai import AsyncOpenAI


DEFAULT_MODEL = "openai/gpt-oss-120b:free"
DEFAULT_MAX_MARKS = 100


class EvaluationError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EvaluationError(f"Missing required environment variable: {name}")
    return value


def _normalize_keywords(items: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        text = re.sub(r"\s+", " ", item.strip().lower())
        if not text:
            continue
        if text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def _deterministic_marks(max_marks: int, matched_keywords: list[str], missing_keywords: list[str]) -> float:
    total_keywords = len(matched_keywords) + len(missing_keywords)
    if total_keywords == 0:
        return float(max_marks) * 0.5
    coverage = len(matched_keywords) / total_keywords
    return round(max(0.0, min(float(max_marks), float(max_marks) * coverage)), 2)


def _build_system_prompt(max_marks: int) -> str:
    return f"""
You are an expert academic examiner.

ROLE AND OBJECTIVE
- Evaluate OCR-extracted exam text that includes questions and student responses.
- Be strict, objective, and evidence-based.
- Award marks out of {max_marks}.

MANDATORY EVALUATION RULES
1. Use only information present in the extracted exam text.
2. Do not invent facts, references, or assumptions.
3. Infer required concepts/keywords from each question and compare with the corresponding answer.
4. Give credit for correct concepts even when exact wording differs.
5. Deduct marks for missing required concepts, factual errors, contradictions, and irrelevant content.
6. If answer content is empty or off-topic, award very low marks.
7. Keep marks within [0, {max_marks}] and allow decimals when justified.

KEYWORD CHECKING REQUIREMENTS
- Extract essential keywords/concepts from the question context.
- Perform concept-based matching against student answers.
- Produce aggregated evidence lists:
    - matched_keywords: required concepts found in answers
    - missing_keywords: required concepts not found in answers
- Do not add speculative keywords that are not supported by question text.

PARSING GUIDANCE
- If multiple questions exist, evaluate all identifiable Q/A sections.
- OCR can be noisy; use conservative interpretation.
- If text is ambiguous, mention uncertainty briefly in remarks and score cautiously.

SCORING RUBRIC
- Correctness and factual accuracy: 40%
- Coverage of required keywords/concepts: 40%
- Clarity and relevance: 20%

REMARKS QUALITY REQUIREMENTS
- Be concise but specific.
- Mention what was correct.
- Clearly explain deductions and what was missing.
- Avoid generic phrases like "needs improvement" without reasons.

OUTPUT CONTRACT (STRICT)
- Return ONLY valid JSON.
- No markdown, no code block fences, no extra keys, no explanatory text outside JSON.
- Exact schema:
    {{
        "marks": number,
        "remarks": "string",
        "matched_keywords": ["string"],
        "missing_keywords": ["string"]
    }}

VALIDATION CHECKLIST BEFORE FINAL OUTPUT
- Is marks a number?
- Is marks inside [0, {max_marks}]?
- Are remarks clear and deduction-focused?
- Are matched_keywords and missing_keywords arrays of strings?
- Is the response strictly valid JSON with exactly four keys?

CONSISTENCY REQUIREMENT
- For identical input text, keep keyword extraction and grading decision stable.
- Prefer deterministic keyword identification over creative paraphrasing.
""".strip()


async def evaluate_exam_text(
    extracted_exam_text: str,
    max_marks: int = DEFAULT_MAX_MARKS,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    if not extracted_exam_text.strip():
        raise EvaluationError("extracted_exam_text is required")

    api_key = _required_env("OPEN_ROUTER_API_KEY")

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    user_prompt = (
        "Evaluate the OCR-extracted exam text using the rubric.\n\n"
        f"MAX_MARKS: {max_marks}\n\n"
        "EXTRACTED_EXAM_TEXT:\n"
        f"{extracted_exam_text}\n\n"
        "Return JSON only with keys: marks, remarks, matched_keywords, missing_keywords."
    )

    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _build_system_prompt(max_marks)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        extra_headers={
            "HTTP-Referer": os.getenv("BASE_URL", "http://localhost"),
            "X-OpenRouter-Title": os.getenv("APP_NAME", "evaluation-engine"),
        },
    )

    content = (completion.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"Model did not return valid JSON: {content}") from exc

    marks = parsed.get("marks")
    remarks = parsed.get("remarks")
    matched_keywords = parsed.get("matched_keywords")
    missing_keywords = parsed.get("missing_keywords")

    if not isinstance(marks, (int, float)):
        raise EvaluationError("Invalid marks type returned by model")
    if not isinstance(remarks, str):
        raise EvaluationError("Invalid remarks type returned by model")
    if not isinstance(matched_keywords, list) or not all(
        isinstance(item, str) for item in matched_keywords
    ):
        raise EvaluationError("Invalid matched_keywords returned by model")
    if not isinstance(missing_keywords, list) or not all(
        isinstance(item, str) for item in missing_keywords
    ):
        raise EvaluationError("Invalid missing_keywords returned by model")

    normalized_matched_keywords = _normalize_keywords(matched_keywords)
    normalized_missing_keywords = _normalize_keywords(missing_keywords)

    # Ensure a keyword does not appear in both lists.
    matched_set = set(normalized_matched_keywords)
    normalized_missing_keywords = [item for item in normalized_missing_keywords if item not in matched_set]

    # Use deterministic final score from keyword coverage to reduce run-to-run drift.
    deterministic_marks = _deterministic_marks(
        max_marks=max_marks,
        matched_keywords=normalized_matched_keywords,
        missing_keywords=normalized_missing_keywords,
    )

    bounded_marks = max(0.0, min(float(max_marks), deterministic_marks))

    if not isinstance(marks, (int, float)):
        marks = bounded_marks

    return {
        "marks": bounded_marks,
        "remarks": remarks.strip(),
        "matched_keywords": normalized_matched_keywords,
        "missing_keywords": normalized_missing_keywords,
        "model": model,
        "llm_marks": float(marks),
    }
