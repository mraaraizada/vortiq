"""Gemini API client: sends the extracted website content and gets back structured
JSON for all five analysis sections in one call.

Uses Gemini's native structured-output support (`responseMimeType: application/json`
+ `responseSchema`) rather than asking the model to "please return JSON" in free text
and hoping — this is what the spec's "reliable structured JSON output" requirement is
actually about, and it's the real mechanism, not a prompt-engineering workaround.

Official docs: https://ai.google.dev/gemini-api/docs/text-generation (generateContent)
             + https://ai.google.dev/gemini-api/docs/structured-output
"""
from __future__ import annotations

import json

import httpx

from app.config import settings

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "brand": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING"},
                "category": {"type": "STRING"},
                "summary": {"type": "STRING"},
            },
            "required": ["name", "category", "summary"],
        },
        "competitor_analysis": {
            "type": "OBJECT",
            "properties": {
                "brand_overview": {"type": "STRING"},
                "main_products_services": {"type": "ARRAY", "items": {"type": "STRING"}},
                "competitors": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING"},
                            "strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "weaknesses": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["name"],
                    },
                },
                "your_strengths": {"type": "ARRAY", "items": {"type": "STRING"}},
                "opportunities": {"type": "ARRAY", "items": {"type": "STRING"}},
                "note": {"type": "STRING"},
            },
            "required": ["brand_overview", "competitors", "your_strengths", "opportunities"],
        },
        "target_search_queries": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING"},
                    "platforms": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "intent": {"type": "STRING"},
                    "target_audience": {"type": "STRING"},
                },
                "required": ["query", "platforms", "intent"],
            },
        },
        "seo_improvements": {
            "type": "OBJECT",
            "properties": {
                "primary_keyword": {"type": "STRING"},
                "secondary_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
                "long_tail_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
                "recommended_title": {"type": "STRING"},
                "meta_description": {"type": "STRING"},
                "supporting_content": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["primary_keyword", "recommended_title", "meta_description"],
        },
        "top_services": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "service_name": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "target_industry": {"type": "STRING"},
                    "target_customer": {"type": "STRING"},
                    "main_benefit": {"type": "STRING"},
                    "inferred": {"type": "BOOLEAN"},
                },
                "required": ["service_name", "description", "inferred"],
            },
        },
        "target_audience": {
            "type": "OBJECT",
            "properties": {
                "primary_audience": {"type": "ARRAY", "items": {"type": "STRING"}},
                "secondary_audience": {"type": "ARRAY", "items": {"type": "STRING"}},
                "industries": {"type": "ARRAY", "items": {"type": "STRING"}},
                "customer_needs": {"type": "ARRAY", "items": {"type": "STRING"}},
                "location_focus": {"type": "STRING"},
            },
            "required": ["primary_audience", "industries", "customer_needs"],
        },
    },
    "required": ["brand", "competitor_analysis", "target_search_queries", "seo_improvements", "top_services", "target_audience"],
}

_PROMPT_TEMPLATE = """You are analyzing a real website for a business intelligence tool. \
Use ONLY the extracted content below — never invent facts about the actual business. \
Where you identify competitors, base them on genuine knowledge of the industry/category; \
if you are not confident a named competitor is real, mark it clearly as an AI-suggested \
possibility inside the "note" field rather than stating it as fact. Do not invent search \
volumes or ranking data — "target_search_queries" should only contain realistic query \
text, platforms, and intent, not fabricated metrics. Any service or audience detail not \
directly present in the extracted content must be marked, where the schema allows it, \
as inferred.
{thin_content_warning}
Website URL: {url}
Page title: {title}
Meta description: {meta_description}

Extracted page text (truncated):
\"\"\"
{text}
\"\"\"

Produce the structured analysis now."""

_THIN_CONTENT_WARNING = (
    "\nIMPORTANT: The page's actual body text could not be read in full (common for "
    "JS-rendered pages, login walls, or social media profiles served to a non-browser "
    "request) — the content above is limited to the page's title and meta description "
    "only. Be noticeably more conservative: mark more fields as inferred where the "
    "schema allows it, and keep the competitor_analysis.note explicit about this "
    "limited basis rather than presenting the analysis with the same confidence as a "
    "fully-read page.\n"
)


class LLMServiceError(Exception):
    """Raised when the LLM call fails or returns an unusable response."""


async def analyze_with_gemini(
    client: httpx.AsyncClient, url: str, title: str, meta_description: str, text: str, is_thin_content: bool = False
) -> tuple[dict, dict]:
    """Returns (parsed_json, usage_metadata). Raises LLMServiceError on failure."""
    if not settings.gemini_api_key:
        raise LLMServiceError("Not configured: GEMINI_API_KEY is required")

    prompt = _PROMPT_TEMPLATE.format(
        url=url,
        title=title or "(none)",
        meta_description=meta_description or "(none)",
        text=text,
        thin_content_warning=_THIN_CONTENT_WARNING if is_thin_content else "",
    )

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            "temperature": 0.4,
        },
    }

    try:
        resp = await client.post(
            endpoint,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=settings.llm_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise LLMServiceError("LLM request timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMServiceError(f"LLM request failed: {exc}") from exc

    if resp.status_code != 200:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except ValueError:
            detail = resp.text[:200]
        raise LLMServiceError(f"Gemini API error (HTTP {resp.status_code}): {detail}")

    body = resp.json()
    candidates = body.get("candidates") or []
    if not candidates:
        raise LLMServiceError("Gemini response contained no candidates")

    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts or "text" not in parts[0]:
        raise LLMServiceError("Gemini response contained no text part")

    try:
        parsed = json.loads(parts[0]["text"])
    except json.JSONDecodeError as exc:
        raise LLMServiceError(f"Gemini response was not valid JSON: {exc}") from exc

    usage = body.get("usageMetadata", {})
    return parsed, usage
