"""Orchestrates the full pipeline: fetch -> extract -> LLM -> validate -> response.

Mirrors the suggested processing flow in the spec exactly: receive URL, fetch HTML,
extract content, send to the LLM, validate the LLM's response against the schema,
return structured JSON. Any failure at any step degrades to a clean
`LinkAnalysisResponse(success=False, error=...)` rather than a raw 500.
"""
from __future__ import annotations

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas import Analysis, BrandInfo, LinkAnalysisResponse
from app.services.llm_service import LLMServiceError, analyze_with_gemini
from app.services.website_extractor import WebsiteExtractionError, fetch_and_extract


async def analyze_website(url: str) -> LinkAnalysisResponse:
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            extracted = await fetch_and_extract(client, url)
        except WebsiteExtractionError as exc:
            return LinkAnalysisResponse(success=False, website=url, error=str(exc))

        try:
            raw, _usage = await analyze_with_gemini(
                client, url, extracted["title"], extracted["meta_description"], extracted["text"]
            )
        except LLMServiceError as exc:
            return LinkAnalysisResponse(success=False, website=url, error=str(exc))

    try:
        brand = BrandInfo(**raw["brand"])
        analysis = Analysis(
            competitor_analysis=raw["competitor_analysis"],
            target_search_queries=raw["target_search_queries"],
            seo_improvements=raw["seo_improvements"],
            top_services=raw["top_services"],
            target_audience=raw["target_audience"],
        )
    except (ValidationError, KeyError, TypeError) as exc:
        return LinkAnalysisResponse(success=False, website=url, error=f"LLM response did not match the expected schema: {exc}")

    return LinkAnalysisResponse(success=True, website=extracted["final_url"], brand=brand, analysis=analysis)
