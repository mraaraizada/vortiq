"""Generic website extraction: a plain HTTP fetch + Trafilatura for the main body
text (confirmed live to give cleaner, more article-focused text than a raw
BeautifulSoup body dump — e.g. 4,563 chars of genuine prose from basecamp.com vs.
BeautifulSoup's cruder whole-body text) with BeautifulSoup as the fallback when
Trafilatura returns nothing (common on thin/social pages it can't parse well), and
BeautifulSoup for title/meta/og: tags either way (Trafilatura's own metadata
extraction was confirmed live to miss a real <meta name="description"> present in
the page, so it isn't relied on for that).
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.config import settings
from app.services.extraction.models import ExtractionResult

_NOISE_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe")

#: Real finding (facebook.com/nike, linkedin.com/company/*): a plain HTTP GET gets
#: redirected to a login page, and that login page's OWN content would otherwise
#: get analyzed as if it were the requested brand's real content — a correctness
#: bug, not just thin content. Detected by checking whether the final URL's path,
#: after following redirects, contains one of these markers while the originally
#: requested URL's path did not.
LOGIN_WALL_MARKERS = ("login", "signin", "sign-in", "authwall", "checkpoint", "accounts/login")

#: Below this many characters of real body text, a page is treated as "thin" — see
#: module docstring for the real pages (social profiles) that trigger this.
_THIN_CONTENT_THRESHOLD = 60


class WebsiteExtractionError(Exception):
    """Raised when the website can't be fetched or contains no usable content."""


def best_meta_description(soup: BeautifulSoup) -> str:
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


def check_login_wall(original_url: str, final_url: str) -> None:
    """Raises WebsiteExtractionError if the request was redirected into what looks
    like a login/auth page rather than the requested content."""
    original_path = urlparse(original_url).path.lower()
    final_path = urlparse(final_url).path.lower()
    if final_path != original_path and any(marker in final_path for marker in LOGIN_WALL_MARKERS):
        raise WebsiteExtractionError(
            f"Website redirected to a login/auth page ({final_url}) instead of the requested content — "
            "cannot analyze a login page as if it were the requested site's real content"
        )


async def fetch(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Performs the real GET, translating network-level failures into
    WebsiteExtractionError. Does not itself raise on a login-wall redirect or a
    non-2xx status — callers decide how to react to those (e.g. to try a
    platform-specific fallback first)."""
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
    return resp


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 429:
        retry_after = resp.headers.get("retry-after")
        suffix = f" (retry after {retry_after}s)" if retry_after else ""
        raise WebsiteExtractionError(
            f"Website rate-limited this request (HTTP 429){suffix} — not retried automatically to avoid compounding the rate limit"
        )
    if resp.status_code >= 400:
        raise WebsiteExtractionError(f"Website returned HTTP {resp.status_code}")


def extract_from_html(html: str, final_url: str) -> ExtractionResult:
    """Pure parsing step (no network) — used both by the normal flow and directly
    by tests. Trafilatura provides the main body text when it can; BeautifulSoup
    provides title/meta and is the fallback body-text source."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_description = best_meta_description(soup)

    trafilatura_text = trafilatura.extract(html, url=final_url) or ""
    if trafilatura_text.strip():
        text = " ".join(trafilatura_text.split())[: settings.max_extracted_chars]
    else:
        body = soup.body or soup
        raw_text = body.get_text(separator=" ", strip=True)
        text = " ".join(raw_text.split())[: settings.max_extracted_chars]

    if not text and not title and not meta_description:
        raise WebsiteExtractionError("Website returned no readable text content")

    is_thin_content = len(text) < _THIN_CONTENT_THRESHOLD
    if is_thin_content and meta_description:
        # The body text is near-empty (common for JS-rendered/login-walled pages)
        # but a real meta description exists; use it as the primary content.
        text = meta_description

    return ExtractionResult(title=title, meta_description=meta_description, text=text, final_url=final_url, is_thin_content=is_thin_content)


async def extract_generic_website(client: httpx.AsyncClient, url: str) -> ExtractionResult:
    """The default strategy for any URL not handled by a platform-specific
    adapter (see extraction/router.py)."""
    resp = await fetch(client, url)
    _raise_for_status(resp)
    check_login_wall(url, str(resp.url))

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and content_type:
        raise WebsiteExtractionError(f"URL did not return HTML content (content-type: {content_type})")

    html = resp.text[: settings.max_html_bytes]
    return extract_from_html(html, str(resp.url))
