"""Fetches a website's real HTML and extracts clean, LLM-ready text content.

Deliberately conservative: strips script/style/nav/footer/noise tags, keeps the
title/meta description plus visible body text, and caps the final length so the
LLM prompt stays bounded (see Settings.max_extracted_chars) — this is also the
project's main documented cost-optimization lever (see docs/llm_research.md).
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_NOISE_TAGS = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe")


class WebsiteExtractionError(Exception):
    """Raised when the website can't be fetched or contains no usable content."""


class ExtractedWebsite(dict):
    """Lightweight structured result: title, meta_description, text."""


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

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and content_type:
        raise WebsiteExtractionError(f"URL did not return HTML content (content-type: {content_type})")

    html = resp.text[: settings.max_html_bytes]
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    meta_description = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_description = meta_tag["content"].strip()

    body = soup.body or soup
    raw_text = body.get_text(separator=" ", strip=True)
    text = " ".join(raw_text.split())[: settings.max_extracted_chars]

    if not text and not title:
        raise WebsiteExtractionError("Website returned no readable text content")

    return ExtractedWebsite(title=title, meta_description=meta_description, text=text, final_url=str(resp.url))
