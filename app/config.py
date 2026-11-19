"""Environment-based configuration. All values default to None/empty so missing
credentials degrade to a clean, explicit error rather than crashing on import."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    gemini_model: str = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"

    request_timeout_seconds: float = float(os.getenv("VORTIQ_REQUEST_TIMEOUT", "15"))
    llm_timeout_seconds: float = float(os.getenv("VORTIQ_LLM_TIMEOUT", "120"))

    #: Hard cap on fetched HTML to bound memory/LLM-prompt size before any cleaning.
    max_html_bytes: int = int(os.getenv("VORTIQ_MAX_HTML_BYTES", str(2_000_000)))
    #: Hard cap on cleaned text characters sent to the LLM, to bound prompt/cost.
    max_extracted_chars: int = int(os.getenv("VORTIQ_MAX_EXTRACTED_CHARS", "12000"))


settings = Settings()
