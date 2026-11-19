"""Dispatches a URL to the right extraction strategy by domain. This is the one
place "which platform adapter" is decided — adding a new platform-specific adapter
means adding one entry here plus its own module, nothing else changes.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.services.extraction.base_website import extract_generic_website
from app.services.extraction.facebook import extract_facebook
from app.services.extraction.instagram import extract_instagram
from app.services.extraction.linkedin import extract_linkedin
from app.services.extraction.models import ExtractionResult


def _strip_www(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


_DOMAIN_ADAPTERS = {
    "facebook.com": extract_facebook,
    "instagram.com": extract_instagram,
    "linkedin.com": extract_linkedin,
}


async def extract(client: httpx.AsyncClient, url: str) -> ExtractionResult:
    host = _strip_www(urlparse(url).hostname or "")
    adapter = _DOMAIN_ADAPTERS.get(host, extract_generic_website)
    return await adapter(client, url)
