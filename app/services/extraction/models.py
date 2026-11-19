"""Common extraction result schema — every strategy (generic website, Facebook
oEmbed, Instagram oEmbed, ...) returns this same shape, so the LLM service and
orchestrator never need to know which strategy actually produced it.
"""
from __future__ import annotations

from pydantic import BaseModel


class ExtractionResult(BaseModel):
    title: str = ""
    meta_description: str = ""
    text: str = ""
    final_url: str
    #: True when the extraction had to fall back to minimal signals (a short body,
    #: a login-wall-blocked fetch rescued by oEmbed, etc.) — passed to the LLM so
    #: it's told to be more conservative rather than implying full-page confidence.
    is_thin_content: bool = False
