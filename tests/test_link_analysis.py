"""Orchestration tests: full pipeline (mocked extraction + mocked LLM), plus the
real FastAPI route's validation responses."""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.analysis_service import analyze_website

WEBSITE_URL = "https://example.com"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"

_HTML = """
<html><head><title>ABC Technologies</title>
<meta name="description" content="We build web platforms."/></head>
<body><p>We provide web development services for small businesses.</p></body></html>
"""

_VALID_LLM_BODY = {
    "brand": {"name": "ABC Technologies", "category": "Technology Services", "summary": "A tech company."},
    "competitor_analysis": {"brand_overview": "...", "competitors": [], "your_strengths": [], "opportunities": []},
    "target_search_queries": [{"query": "best web dev company", "platforms": ["Google"], "intent": "Service Search"}],
    "seo_improvements": {"primary_keyword": "web development", "recommended_title": "ABC - Web Dev", "meta_description": "We build sites."},
    "top_services": [{"service_name": "Web Development", "description": "...", "inferred": False}],
    "target_audience": {"primary_audience": ["Small businesses"], "industries": ["Retail"], "customer_needs": ["online presence"]},
}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def _mock_all_success():
    respx.get(WEBSITE_URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=_HTML))
    respx.post(GEMINI_ENDPOINT).mock(
        return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(_VALID_LLM_BODY)}]}}]})
    )


@respx.mock
async def test_full_pipeline_success():
    _mock_all_success()
    result = await analyze_website(WEBSITE_URL)
    assert result.success is True
    assert result.brand.name == "ABC Technologies"
    assert result.analysis.top_services[0].service_name == "Web Development"


@respx.mock
async def test_website_fetch_failure_is_a_clean_result_not_a_crash():
    respx.get(WEBSITE_URL).mock(return_value=httpx.Response(500))
    result = await analyze_website(WEBSITE_URL)
    assert result.success is False
    assert result.analysis is None
    assert "500" in result.error


@respx.mock
async def test_llm_failure_is_a_clean_result_not_a_crash():
    respx.get(WEBSITE_URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=_HTML))
    respx.post(GEMINI_ENDPOINT).mock(return_value=httpx.Response(429, json={"error": {"message": "Resource exhausted"}}))
    result = await analyze_website(WEBSITE_URL)
    assert result.success is False
    assert "429" in result.error


@respx.mock
async def test_malformed_llm_schema_is_a_clean_result_not_a_crash():
    respx.get(WEBSITE_URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=_HTML))
    respx.post(GEMINI_ENDPOINT).mock(return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}))
    result = await analyze_website(WEBSITE_URL)
    assert result.success is False
    assert "schema" in result.error


# ---------------------------------------------------------------------------
# Real HTTP-level validation tests against the FastAPI route
# ---------------------------------------------------------------------------

client = TestClient(app)


def test_route_rejects_empty_url():
    resp = client.post("/link-analysis", json={"url": ""})
    assert resp.status_code == 422


def test_route_rejects_invalid_scheme():
    resp = client.post("/link-analysis", json={"url": "ftp://example.com"})
    assert resp.status_code == 422


def test_route_rejects_private_address_ssrf():
    resp = client.post("/link-analysis", json={"url": "http://127.0.0.1/"})
    assert resp.status_code == 422
    assert "private/internal" in resp.text


def test_route_rejects_cloud_metadata_address_ssrf():
    resp = client.post("/link-analysis", json={"url": "http://169.254.169.254/"})
    assert resp.status_code == 422


def test_docs_endpoint_is_available():
    resp = client.get("/docs")
    assert resp.status_code == 200


def test_openapi_schema_is_available():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "Vortiq — AI-Powered Website Link Analysis"
