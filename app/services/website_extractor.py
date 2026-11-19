"""Fetches a website's real HTML and extracts clean, LLM-ready text content.

Deliberately conservative: strips script/style/nav/footer/noise tags, keeps the
title/meta description plus visible body text, and caps the final length so the
LLM prompt stays bounded (see Settings.max_extracted_chars) — this is also the
project's main documented cost-optimization lever (see docs/llm_research.md).
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_NOISE_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe")

#: Real finding (facebook.com/nike): a plain HTTP GET gets redirected to a login
#: page, and httpx's follow_redirects silently lands there — the login page's OWN
#: content (e.g. "Connect with friends, family...") then gets analyzed as if it
#: were the requested brand's real content, which is a real correctness bug, not
#: just thin content. Detected by checking whether the final URL's path, after
#: following redirects, contains one of these markers while the originally
#: requested URL's path did not.
_LOGIN_WALL_MARKERS = ("login", "signin", "sign-in", "authwall", "checkpoint", "accounts/login")

#: Below this many characters of real body text, a page is treated as "thin" —
#: real-world finding: JS-rendered/login-walled pages (social media profiles are
#: the common case) often return a near-empty body (e.g. just "Log In Sign Up")
#: to a plain HTTP GET, even though the page itself has real, visible content for
#: a browser. Below this threshold, og:/twitter: meta tags are preferred as the
#: primary content signal instead, and the LLM is told explicitly that content was
#: limited so it doesn't imply confidence the extraction doesn't actually have.
_THIN_CONTENT_THRESHOLD = 60


class WebsiteExtractionError(Exception):
    """Raised when the website can't be fetched or contains no usable content."""


class ExtractedWebsite(dict):
    """Lightweight structured result: title, meta_description, text, is_thin_content."""


def _best_meta_description(soup: BeautifulSoup) -> str:
    """Prefers whichever of description / og:description / twitter:description is
    longest and non-trivial — real pages (notably social-media profiles) often put
    the actually-useful bio/summary text in og:description or twitter:description
    rather than the plain <meta name="description"> tag, or split it across both
    with one of them being a bare tracking link (observed directly on x.com)."""
    candidates = []
    for selector in (
        {"name": "description"},
        {"property": "og:description"},
        {"name": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            candidates.append(tag["content"].strip())
    # A bare URL (e.g. a t.co tracking link, observed on x.com) isn't real content.
    candidates = [c for c in candidates if c and not c.lower().startswith(("http://", "https://"))]
    return max(candidates, key=len, default="")


async def fetch_and_extract(client: httpx.AsyncClient, url: str) -> ExtractedWebsite:
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": "Vortiq-LinkAnalysis/1.0 (+https://github.com)"},
            follow_redirects=True,
        )
    except httpx.TimeoutException as exc:
        raise WebsiteExtractionError("Website did not respond in time") from exc
    except httpx.HTTPError as exc:
        raise WebsiteExtractionError(f"Could not reach website: {exc}") from exc

    if resp.status_code >= 400:
        raise WebsiteExtractionError(f"Website returned HTTP {resp.status_code}")

    original_path = urlparse(url).path.lower()
    final_path = urlparse(str(resp.url)).path.lower()
    if final_path != original_path and any(marker in final_path for marker in _LOGIN_WALL_MARKERS):
        raise WebsiteExtractionError(
            f"Website redirected to a login/auth page ({resp.url}) instead of the requested content — "
            "cannot analyze a login page as if it were the requested site's real content"
        )

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and content_type:
        raise WebsiteExtractionError(f"URL did not return HTML content (content-type: {content_type})")

    html = resp.text[: settings.max_html_bytes]
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_description = _best_meta_description(soup)

    body = soup.body or soup
    raw_text = body.get_text(separator=" ", strip=True)
    text = " ".join(raw_text.split())[: settings.max_extracted_chars]

    if not text and not title and not meta_description:
        raise WebsiteExtractionError("Website returned no readable text content")

    is_thin_content = len(text) < _THIN_CONTENT_THRESHOLD
    if is_thin_content and meta_description:
        # The body text is near-empty (common for JS-rendered/login-walled pages —
        # see the module docstring) but a real meta description exists; use it as
        # the primary content instead of the near-empty body text.
        text = meta_description

    return ExtractedWebsite(
        title=title,
        meta_description=meta_description,
        text=text,
        final_url=str(resp.url),
        is_thin_content=is_thin_content,
    )
