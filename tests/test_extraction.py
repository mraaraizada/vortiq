"""Extraction tests for the platform-adapter architecture (app/services/extraction/).
All HTTP mocked with respx — no real network calls."""
from __future__ import annotations

import httpx
import pytest
import respx

from app.services.extraction.base_website import WebsiteExtractionError, extract_generic_website
from app.services.extraction.facebook import extract_facebook
from app.services.extraction.instagram import extract_instagram
from app.services.extraction.linkedin import extract_linkedin
from app.services.extraction.router import extract

URL = "https://example.com"


@pytest.fixture
def client():
    return httpx.AsyncClient()


# ---------------------------------------------------------------------------
# Generic website extraction (base_website.py)
# ---------------------------------------------------------------------------


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
    result = await extract_generic_website(client, URL)
    assert result.title == "ABC Technologies"
    assert result.meta_description == "We build web platforms."
    assert "web development services" in result.text
    assert "menu" not in result.text
    assert "copyright" not in result.text
    assert "var x = 1" not in result.text
    assert result.is_thin_content is False


@respx.mock
async def test_prefers_og_description_over_bare_url_meta_description(client):
    # Real finding (x.com): meta name="description" was just a bare t.co tracking
    # link — og:description is correctly preferred here whenever it's real content.
    html = """
    <html><head><title>Example Profile</title>
    <meta name="description" content="https://t.co/abc123"/>
    <meta property="og:description" content="A real bio describing this profile and what it does."/>
    </head><body></body></html>
    """
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await extract_generic_website(client, URL)
    assert result.meta_description == "A real bio describing this profile and what it does."


@respx.mock
async def test_thin_body_content_falls_back_to_meta_description(client):
    # Real finding (instagram.com): a login-walled profile page's actual body text
    # to a plain HTTP GET is just "Log In Sign Up" — near-useless — while a real,
    # substantive bio lives in the meta description.
    html = """
    <html><head><title>Some Profile</title>
    <meta name="description" content="500 Followers - A real bio with actual substance about this account."/>
    </head><body>Log In Sign Up</body></html>
    """
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await extract_generic_website(client, URL)
    assert result.is_thin_content is True
    assert result.text == "500 Followers - A real bio with actual substance about this account."


@respx.mock
async def test_redirect_to_login_page_is_a_real_failure_not_mislabeled_success(client):
    # Real finding (facebook.com/nike): a plain GET gets redirected to a login
    # wall, and the login page's OWN content would otherwise get analyzed as if it
    # were the requested brand's real content — a correctness bug, not just thin
    # content. Must be a reported failure (generic extractor has no oEmbed rescue).
    target = "https://www.somesite-with-a-wall.com/nike"
    login_url = "https://www.somesite-with-a-wall.com/login/?next=/nike"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Log in to continue</body></html>")
    )
    with pytest.raises(WebsiteExtractionError, match="login/auth page"):
        await extract_generic_website(client, target)


@respx.mock
async def test_redirect_within_same_site_is_not_treated_as_a_login_wall(client):
    respx.get("https://example.com/page").mock(return_value=httpx.Response(301, headers={"location": "https://example.com/page/"}))
    respx.get("https://example.com/page/").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Real content here, nothing to do with login.</body></html>")
    )
    result = await extract_generic_website(client, "https://example.com/page")
    assert "Real content" in result.text


@respx.mock
async def test_http_error_status_is_a_real_failure(client):
    respx.get(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(WebsiteExtractionError, match="404"):
        await extract_generic_website(client, URL)


@respx.mock
async def test_rate_limit_reports_retry_after_instead_of_blind_retry(client):
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(WebsiteExtractionError, match="retry after 120s"):
        await extract_generic_website(client, URL)


@respx.mock
async def test_non_html_content_type_rejected(client):
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    with pytest.raises(WebsiteExtractionError, match="content-type"):
        await extract_generic_website(client, URL)


@respx.mock
async def test_timeout_is_a_real_failure(client):
    respx.get(URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(WebsiteExtractionError, match="did not respond"):
        await extract_generic_website(client, URL)


@respx.mock
async def test_empty_page_is_a_real_failure(client):
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><head></head><body></body></html>"))
    with pytest.raises(WebsiteExtractionError, match="no readable text"):
        await extract_generic_website(client, URL)


# ---------------------------------------------------------------------------
# Facebook adapter (facebook.py)
# ---------------------------------------------------------------------------


@respx.mock
async def test_facebook_login_wall_falls_back_to_real_oembed(client):
    # Real finding: Facebook's Page oEmbed (graph.facebook.com/v19.0/oembed_page)
    # is genuinely tokenless and works for a public Page even when the plain GET
    # gets redirected to a login wall — confirmed live.
    target = "https://www.facebook.com/nike"
    login_url = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Fnike"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Log in</body></html>"))
    respx.get("https://graph.facebook.com/v19.0/oembed_page").mock(
        return_value=httpx.Response(200, json={"provider_name": "Facebook", "html": '<a href="https://www.facebook.com/nike">Nike</a>'})
    )
    result = await extract_facebook(client, target)
    assert "Nike" in result.text
    assert result.is_thin_content is True


