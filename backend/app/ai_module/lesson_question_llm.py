"""Cloud-only LLM client for lesson-scoped question generation."""

from __future__ import annotations

import logging
import os
import random
import re
import time
from typing import Optional

from backend.app.utils.gemini import (
    build_gemini_model_candidates,
    configured_gemini_api_key_count,
    get_gemini_client,
    get_gemini_model_scope_status,
    is_gemini_capacity_exhausted_error,
    is_gemini_failover_error,
    is_gemini_hard_quota_error,
    is_gemini_invalid_key_error,
    is_gemini_transient_unavailable_error,
)

logger = logging.getLogger(__name__)

LESSON_QA_PROVIDER = os.getenv("LESSON_QUESTION_LLM_PROVIDER", "gemini").lower()
LESSON_QA_MODEL = os.getenv(
    "LESSON_QUESTION_LLM_MODEL", os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
)
LESSON_QA_FALLBACK_MODELS = os.getenv("LESSON_QUESTION_LLM_FALLBACK_MODELS")
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
            0.0 if active_model else self._minimum_model_wait_seconds(now=now)
        )
        api_key_configured = (
            configured_gemini_api_key_count() > 0 if self.provider == "gemini" else False
        )
        scope_status = self._get_model_scope_status(display_model, now=now)
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
            "scope_cooldown_active": bool(scope_status.get("cooldown_active")),
            "scope_cooldown_remaining_seconds": int(
                scope_status.get("retry_after_seconds", 0) or 0
            ),
            "available_key_count": int(scope_status.get("available_key_count", 0) or 0),
            "total_key_count": int(scope_status.get("total_key_count", 0) or 0),
        }

    def generate(self, prompt: str) -> str:
        """Generate JSON text from the configured LLM with retry and jittered backoff."""
        if not self.client:
            self.last_error = self.init_error or "Lesson question LLM is not available."
            return ""

        if not self._available_model_candidates():
            wait_seconds = self._minimum_model_wait_seconds()
            self.last_error = (
                f"Lesson question LLM cooldown active after quota exhaustion. Retry in {wait_seconds}s."
            )
            return ""

        self.last_error = None
        for attempt in range(1, LESSON_QA_MAX_RETRIES + 1):
            candidate_models = self._available_model_candidates()
            if not candidate_models:
                wait_seconds = self._minimum_model_wait_seconds()
                self.last_error = (
                    "Lesson question LLM model cooldown active after quota exhaustion. "
                    f"Retry in {wait_seconds}s."
                )
                return ""
            retryable_error: Exception | None = None
            should_stop = False
            for model_name in candidate_models:
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
                        if self._is_retryable_error(exc):
                            retryable_error = exc
                        continue
                    should_stop = True
                    break
            if should_stop:
                break
            if (
                not LESSON_QA_HARD_QUOTA_RETRY_ENABLED
                and not self._available_model_candidates()
            ):
                logger.info(
                    "Lesson question LLM exhausted all available models under cooldown; stop retrying early."
                )
                break
            if attempt < LESSON_QA_MAX_RETRIES and retryable_error is not None:
                delay = self._compute_retry_delay_seconds(attempt, retryable_error)
                logger.info(
                    "Lesson question LLM retrying in %.2fs (attempt %s/%s).",
                    delay,
                    attempt + 1,
                    LESSON_QA_MAX_RETRIES,
                )
                time.sleep(delay)
        return ""

    def _build_model_candidates(self) -> list[str]:
        return build_gemini_model_candidates(
            LESSON_QA_MODEL,
            LESSON_QA_FALLBACK_MODELS,
        ) or [LESSON_QA_MODEL]

    def _select_available_model(self, *, now: float | None = None) -> str | None:
        candidates = self._available_model_candidates(now=now)
        return candidates[0] if candidates else None

    def _available_model_candidates(self, *, now: float | None = None) -> list[str]:
        current_time = now if now is not None else time.time()
        return [
            model_name
            for model_name in self.model_candidates
            if self._model_wait_seconds(model_name, now=current_time) <= 0
        ]

    def _minimum_model_wait_seconds(self, *, now: float | None = None) -> int:
        current_time = now if now is not None else time.time()
        waits = [
            self._model_wait_seconds(model_name, now=current_time)
            for model_name in self.model_candidates
        ]
        positive_waits = [wait for wait in waits if wait > 0]
        if positive_waits:
            return max(1, int(min(positive_waits)))
        return max(1, int(max(0.0, self.cooldown_until_ts - current_time)))

    def _minimum_global_cooldown_until(self) -> float:
        future = [ts for ts in self._model_cooldowns.values() if ts > time.time()]
        return min(future) if future else 0.0

    def _model_wait_seconds(
        self, model_name: str, *, now: float | None = None
    ) -> float:
        current_time = now if now is not None else time.time()
        local_wait = max(0.0, self._model_cooldowns.get(model_name, 0.0) - current_time)
        scope_status = self._get_model_scope_status(model_name, now=current_time)
        scope_wait = float(scope_status.get("retry_after_seconds", 0.0) or 0.0)
        return max(local_wait, scope_wait)

    def _get_model_scope_status(
        self, model_name: str | None, *, now: float | None = None
    ) -> dict:
        if self.provider != "gemini" or not model_name:
            return {}
        status = get_gemini_model_scope_status(model_name)
        if now is None:
            return status
        # Keep derived status aligned when a cached `now` is already available.
        scope_wait = max(
            0.0,
            float(status.get("scope_cooldown_remaining_seconds", 0.0) or 0.0),
        )
        retry_after = max(0.0, float(status.get("retry_after_seconds", 0.0) or 0.0))
        status["scope_cooldown_active"] = scope_wait > 0
        status["cooldown_active"] = bool(status.get("cooldown_active")) or retry_after > 0
        return status

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
        return is_gemini_transient_unavailable_error(exc) or is_gemini_capacity_exhausted_error(exc)

    @staticmethod
    def _is_model_switchable_error(exc: Exception) -> bool:
        return is_gemini_invalid_key_error(exc)

    @classmethod
    def _should_fail_over_model(cls, exc: Exception) -> bool:
        return is_gemini_failover_error(exc) or cls._is_model_switchable_error(exc)

    @staticmethod
    def _is_hard_quota_error(exc: Exception) -> bool:
        return is_gemini_hard_quota_error(exc)

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
