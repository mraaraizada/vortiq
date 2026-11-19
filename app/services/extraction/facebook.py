"""Facebook extraction adapter.

Strategy: try the normal generic fetch first (works for a genuinely public Page
whenever Facebook doesn't challenge the request); if that hits a login-wall
redirect, fall back to Facebook's own Page oEmbed endpoint, which is live-confirmed
(2026-11-19) to be genuinely tokenless for a public Page — no app registration, no
access token. Docs: https://developers.facebook.com/docs/plugins/oembed
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.services.extraction.base_website import WebsiteExtractionError, extract_generic_website
from app.services.extraction.models import ExtractionResult

_OEMBED_ENDPOINT = "https://graph.facebook.com/v19.0/oembed_page"


async def _try_oembed(client: httpx.AsyncClient, url: str) -> ExtractionResult | None:
    """Never raises — returns None if oEmbed doesn't apply or fails, so the caller
    can fall through to reporting the original restriction honestly."""
    try:
        resp = await client.get(_OEMBED_ENDPOINT, params={"url": url})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    html_snippet = body.get("html") or ""
    name = BeautifulSoup(html_snippet, "html.parser").get_text(strip=True) or body.get("provider_name") or ""
    if not name:
        return None
    return ExtractionResult(
        title=name,
        text=f"Facebook Page: {name} (content limited to what Facebook's oEmbed API exposes without authentication — see README's Known Limitations)",
        final_url=url,
        is_thin_content=True,
    )


async def extract_facebook(client: httpx.AsyncClient, url: str) -> ExtractionResult:
    try:
        return await extract_generic_website(client, url)
    except WebsiteExtractionError as exc:
        if "login/auth page" not in str(exc):
            raise
        fallback = await _try_oembed(client, url)
        if fallback is not None:
            return fallback
        raise
