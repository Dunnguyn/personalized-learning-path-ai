"""Cloud-only LLM client for curriculum generation."""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import time
from copy import deepcopy
from threading import Event, Lock
from typing import Any, Dict

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

CURRICULUM_PROVIDER = os.getenv("LEARNING_PATH_LLM_PROVIDER", "gemini").lower()
CURRICULUM_MODEL = os.getenv(
    "LEARNING_PATH_LLM_MODEL",
    os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
)
CURRICULUM_FALLBACK_MODELS = os.getenv("LEARNING_PATH_LLM_FALLBACK_MODELS")
CURRICULUM_MAX_RETRIES = int(os.getenv("LEARNING_PATH_LLM_MAX_RETRIES", "1"))
CURRICULUM_QUOTA_COOLDOWN_SECONDS = int(
    os.getenv("LEARNING_PATH_LLM_QUOTA_COOLDOWN_SECONDS", "300")
)
CURRICULUM_MODEL_FAILOVER_COOLDOWN_SECONDS = float(
    os.getenv("LEARNING_PATH_LLM_MODEL_FAILOVER_COOLDOWN_SECONDS", "20")
)
CURRICULUM_RETRY_BASE_DELAY_SECONDS = float(
    os.getenv("LEARNING_PATH_LLM_RETRY_BASE_DELAY_SECONDS", "1.0")
)
CURRICULUM_RETRY_MAX_DELAY_SECONDS = float(
    os.getenv("LEARNING_PATH_LLM_RETRY_MAX_DELAY_SECONDS", "8.0")
)
CURRICULUM_RETRY_JITTER_SECONDS = float(
    os.getenv("LEARNING_PATH_LLM_RETRY_JITTER_SECONDS", "0.5")
)
CURRICULUM_RETRY_HINT_MAX_SECONDS = float(
    os.getenv("LEARNING_PATH_LLM_RETRY_HINT_MAX_SECONDS", "45")
)
CURRICULUM_REPAIR_MAX_OUTPUT_TOKENS = int(
    os.getenv("LEARNING_PATH_LLM_REPAIR_MAX_OUTPUT_TOKENS", "2200")
)
CURRICULUM_REPAIR_INPUT_MAX_CHARS = int(
    os.getenv("LEARNING_PATH_LLM_REPAIR_INPUT_MAX_CHARS", "2600")
)


