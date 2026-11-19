"""Opt-in live end-to-end tests: real website fetch + real Gemini API call.

Excluded from the default `pytest` run (see pytest.ini's `addopts = -m "not live"`).
Run explicitly with `pytest -m live -v -s` once a real GEMINI_API_KEY is in `.env`.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.analysis_service import analyze_website

pytestmark = pytest.mark.live


async def test_live_analysis_of_a_real_website():
    if not settings.gemini_api_key:
        pytest.skip("GEMINI_API_KEY not configured")

    result = await analyze_website("https://httpbin.org")
    print("\n--- Live /link-analysis result ---")
    print(result.model_dump_json(indent=2))

    assert result.website
    if result.success:
        assert result.brand is not None
        assert result.analysis is not None
        assert len(result.analysis.target_search_queries) > 0
        assert len(result.analysis.top_services) > 0
    else:
        # Still a well-formed, honest failure result, not a crash.
        assert result.error
