"""Cloud-only LLM client for lesson-scoped question generation."""

from __future__ import annotations

import logging
import os
import random
import re
import time
from typing import Optional

from backend.app.utils.gemini import (
    configured_gemini_api_key_count,
    get_gemini_client,
)

logger = logging.getLogger(__name__)

LESSON_QA_PROVIDER = os.getenv("LESSON_QUESTION_LLM_PROVIDER", "gemini").lower()
LESSON_QA_MODEL = os.getenv(
    "LESSON_QUESTION_LLM_MODEL", os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
)
LESSON_QA_FALLBACK_MODELS = [
    item.strip()
    for item in re.split(
        r"[\n,]+",
        os.getenv(
            "LESSON_QUESTION_LLM_FALLBACK_MODELS",
            "models/gemini-2.0-flash-lite,models/gemini-2.0-flash",
        ),
    )
    if item.strip()
]
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
LESSON_QA_MODEL_FAILOVER_COOLDOWN_SECONDS = float(
    os.getenv("LESSON_QUESTION_LLM_MODEL_FAILOVER_COOLDOWN_SECONDS", "20")
)


class LessonQuestionLLMClient:
    """Thin provider client used only for question generation."""

    def __init__(self) -> None:
        self.provider = LESSON_QA_PROVIDER
        self.model = LESSON_QA_MODEL
        self.model_candidates = self._build_model_candidates()
        self.init_error: str | None = None
        self.client = self._init_client()
        self.last_error: str | None = None
        self.cooldown_until_ts: float = 0.0
        self._model_cooldowns: dict[str, float] = {}
        self._last_used_model: str | None = None

    def is_available(self) -> bool:
        return self.client is not None

    def get_init_error(self) -> str | None:
        return self.init_error

    def get_last_error(self) -> str | None:
        return self.last_error

    def get_debug_status(self) -> dict:
        now = time.time()
        active_model = self._select_available_model(now=now)
        display_model = active_model or self._last_used_model or self.model
        cooldown_remaining = (
            0.0 if active_model else max(0.0, self.cooldown_until_ts - now)
        )
        api_key_configured = (
            configured_gemini_api_key_count() > 0 if self.provider == "gemini" else False
        )
        return {
            "provider": self.provider,
            "model": display_model,
            "configured_model": self.model,
            "fallback_models": list(self.model_candidates[1:]),
            "provider_supported": self.provider == "gemini",
            "api_key_configured": api_key_configured,
            "client_available": self.is_available(),
            "init_error": self.init_error,
            "last_error": self.last_error,
            "cooldown_active": cooldown_remaining > 0,
            "cooldown_remaining_seconds": int(cooldown_remaining),
        }

    def generate(self, prompt: str) -> str:
        """Generate JSON text from the configured LLM with retry and jittered backoff."""
        if not self.client:
            self.last_error = self.init_error or "Lesson question LLM is not available."
            return ""

        model_name = self._select_available_model()
        if not model_name:
            wait_seconds = self._minimum_model_wait_seconds()
            self.last_error = (
                f"Lesson question LLM cooldown active after quota exhaustion. Retry in {wait_seconds}s."
            )
            return ""

        self.last_error = None
        for attempt in range(1, LESSON_QA_MAX_RETRIES + 1):
            model_name = self._select_available_model()
            if not model_name:
                wait_seconds = self._minimum_model_wait_seconds()
                self.last_error = (
                    "Lesson question LLM model cooldown active after quota exhaustion. "
                    f"Retry in {wait_seconds}s."
                )
                return ""
            try:
                if self.provider == "gemini":
                    self._last_used_model = model_name
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config={
                            "temperature": 0.3,
                            "max_output_tokens": LESSON_QA_MAX_OUTPUT_TOKENS,
                            "response_mime_type": "application/json",
                        },
                    )
                    self.model = model_name
                    text = getattr(response, "text", None)
                    if text:
                        return str(text).strip()
                self.last_error = "Lesson question LLM returned an empty response."
                return ""
            except Exception as exc:  # pragma: no cover - external dependency
                self.last_error = str(exc)
                logger.warning(
                    "Lesson question LLM request failed on attempt %s/%s with model %s: %s",
                    attempt,
                    LESSON_QA_MAX_RETRIES,
                    model_name,
                    exc,
                )
                if self._should_fail_over_model(exc):
                    cooldown = self._compute_model_cooldown_seconds(exc)
                    self._model_cooldowns[model_name] = time.time() + cooldown
                    self.cooldown_until_ts = self._minimum_global_cooldown_until()
                    logger.info(
                        "Lesson question LLM model cooldown set to %.1fs for %s after generation failure.",
                        cooldown,
                        model_name,
                    )
                    if not LESSON_QA_HARD_QUOTA_RETRY_ENABLED and not self._select_available_model():
                        logger.info(
                            "Lesson question LLM exhausted all available models under cooldown; stop retrying early."
                        )
                        break
                if not self._should_fail_over_model(exc):
                    break
                if attempt < LESSON_QA_MAX_RETRIES and self._is_retryable_error(exc):
                    delay = self._compute_retry_delay_seconds(attempt, exc)
                    logger.info(
                        "Lesson question LLM retrying in %.2fs (attempt %s/%s).",
                        delay,
                        attempt + 1,
                        LESSON_QA_MAX_RETRIES,
                    )
                    time.sleep(delay)
        return ""

    def _build_model_candidates(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in [LESSON_QA_MODEL, *LESSON_QA_FALLBACK_MODELS]:
            model_name = str(item or "").strip()
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            ordered.append(model_name)
        return ordered or [LESSON_QA_MODEL]

    def _select_available_model(self, *, now: float | None = None) -> str | None:
        current_time = now if now is not None else time.time()
        for model_name in self.model_candidates:
            if self._model_cooldowns.get(model_name, 0.0) <= current_time:
                return model_name
        return None

    def _minimum_model_wait_seconds(self) -> int:
        now = time.time()
        waits = [
            max(0.0, ts - now)
            for ts in self._model_cooldowns.values()
            if ts > now
        ]
        return max(1, int(min(waits))) if waits else max(
            1, int(max(0.0, self.cooldown_until_ts - now))
        )

    def _minimum_global_cooldown_until(self) -> float:
        future = [ts for ts in self._model_cooldowns.values() if ts > time.time()]
        return min(future) if future else 0.0

    def _init_client(self):
        self.init_error = None
        if self.provider == "gemini":
            try:
                client = get_gemini_client()
                if client is None:
                    self.init_error = (
                        "Gemini API key is not configured. Set GEMINI_API_KEY, "
                        "GEMINI_API_KEYS, or GEMINI_API_KEY_1..N."
                    )
                    return None
                return client
            except Exception as exc:  # pragma: no cover - external dependency
                self.init_error = f"Could not initialize Gemini client: {exc}"
                logger.warning(
                    "Could not initialize lesson question Gemini client: %s", exc
                )
                return None

        self.init_error = f"Unsupported lesson question provider: {self.provider}"
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
    def _is_model_switchable_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "api key" in message
            or "invalid_argument" in message
            or "invalid api key" in message
            or "api_key_invalid" in message
            or "permission denied" in message
            or "401" in message
            or "403" in message
        )

    @classmethod
    def _should_fail_over_model(cls, exc: Exception) -> bool:
        return cls._is_retryable_error(exc) or cls._is_model_switchable_error(exc)

    @staticmethod
    def _is_hard_quota_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "generaterequestsperday" in message
            or "free_tier_requests" in message
            or "perdayperproject" in message
        )

    @staticmethod
    def _compute_model_cooldown_seconds(exc: Exception) -> float:
        retry_after = LessonQuestionLLMClient._extract_retry_delay_seconds(exc) or 0.0
        if LessonQuestionLLMClient._is_hard_quota_error(exc):
            return max(LESSON_QA_HARD_QUOTA_COOLDOWN_SECONDS, retry_after)
        if LessonQuestionLLMClient._is_retryable_error(exc):
            return max(LESSON_QA_MODEL_FAILOVER_COOLDOWN_SECONDS, retry_after)
        return max(1.0, LESSON_QA_MODEL_FAILOVER_COOLDOWN_SECONDS)

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
