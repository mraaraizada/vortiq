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
    <body><nav>menu</nav><p>We provide web development services for small and medium
    businesses looking to grow their online presence.</p>
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
    assert result["is_thin_content"] is False


@respx.mock
async def test_prefers_og_description_over_bare_url_meta_description(client):
    # Real finding (x.com): meta name="description" and og:description were both
    # just a bare t.co tracking link, while twitter:description had nothing useful
    # either in that real case — but og:description is still correctly preferred
    # here whenever it's a real, non-URL description and longer than the plain tag.
    html = """
    <html><head><title>Example Profile</title>
    <meta name="description" content="https://t.co/abc123"/>
    <meta property="og:description" content="A real bio describing this profile and what it does."/>
    </head><body></body></html>
    """
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await fetch_and_extract(client, URL)
    assert result["meta_description"] == "A real bio describing this profile and what it does."


@respx.mock
async def test_thin_body_content_falls_back_to_meta_description(client):
    # Real finding (instagram.com): a login-walled profile page's actual body text
    # to a plain HTTP GET is just "Log In Sign Up" — near-useless — while a real,
    # substantive bio lives in the meta description. The near-empty body text must
    # not become the LLM's primary content signal in a case like this.
    html = """
    <html><head><title>Some Profile</title>
    <meta name="description" content="500 Followers - A real bio with actual substance about this account."/>
    </head><body>Log In Sign Up</body></html>
    """
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await fetch_and_extract(client, URL)
    assert result["is_thin_content"] is True
    assert result["text"] == "500 Followers - A real bio with actual substance about this account."


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
