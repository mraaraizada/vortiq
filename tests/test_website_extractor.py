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
async def test_redirect_to_login_page_is_a_real_failure_not_mislabeled_success(client):
    # Real finding (facebook.com/nike): a plain GET gets redirected to a login
    # wall, and the login page's OWN content ("Connect with friends...") would
    # otherwise get analyzed as if it were the requested brand's real content —
    # a correctness bug, not just thin content. Must be a reported failure instead.
    target = "https://www.facebook.com/nike"
    login_url = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Fnike"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>Facebook - Log In or Sign Up</title></head><body>Connect with friends.</body></html>",
        )
    )
    # The oEmbed fallback is attempted first for facebook.com; mock it to fail too
    # so this test exercises the final, correctly-reported failure.
    respx.get("https://graph.facebook.com/v19.0/oembed_page").mock(return_value=httpx.Response(404))
    with pytest.raises(WebsiteExtractionError, match="login/auth page"):
        await fetch_and_extract(client, target)


@respx.mock
async def test_redirect_within_same_site_is_not_treated_as_a_login_wall(client):
    # A normal same-site redirect (e.g. http -> https, or a trailing-slash
    # normalization) must NOT be mistaken for a login-wall redirect.
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(301, headers={"location": "https://example.com/page/"})
    )
    respx.get("https://example.com/page/").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Real content here, nothing to do with login.</body></html>")
    )
    result = await fetch_and_extract(client, "https://example.com/page")
    assert "Real content" in result["text"]


@respx.mock
async def test_http_error_status_is_a_real_failure(client):
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(WebsiteExtractionError, match="404"):
        await fetch_and_extract(client, URL)


@respx.mock
async def test_rate_limit_reports_retry_after_instead_of_blind_retry(client):
    # Real finding (instagram.com): a 429 must be reported honestly, including the
    # real Retry-After value when present, never silently retried (which would
    # only compound the rate limit).
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(WebsiteExtractionError, match="retry after 120s"):
        await fetch_and_extract(client, URL)


@respx.mock
async def test_facebook_login_wall_falls_back_to_real_oembed(client):
    # Real finding: Facebook's Page oEmbed (graph.facebook.com/v19.0/oembed_page)
    # is genuinely tokenless and works for a public Page even when the plain GET
    # gets redirected to a login wall — confirmed live. Used only for facebook.com.
    target = "https://www.facebook.com/nike"
    login_url = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Fnike"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Log in</body></html>")
    )
    respx.get("https://graph.facebook.com/v19.0/oembed_page").mock(
        return_value=httpx.Response(
            200,
            json={"provider_name": "Facebook", "html": '<a href="https://www.facebook.com/nike">Nike</a>'},
        )
    )
    result = await fetch_and_extract(client, target)
    assert "Nike" in result["text"]
    assert result["is_thin_content"] is True


@respx.mock
async def test_non_facebook_login_wall_does_not_attempt_facebook_oembed(client):
    # The oEmbed fallback is facebook.com-specific; a login wall on another site
    # (e.g. LinkedIn) must still be reported as a real failure, not silently
    # routed through Facebook's API.
    target = "https://www.linkedin.com/company/example"
    login_url = "https://www.linkedin.com/login?session_redirect=example"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Sign in</body></html>"))
    with pytest.raises(WebsiteExtractionError, match="login/auth page"):
        await fetch_and_extract(client, target)


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
