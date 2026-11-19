"""Gemini LLM service tests. All HTTP mocked with respx — no real network calls, no
real API key required."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.config import settings
from app.services.llm_service import LLMServiceError, analyze_with_gemini

ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"


@pytest.fixture
def client():
    return httpx.AsyncClient()


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


_VALID_BODY = {
    "brand": {"name": "ABC Technologies", "category": "Technology Services", "summary": "A tech company."},
    "competitor_analysis": {"brand_overview": "...", "competitors": [], "your_strengths": [], "opportunities": []},
    "target_search_queries": [{"query": "best web dev company", "platforms": ["Google"], "intent": "Service Search"}],
    "seo_improvements": {"primary_keyword": "web development", "recommended_title": "ABC - Web Dev", "meta_description": "We build sites."},
    "top_services": [{"service_name": "Web Development", "description": "...", "inferred": False}],
    "target_audience": {"primary_audience": ["Small businesses"], "industries": ["Retail"], "customer_needs": ["online presence"]},
}


@respx.mock
async def test_successful_structured_response(client):
    import json as _json

    respx.post(ENDPOINT).mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": _json.dumps(_VALID_BODY)}]}}],
                "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 400},
            },
        )
    )
    parsed, usage = await analyze_with_gemini(client, "https://example.com", "Title", "Desc", "some text")
    assert parsed["brand"]["name"] == "ABC Technologies"
    assert usage["promptTokenCount"] == 500


async def test_missing_api_key_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)
    with pytest.raises(LLMServiceError, match="Not configured"):
        await analyze_with_gemini(client, "https://example.com", "T", "D", "text")


@respx.mock
async def test_malformed_json_in_response_is_a_real_failure(client):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))
    with pytest.raises(LLMServiceError, match="not valid JSON"):
        await analyze_with_gemini(client, "https://example.com", "T", "D", "text")


@respx.mock
async def test_empty_candidates_is_a_real_failure(client):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={"candidates": []}))
    with pytest.raises(LLMServiceError, match="no candidates"):
        await analyze_with_gemini(client, "https://example.com", "T", "D", "text")


@respx.mock
async def test_rate_limited_is_a_real_failure(client):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(429, json={"error": {"message": "Resource exhausted"}}))
    with pytest.raises(LLMServiceError, match="429"):
        await analyze_with_gemini(client, "https://example.com", "T", "D", "text")


@respx.mock
async def test_timeout_is_a_real_failure(client):
    respx.post(ENDPOINT).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(LLMServiceError, match="timed out"):
        await analyze_with_gemini(client, "https://example.com", "T", "D", "text")
