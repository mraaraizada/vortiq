"""Instagram extraction adapter.

Strategy: Instagram's oEmbed endpoint (confirmed live, 2026-11-19) only supports
individual post/reel/IGTV URLs — a real test against a profile URL
(instagram.com/<handle>) returns a real "Invalid parameter" error, while the same
request against a plausible-but-nonexistent post URL (instagram.com/p/<id>/)
returns a different, more specific "Media Not Found" error, indicating the
endpoint DOES recognize and process post-shaped URLs tokenlessly — it simply has
no equivalent for profile pages. Docs:
https://developers.facebook.com/docs/instagram-platform/oembed

So: post/reel/IGTV URLs get a real oEmbed attempt; profile URLs fall through to
the generic extractor, which will honestly report whatever Instagram's anti-bot
system does to it (429/login-wall) rather than pretending a fallback exists where
none does.
"""
from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from app.services.extraction.base_website import extract_generic_website
from app.services.extraction.models import ExtractionResult

_OEMBED_ENDPOINT = "https://graph.facebook.com/v19.0/instagram_oembed"
_POST_PATH_RE = re.compile(r"^/(p|reel|tv)/[^/]+/?$")


def _is_post_url(url: str) -> bool:
    from urllib.parse import urlparse

    return bool(_POST_PATH_RE.match(urlparse(url).path))


async def _try_oembed(client: httpx.AsyncClient, url: str) -> ExtractionResult | None:
    try:
        resp = await client.get(_OEMBED_ENDPOINT, params={"url": url})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    html_snippet = body.get("html") or ""
    author = body.get("author_name") or ""
    title = BeautifulSoup(html_snippet, "html.parser").get_text(strip=True) or author
    if not title:
        return None
    return ExtractionResult(
        title=title,
        text=f"Instagram post by {author or 'unknown author'}: {title}",
        final_url=url,
        is_thin_content=True,
    )


async def extract_instagram(client: httpx.AsyncClient, url: str) -> ExtractionResult:
    if _is_post_url(url):
        fallback = await _try_oembed(client, url)
        if fallback is not None:
            return fallback
    # Either not a post/reel URL (a profile), or oEmbed itself failed — Instagram's
    # oEmbed has no profile-page equivalent, so this falls through to the generic
    # extractor, which will honestly report whatever restriction Instagram applies
    # (429, login-wall, etc.) rather than claiming a fallback that doesn't exist.
    return await extract_generic_website(client, url)