@respx.mock
async def test_facebook_succeeds_normally_when_no_login_wall(client):
    # When Facebook doesn't challenge the request, the oEmbed fallback is never
    # even attempted — the normal extractor result is used directly.
    target = "https://www.facebook.com/nike"
    html = "<html><head><title>Nike</title><meta name='description' content='Just Do It.'/></head><body>Real page content about Nike products, apparel, and the latest footwear news updates.</body></html>"
    respx.get(target).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await extract_facebook(client, target)
    assert result.title == "Nike"
    assert result.is_thin_content is False


@respx.mock
async def test_facebook_oembed_failure_still_reports_the_original_restriction(client):
    target = "https://www.facebook.com/nike"
    login_url = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2Fnike"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Log in</body></html>"))
    respx.get("https://graph.facebook.com/v19.0/oembed_page").mock(return_value=httpx.Response(404))
    with pytest.raises(WebsiteExtractionError, match="login/auth page"):
        await extract_facebook(client, target)


# ---------------------------------------------------------------------------
# Instagram adapter (instagram.py)
# ---------------------------------------------------------------------------


@respx.mock
async def test_instagram_post_url_uses_oembed(client):
    target = "https://www.instagram.com/p/Cxxxxxx/"
    respx.get("https://graph.facebook.com/v19.0/instagram_oembed").mock(
        return_value=httpx.Response(200, json={"author_name": "nike", "html": "<blockquote>A post about new shoes</blockquote>"})
    )
    result = await extract_instagram(client, target)
    assert "nike" in result.text
    assert result.is_thin_content is True


@respx.mock
async def test_instagram_profile_url_has_no_oembed_and_falls_through_to_generic(client):
    # Real finding: Instagram's oEmbed only supports post/reel URLs, not profile
    # pages — a profile URL must go straight to the generic extractor (which will
    # honestly report whatever restriction Instagram applies), never attempt
    # oEmbed for a shape it doesn't support.
    target = "https://www.instagram.com/crestspot"
    respx.get(target).mock(return_value=httpx.Response(429, headers={"retry-after": "60"}))
    with pytest.raises(WebsiteExtractionError, match="retry after 60s"):
        await extract_instagram(client, target)


@respx.mock
async def test_instagram_post_oembed_failure_falls_through_to_generic(client):
    target = "https://www.instagram.com/p/Cxxxxxx/"
    respx.get("https://graph.facebook.com/v19.0/instagram_oembed").mock(return_value=httpx.Response(404))
    respx.get(target).mock(return_value=httpx.Response(429))
    with pytest.raises(WebsiteExtractionError, match="429"):
        await extract_instagram(client, target)


# ---------------------------------------------------------------------------
# LinkedIn adapter (linkedin.py) — no tokenless fallback exists
# ---------------------------------------------------------------------------


@respx.mock
async def test_linkedin_403_gets_a_clear_explanation_not_a_fake_workaround(client):
    target = "https://www.linkedin.com/company/microsoft"
    respx.get(target).mock(return_value=httpx.Response(403))
    with pytest.raises(WebsiteExtractionError, match="Community Management API"):
        await extract_linkedin(client, target)


@respx.mock
async def test_linkedin_succeeds_normally_when_not_blocked(client):
    target = "https://www.linkedin.com/company/example"
    html = "<html><head><title>Example Inc</title></head><body>A real company description with enough content to not be thin.</body></html>"
    respx.get(target).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await extract_linkedin(client, target)
    assert result.title == "Example Inc"


# ---------------------------------------------------------------------------
# Router (router.py) — the single place platform selection is decided
# ---------------------------------------------------------------------------


@respx.mock
async def test_router_dispatches_facebook_urls_to_the_facebook_adapter(client):
    target = "https://www.facebook.com/nike"
    login_url = "https://www.facebook.com/login/?next=x"
    respx.get(target).mock(return_value=httpx.Response(302, headers={"location": login_url}))
    respx.get(login_url).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Log in</body></html>"))
    respx.get("https://graph.facebook.com/v19.0/oembed_page").mock(
        return_value=httpx.Response(200, json={"provider_name": "Facebook", "html": "<a>Nike</a>"})
    )
    result = await extract(client, target)
    assert "Nike" in result.text


@respx.mock
async def test_router_dispatches_unknown_domains_to_the_generic_extractor(client):
    html = "<html><head><title>A Real Site</title></head><body>Plenty of real content about this business and its services.</body></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, headers={"content-type": "text/html"}, text=html))
    result = await extract(client, URL)
    assert result.title == "A Real Site"
