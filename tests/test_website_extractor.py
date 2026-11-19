"""Website extraction tests. All HTTP mocked with respx — no real network calls."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.services.website_extractor import WebsiteExtractionError, fetch_and_extract

URL = "https://example.com"


@pytest.fixture
def client():
    return httpx.AsyncClient()


@respx.mock
async def test_extracts_title_meta_and_text(client):
    html = """
    <html><head><title>ABC Technologies</title>
    <meta name="description" content="We build web platforms."/>
    <script>var x = 1;</script></head>
    <body><nav>menu</nav><p>We provide web development services.</p>
    <footer>copyright</footer></body></html>
    """
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await fetch_and_extract(client, URL)
    assert result["title"] == "ABC Technologies"
    assert result["meta_description"] == "We build web platforms."
    assert "web development services" in result["text"]
    assert "menu" not in result["text"]
    assert "copyright" not in result["text"]
    assert "var x = 1" not in result["text"]


@respx.mock
async def test_http_error_status_is_a_real_failure(client):
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(WebsiteExtractionError, match="404"):
        await fetch_and_extract(client, URL)


@respx.mock
async def test_non_html_content_type_rejected(client):
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    with pytest.raises(WebsiteExtractionError, match="content-type"):
        await fetch_and_extract(client, URL)


@respx.mock
async def test_timeout_is_a_real_failure(client):
    respx.get(URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(WebsiteExtractionError, match="did not respond"):
        await fetch_and_extract(client, URL)


@respx.mock
async def test_empty_page_is_a_real_failure(client):
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><head></head><body></body></html>"))
    with pytest.raises(WebsiteExtractionError, match="no readable text"):
        await fetch_and_extract(client, URL)
