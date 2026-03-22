"""Cloud-only LLM client for curriculum generation."""

from __future__ import annotations

import logging
import os
import time
from typing import Dict

logger = logging.getLogger(__name__)

CURRICULUM_PROVIDER = os.getenv("LEARNING_PATH_LLM_PROVIDER", "gemini").lower()
CURRICULUM_MODEL = os.getenv(
    "LEARNING_PATH_LLM_MODEL",
    os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
)
CURRICULUM_MAX_RETRIES = int(os.getenv("LEARNING_PATH_LLM_MAX_RETRIES", "3"))


class CurriculumLLMClient:
    """Thin provider client used only for curriculum generation."""

    def __init__(self) -> None:
        self.provider = CURRICULUM_PROVIDER
        self.model = CURRICULUM_MODEL
        self.client = self._init_client()

    def is_available(self) -> bool:
        return self.client is not None

    def status(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "enabled": self.is_available(),
            "cooldown_active": False,
            "reason": None if self.is_available() else "provider_unavailable",
            "model": self.model,
        }

    def generate(self, prompt: str) -> str:
        """Generate curriculum JSON text with simple retry logic."""
        if not self.client:
            return ""

        for attempt in range(1, CURRICULUM_MAX_RETRIES + 1):
            try:
                if self.provider == "gemini":
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config={
                            "temperature": 0.3,
                            "max_output_tokens": 3200,
                            "response_mime_type": "application/json",
                        },
                    )
                    text = getattr(response, "text", None)
                    if text:
                        return str(text).strip()
                return ""
            except Exception as exc:  # pragma: no cover - external dependency
                logger.warning(
                    "Curriculum LLM request failed on attempt %s/%s: %s",
                    attempt,
                    CURRICULUM_MAX_RETRIES,
                    exc,
                )
                time.sleep(min(attempt, 3))
        return ""

    def _init_client(self):
        if self.provider == "gemini":
            try:
                from google import genai

                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    return None
                return genai.Client(api_key=api_key)
            except Exception as exc:  # pragma: no cover - external dependency
                logger.warning("Could not initialize curriculum Gemini client: %s", exc)
                return None

        logger.warning("Unsupported curriculum provider: %s", self.provider)
        return None
