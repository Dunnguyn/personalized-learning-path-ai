"""Cloud-only LLM client for lesson-scoped question generation."""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

LESSON_QA_PROVIDER = os.getenv("LESSON_QUESTION_LLM_PROVIDER", "gemini").lower()
LESSON_QA_MODEL = os.getenv("LESSON_QUESTION_LLM_MODEL", os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"))
LESSON_QA_MAX_RETRIES = int(os.getenv("LESSON_QUESTION_LLM_MAX_RETRIES", "3"))


class LessonQuestionLLMClient:
    """Thin provider client used only for question generation."""

    def __init__(self) -> None:
        self.provider = LESSON_QA_PROVIDER
        self.model = LESSON_QA_MODEL
        self.client = self._init_client()
        self.last_error: str | None = None

    def is_available(self) -> bool:
        return self.client is not None

    def get_last_error(self) -> str | None:
        return self.last_error

    def generate(self, prompt: str) -> str:
        """Generate JSON text from the configured LLM with simple retry."""
        if not self.client:
            self.last_error = "Lesson question LLM is not available."
            return ""

        self.last_error = None
        for attempt in range(1, LESSON_QA_MAX_RETRIES + 1):
            try:
                if self.provider == "gemini":
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config={
                            "temperature": 0.3,
                            "max_output_tokens": 2400,
                            "response_mime_type": "application/json",
                        },
                    )
                    text = getattr(response, "text", None)
                    if text:
                        return str(text).strip()
                self.last_error = "Lesson question LLM returned an empty response."
                return ""
            except Exception as exc:  # pragma: no cover - external dependency
                self.last_error = str(exc)
                logger.warning(
                    "Lesson question LLM request failed on attempt %s/%s: %s",
                    attempt,
                    LESSON_QA_MAX_RETRIES,
                    exc,
                )
                if self._is_quota_error(exc):
                    break
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
                logger.warning("Could not initialize lesson question Gemini client: %s", exc)
                return None

        logger.warning("Unsupported lesson question provider: %s", self.provider)
        return None

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "resource_exhausted" in message
            or "quota exceeded" in message
            or "rate limit" in message
            or "429" in message
        )
