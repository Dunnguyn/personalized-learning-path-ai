"""Cloud-only LLM client for lesson-scoped question generation."""

from __future__ import annotations

import logging
import os
import random
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

LESSON_QA_PROVIDER = os.getenv("LESSON_QUESTION_LLM_PROVIDER", "gemini").lower()
LESSON_QA_MODEL = os.getenv(
    "LESSON_QUESTION_LLM_MODEL", os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
)
LESSON_QA_MAX_RETRIES = int(os.getenv("LESSON_QUESTION_LLM_MAX_RETRIES", "3"))
LESSON_QA_MAX_OUTPUT_TOKENS = int(
    os.getenv("LESSON_QUESTION_LLM_MAX_OUTPUT_TOKENS", "1800")
)
LESSON_QA_RETRY_BASE_DELAY_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_RETRY_BASE_DELAY_SECONDS", "1.0")
)
LESSON_QA_RETRY_MAX_DELAY_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_RETRY_MAX_DELAY_SECONDS", "8.0")
)
LESSON_QA_RETRY_JITTER_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_RETRY_JITTER_SECONDS", "0.5")
)
LESSON_QA_RETRY_HINT_MAX_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_RETRY_HINT_MAX_SECONDS", "45")
)
LESSON_QA_HARD_QUOTA_RETRY_ENABLED = (
    os.getenv("LESSON_QUESTION_LLM_HARD_QUOTA_RETRY_ENABLED", "false")
    .strip()
    .lower()
    in {"1", "true", "yes", "on"}
)
LESSON_QA_HARD_QUOTA_COOLDOWN_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_HARD_QUOTA_COOLDOWN_SECONDS", "300")
)


class LessonQuestionLLMClient:
    """Thin provider client used only for question generation."""

    def __init__(self) -> None:
        self.provider = LESSON_QA_PROVIDER
        self.model = LESSON_QA_MODEL
        self.client = self._init_client()
        self.last_error: str | None = None
        self.cooldown_until_ts: float = 0.0

    def is_available(self) -> bool:
        return self.client is not None

    def get_last_error(self) -> str | None:
        return self.last_error

    def generate(self, prompt: str) -> str:
        """Generate JSON text from the configured LLM with retry and jittered backoff."""
        if not self.client:
            self.last_error = "Lesson question LLM is not available."
            return ""

        now = time.time()
        if now < self.cooldown_until_ts:
            wait_seconds = max(1, int(self.cooldown_until_ts - now))
            self.last_error = (
                f"Lesson question LLM cooldown active after quota exhaustion. Retry in {wait_seconds}s."
            )
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
                            "max_output_tokens": LESSON_QA_MAX_OUTPUT_TOKENS,
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
                if self._is_hard_quota_error(exc):
                    retry_after = self._extract_retry_delay_seconds(exc) or 0.0
                    cooldown = max(LESSON_QA_HARD_QUOTA_COOLDOWN_SECONDS, retry_after)
                    self.cooldown_until_ts = time.time() + cooldown
                    logger.info(
                        "Lesson question LLM cooldown set to %.1fs due to hard quota.",
                        cooldown,
                    )
                    if not LESSON_QA_HARD_QUOTA_RETRY_ENABLED:
                        logger.info(
                            "Lesson question LLM hard quota detected; stop retrying early."
                        )
                        break
                if not self._is_retryable_error(exc):
                    break
                if attempt < LESSON_QA_MAX_RETRIES:
                    delay = self._compute_retry_delay_seconds(attempt, exc)
                    logger.info(
                        "Lesson question LLM retrying in %.2fs (attempt %s/%s).",
                        delay,
                        attempt + 1,
                        LESSON_QA_MAX_RETRIES,
                    )
                    time.sleep(delay)
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
                logger.warning(
                    "Could not initialize lesson question Gemini client: %s", exc
                )
                return None

        logger.warning("Unsupported lesson question provider: %s", self.provider)
        return None

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "resource_exhausted" in message
            or "quota exceeded" in message
            or "rate limit" in message
            or "429" in message
            or "503" in message
            or "unavailable" in message
            or "deadline exceeded" in message
            or "timeout" in message
            or "temporar" in message
        )

    @staticmethod
    def _is_hard_quota_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "generaterequestsperday" in message
            or "free_tier_requests" in message
            or "perdayperproject" in message
        )

    @staticmethod
    def _extract_retry_delay_seconds(exc: Exception) -> float | None:
        message = str(exc)
        match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    @staticmethod
    def _compute_retry_delay_seconds(attempt: int, exc: Exception | None = None) -> float:
        retry_after = LessonQuestionLLMClient._extract_retry_delay_seconds(exc) if exc else None
        if retry_after is not None and retry_after > 0:
            jitter = random.uniform(0.0, max(0.0, LESSON_QA_RETRY_JITTER_SECONDS))
            return min(LESSON_QA_RETRY_HINT_MAX_SECONDS, retry_after + jitter)
        capped_attempt = max(1, attempt)
        base = LESSON_QA_RETRY_BASE_DELAY_SECONDS * (2 ** (capped_attempt - 1))
        jitter = random.uniform(0.0, max(0.0, LESSON_QA_RETRY_JITTER_SECONDS))
        return min(LESSON_QA_RETRY_MAX_DELAY_SECONDS, base + jitter)