class CurriculumLLMClient:
    """Thin provider client used only for curriculum generation."""

    def __init__(self) -> None:
        self.provider = CURRICULUM_PROVIDER
        self.model = CURRICULUM_MODEL
        self.model_candidates = self._build_model_candidates()
        self.cooldown_until_ts: float = 0.0
        self.last_error: str | None = None
        self.client = self._init_client()
        self._model_cooldowns: dict[str, float] = {}
        self._last_used_model: str | None = None
        self._inflight_lock = Lock()
        self._inflight_generations: dict[str, dict[str, object]] = {}

    def is_available(self) -> bool:
        return self.client is not None

    def status(self) -> Dict[str, object]:
        now = time.time()
        active_model = self._select_available_model(now=now)
        display_model = active_model or self._last_used_model or self.model
        cooldown_remaining = (
            0.0 if active_model else self._minimum_model_wait_seconds(now=now)
        )
        scope_status = self._get_model_scope_status(display_model, now=now)
        return {
            "provider": self.provider,
            "enabled": self.is_available(),
            "cooldown_active": cooldown_remaining > 0,
            "cooldown_remaining_seconds": int(cooldown_remaining),
            "reason": (
                "quota_cooldown"
                if cooldown_remaining > 0
                else None if self.is_available() else "provider_unavailable"
            ),
            "model": display_model,
            "configured_model": self.model,
            "fallback_models": list(self.model_candidates[1:]),
            "last_error": self.last_error,
            "api_key_configured": (
                configured_gemini_api_key_count() > 0
                if self.provider == "gemini"
                else False
            ),
            "scope_cooldown_active": bool(scope_status.get("cooldown_active")),
            "scope_cooldown_remaining_seconds": int(
                scope_status.get("retry_after_seconds", 0) or 0
            ),
            "available_key_count": int(scope_status.get("available_key_count", 0) or 0),
            "total_key_count": int(scope_status.get("total_key_count", 0) or 0),
        }

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: int = 3200,
        temperature: float = 0.1,
    ) -> str:
        """Generate curriculum JSON text with model failover and retry logic."""
        return self._run_with_model_failover(
            operation="generate",
            request_key=self._build_request_key(
                operation="generate",
                prompt=prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            ),
            request_builder=lambda model_name: {
                "model": model_name,
                "contents": prompt,
                "config": {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "response_mime_type": "application/json",
                },
            },
        )

    def repair_json(self, partial_json: str) -> str:
        """Repair or complete partial curriculum JSON returned by the model."""
        snippet = str(partial_json or "").strip()
        if not snippet:
            return ""
        snippet = snippet[:CURRICULUM_REPAIR_INPUT_MAX_CHARS]
        return self._run_with_model_failover(
            operation="repair_json",
            request_key=self._build_request_key(
                operation="repair_json",
                prompt=snippet,
                max_output_tokens=CURRICULUM_REPAIR_MAX_OUTPUT_TOKENS,
                temperature=0.0,
            ),
            request_builder=lambda model_name: {
                "model": model_name,
                "contents": (
                    "Repair the curriculum JSON below.\n"
                    "Return valid JSON only.\n"
                    'Use top-level key "chapters".\n'
                    "Keep the structure compact.\n"
                    "Preserve the original meaning when possible.\n"
                    "Each chapter needs title and lessons.\n"
                    "Each lesson needs title, summary, objectives, prerequisites, "
                    "target_concepts, prerequisite_concepts, difficulty, lesson_kind.\n"
                    "If a field is missing, fill it with a short sensible value.\n\n"
                    f"Partial JSON:\n{snippet}"
                ),
                "config": {
                    "temperature": 0.0,
                    "max_output_tokens": CURRICULUM_REPAIR_MAX_OUTPUT_TOKENS,
                    "response_mime_type": "application/json",
                },
            },
        )

    def _run_with_model_failover(
        self,
        *,
        operation: str,
        request_key: str,
        request_builder: Any,
    ) -> str:
        if not self.client:
            return ""
        cooldown_seconds = self._current_cooldown_seconds()
        if cooldown_seconds > 0:
            wait_seconds = max(1, int(cooldown_seconds))
            self.last_error = (
                f"Curriculum LLM cooldown active after quota exhaustion. Retry in {wait_seconds}s."
            )
            return ""

        state, is_owner = self._acquire_generation_slot(request_key)
        if not is_owner:
            logger.info("curriculum_llm_join_inflight | key=%s", request_key[:12])
            state["event"].wait()
            error = state.get("error")
            if error is not None:
                raise error
            return str(state.get("result") or "")

        try:
            result = ""
            last_retryable_error: Exception | None = None
            for attempt in range(1, CURRICULUM_MAX_RETRIES + 1):
                candidate_models = self._available_model_candidates()
                if not candidate_models:
                    wait_seconds = self._minimum_model_wait_seconds()
                    self.last_error = (
                        "Curriculum LLM model cooldown active after quota exhaustion. "
                        f"Retry in {wait_seconds}s."
                    )
                    break

                last_retryable_error = None
                should_stop = False
                for model_name in candidate_models:
                    try:
                        params = request_builder(model_name)
                        self._last_used_model = model_name
                        response = self.client.models.generate_content(
                            model=params["model"],
                            contents=params["contents"],
                            config=params["config"],
                        )
                        text = getattr(response, "text", None)
                        if text:
                            self.model = model_name
                            self.last_error = None
                            result = str(text).strip()
                            break
                        self.last_error = "Curriculum LLM returned an empty response."
                        should_stop = True
                        break
                    except Exception as exc:  # pragma: no cover - external dependency
                        self.last_error = str(exc)
                        logger.warning(
                            "Curriculum LLM %s failed on attempt %s/%s with model %s: %s",
                            operation,
                            attempt,
                            CURRICULUM_MAX_RETRIES,
                            model_name,
                            exc,
                        )
                        if self._should_fail_over_model(exc):
                            cooldown = self._compute_model_cooldown_seconds(exc)
                            self._model_cooldowns[model_name] = time.time() + cooldown
                            self.cooldown_until_ts = self._minimum_global_cooldown_until()
                            logger.info(
                                "Curriculum LLM model cooldown set to %.1fs for %s after %s failure.",
                                cooldown,
                                model_name,
                                operation,
                            )
                            if self._is_retryable_error(exc):
                                last_retryable_error = exc
                            continue
                        should_stop = True
                        break

                if result or should_stop:
                    break

                if attempt < CURRICULUM_MAX_RETRIES and last_retryable_error is not None:
                    delay = self._compute_retry_delay_seconds(attempt, last_retryable_error)
                    logger.info(
                        "Curriculum LLM retrying %s in %.2fs (attempt %s/%s).",
                        operation,
                        delay,
                        attempt + 1,
                        CURRICULUM_MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                break

            state["result"] = deepcopy(result)
            return result
        except Exception as exc:
            state["error"] = exc
            raise
        finally:
            state["event"].set()
            with self._inflight_lock:
                self._inflight_generations.pop(request_key, None)

    def _build_model_candidates(self) -> list[str]:
        return build_gemini_model_candidates(
            self.model,
            CURRICULUM_FALLBACK_MODELS,
        ) or [self.model]

    def _available_model_candidates(self, *, now: float | None = None) -> list[str]:
        current_time = now if now is not None else time.time()
        return [
            model_name
            for model_name in self.model_candidates
            if self._model_wait_seconds(model_name, now=current_time) <= 0
        ]

    def _select_available_model(self, *, now: float | None = None) -> str | None:
        candidates = self._available_model_candidates(now=now)
        return candidates[0] if candidates else None

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
        self,
        model_name: str,
        *,
        now: float | None = None,
    ) -> float:
        current_time = now if now is not None else time.time()
        local_wait = max(0.0, self._model_cooldowns.get(model_name, 0.0) - current_time)
        scope_status = self._get_model_scope_status(model_name, now=current_time)
        scope_wait = float(scope_status.get("retry_after_seconds", 0.0) or 0.0)
        return max(local_wait, scope_wait)

    def _get_model_scope_status(
        self, model_name: str | None, *, now: float | None = None
    ) -> Dict[str, object]:
        if self.provider != "gemini" or not model_name:
            return {}
        status = get_gemini_model_scope_status(model_name)
        if now is None:
            return status
        retry_after = max(0.0, float(status.get("retry_after_seconds", 0.0) or 0.0))
        status["cooldown_active"] = bool(status.get("cooldown_active")) or retry_after > 0
        status["scope_cooldown_active"] = max(
            0.0,
            float(status.get("scope_cooldown_remaining_seconds", 0.0) or 0.0),
        ) > 0
        return status

    def _current_cooldown_seconds(self) -> float:
        if self._select_available_model() is not None:
            return 0.0
        return float(self._minimum_model_wait_seconds())

    def _acquire_generation_slot(
        self, generation_key: str
    ) -> tuple[dict[str, object], bool]:
        with self._inflight_lock:
            current = self._inflight_generations.get(generation_key)
            if current is not None:
                return current, False
            created: dict[str, object] = {
                "event": Event(),
                "result": None,
                "error": None,
            }
            self._inflight_generations[generation_key] = created
            return created, True

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        return is_gemini_transient_unavailable_error(exc) or is_gemini_capacity_exhausted_error(exc)

    @staticmethod
    def _should_fail_over_model(exc: Exception) -> bool:
        return is_gemini_failover_error(exc)

    @staticmethod
    def _compute_model_cooldown_seconds(exc: Exception) -> float:
        retry_after = CurriculumLLMClient._extract_retry_delay_seconds(exc) or 0.0
        if is_gemini_invalid_key_error(exc):
            return max(CURRICULUM_QUOTA_COOLDOWN_SECONDS, retry_after)
        if is_gemini_hard_quota_error(exc):
            return max(CURRICULUM_QUOTA_COOLDOWN_SECONDS, retry_after)
        if CurriculumLLMClient._is_retryable_error(exc):
            return max(CURRICULUM_MODEL_FAILOVER_COOLDOWN_SECONDS, retry_after)
        return max(1.0, CURRICULUM_MODEL_FAILOVER_COOLDOWN_SECONDS)

    @staticmethod
    def _extract_retry_delay_seconds(exc: Exception) -> float | None:
        message = str(exc)
        match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", message, re.IGNORECASE)
        if not match:
            match = re.search(r"retryDelay': '([0-9]+(?:\.[0-9]+)?)s'", message)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _compute_retry_delay_seconds(attempt: int, exc: Exception | None = None) -> float:
        retry_after = CurriculumLLMClient._extract_retry_delay_seconds(exc) if exc else None
        if retry_after is not None and retry_after > 0:
            jitter = random.uniform(0.0, max(0.0, CURRICULUM_RETRY_JITTER_SECONDS))
            return min(CURRICULUM_RETRY_HINT_MAX_SECONDS, retry_after + jitter)
        capped_attempt = max(1, attempt)
        base = CURRICULUM_RETRY_BASE_DELAY_SECONDS * (2 ** (capped_attempt - 1))
        jitter = random.uniform(0.0, max(0.0, CURRICULUM_RETRY_JITTER_SECONDS))
        return min(CURRICULUM_RETRY_MAX_DELAY_SECONDS, base + jitter)

    def _init_client(self):
        if self.provider == "gemini":
            try:
                return get_gemini_client()
            except Exception as exc:  # pragma: no cover - external dependency
                logger.warning("Could not initialize curriculum Gemini client: %s", exc)
                return None

        logger.warning("Unsupported curriculum provider: %s", self.provider)
        return None

    def _build_request_key(
        self,
        *,
        operation: str,
        prompt: str,
        max_output_tokens: int,
        temperature: float,
    ) -> str:
        raw = "||".join(
            [
                operation,
                self.provider,
                ",".join(self.model_candidates),
                str(max_output_tokens),
                str(temperature),
                hashlib.sha1(str(prompt or "").encode("utf-8")).hexdigest(),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
