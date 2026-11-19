"""LinkedIn extraction adapter.

No tokenless fallback exists here, unlike Facebook/Instagram: LinkedIn's official
Community Management API requires an approved, registered application with
explicit per-permission grants for company-page data — there is no public,
unauthenticated endpoint equivalent to Facebook/Instagram's oEmbed. Docs:
https://learn.microsoft.com/en-us/linkedin/consumer/
(and LinkedIn's own developer terms explicitly prohibit unauthorized scraping).

So this adapter is a thin pass-through to the generic extractor that gives a
clearer, LinkedIn-specific explanation when the request is blocked, rather than
attempting any workaround.
"""
from __future__ import annotations

import httpx

from app.services.extraction.base_website import WebsiteExtractionError, extract_generic_website
from app.services.extraction.models import ExtractionResult


async def extract_linkedin(client: httpx.AsyncClient, url: str) -> ExtractionResult:
    try:
        return await extract_generic_website(client, url)
    except WebsiteExtractionError as exc:
        message = str(exc)
        if "HTTP 403" in message or "login/auth page" in message:
            raise WebsiteExtractionError(
                "LinkedIn restricted this request (no tokenless public API exists for company/member data — "
                "LinkedIn's Community Management API requires an approved, registered application with explicit "
                "per-permission access). Use the business's own website as the primary source instead."
            ) from exc
        raise
