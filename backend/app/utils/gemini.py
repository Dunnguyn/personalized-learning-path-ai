"""Gemini client utilities with API key rotation support."""

from __future__ import annotations

import logging
import os
import re
import time
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

GEMINI_API_KEY_COOLDOWN_SECONDS = float(
    os.getenv("GEMINI_API_KEY_COOLDOWN_SECONDS", "300")
)
GEMINI_API_KEY_RETRY_DELAY_SECONDS = float(
    os.getenv("GEMINI_API_KEY_RETRY_DELAY_SECONDS", "0.5")
)
GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS = float(
    os.getenv("GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS", "15")
)
GEMINI_INVALID_KEY_COOLDOWN_SECONDS = float(
    os.getenv("GEMINI_INVALID_KEY_COOLDOWN_SECONDS", "1800")
)
GEMINI_MAX_CONCURRENT_REQUESTS = max(
    0,
    int(os.getenv("GEMINI_MAX_CONCURRENT_REQUESTS", "3")),
)
GEMINI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS = max(
    0.0,
    float(os.getenv("GEMINI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", "20")),
)
GEMINI_CONCURRENCY_WAIT_LOG_THRESHOLD_SECONDS = max(
    0.0,
    float(os.getenv("GEMINI_CONCURRENCY_WAIT_LOG_THRESHOLD_SECONDS", "0.25")),
)
GEMINI_TRANSIENT_UNAVAILABLE_MAX_KEY_ATTEMPTS = max(
    1,
    int(os.getenv("GEMINI_TRANSIENT_UNAVAILABLE_MAX_KEY_ATTEMPTS", "2")),
)
GEMINI_SCOPE_COOLDOWN_SECONDS = max(
    0.0,
    float(
        os.getenv(
            "GEMINI_SCOPE_COOLDOWN_SECONDS",
            str(GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS),
        )
    ),
)

_KEY_ERROR_MARKERS = (
    "resource_exhausted",
    "quota exceeded",
    "rate limit",
    "429",
    "503",
    "unavailable",
    "deadline exceeded",
    "timeout",
    "temporar",
    "api key",
    "invalid api key",
    "permission denied",
    "401",
    "403",
)
_HARD_QUOTA_MARKERS = (
    "generaterequestsperday",
    "free_tier_requests",
    "perdayperproject",
)
_T = TypeVar("_T")


def _split_api_keys(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r"[\r\n,;]+", raw or "") if item.strip()]


def get_configured_gemini_api_keys() -> list[str]:
    """Return configured Gemini API keys in stable priority order."""
    candidates: list[str] = []

    primary_key = str(os.getenv("GEMINI_API_KEY") or "").strip()
    if primary_key:
        candidates.append(primary_key)

    candidates.extend(_split_api_keys(os.getenv("GEMINI_API_KEYS", "")))

    indexed_keys = sorted(
        (
            (name, str(value).strip())
            for name, value in os.environ.items()
            if re.fullmatch(r"GEMINI_API_KEY_\d+", name) and str(value).strip()
        ),
        key=lambda item: int(item[0].rsplit("_", 1)[1]),
    )
    candidates.extend(value for _, value in indexed_keys)

    seen: set[str] = set()
    ordered: list[str] = []
    for key in candidates:
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def has_configured_gemini_api_keys() -> bool:
    return bool(get_configured_gemini_api_keys())


def configured_gemini_api_key_count() -> int:
    return len(get_configured_gemini_api_keys())


def _normalize_model_candidates(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in re.split(r"[\r\n,;]+", raw) if item.strip()]
    ordered: list[str] = []
    for item in raw:
        model_name = str(item or "").strip()
        if model_name:
            ordered.append(model_name)
    return ordered


def default_gemini_fallback_models() -> list[str]:
    return _normalize_model_candidates(
        os.getenv(
            "GEMINI_MODEL_FALLBACKS",
            "models/gemini-2.0-flash-lite,models/gemini-2.0-flash",
        )
    )


def build_gemini_model_candidates(
    primary_model: str | None,
    fallback_models: str | list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    extras = (
        _normalize_model_candidates(fallback_models)
        if fallback_models is not None
        else default_gemini_fallback_models()
    )
    for model_name in [str(primary_model or "").strip(), *extras]:
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        ordered.append(model_name)
    return ordered


def get_gemini_scope_status(scope: str) -> dict[str, Any]:
    return get_gemini_client_manager().get_scope_status(scope=scope)


def get_gemini_model_scope_status(model_name: str | None) -> dict[str, Any]:
    normalized = str(model_name or "").strip()
    if not normalized:
        return {}
    return get_gemini_scope_status(f"generate_content:{normalized}")


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


def is_gemini_failover_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _KEY_ERROR_MARKERS)


def is_gemini_hard_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _HARD_QUOTA_MARKERS)


def is_gemini_transient_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "503" in message
        or "unavailable" in message
        or "temporar" in message
        or "deadline exceeded" in message
        or "timeout" in message
    )


def is_gemini_capacity_exhausted_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "resource_exhausted" in message
        or "resource exhausted" in message
        or "rate limit" in message
        or "429" in message
    )


def is_gemini_invalid_key_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "invalid api key" in message
        or "api key not valid" in message
        or "permission denied" in message
        or "unauthenticated" in message
        or "401" in message
        or "403" in message
    )


def is_gemini_scope_wide_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return is_gemini_hard_quota_error(exc) or (
        is_gemini_capacity_exhausted_error(exc)
        and (
            "permodel" in message
            or "perproject" in message
            or "quota exceeded for metric" in message
            or "quotaid" in message
            or "quotafailure" in message
            or "limit: 0, model:" in message
        )
    )


def is_gemini_scope_wide_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return is_gemini_transient_unavailable_error(exc) and (
        "currently experiencing high demand" in message
        or "spikes in demand" in message
        or "status': 'unavailable'" in message
        or '"status": "unavailable"' in message
    )


class _RotatingGeminiModels:
    def __init__(self, manager: "GeminiClientManager") -> None:
        self._manager = manager

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        return self._manager.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    def embed_content(self, *, model: str, contents: Any) -> Any:
        return self._manager.embed_content(model=model, contents=contents)


class RotatingGeminiClient:
    """Drop-in Gemini client wrapper that retries with the next API key."""

    def __init__(self, manager: "GeminiClientManager") -> None:
        self._manager = manager
        self.models = _RotatingGeminiModels(manager)

    def configured_key_count(self) -> int:
        return self._manager.configured_key_count()


class GeminiClientManager:
    def __init__(self) -> None:
        self._lock = Lock()
        self._clients: dict[str, Any] = {}
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._scope_cooldowns: dict[str, float] = {}
        self._active_index = 0
        self._scope_active_indexes: dict[str, int] = {}
        self._concurrency_limit = GEMINI_MAX_CONCURRENT_REQUESTS
        self._concurrency_semaphore = (
            BoundedSemaphore(self._concurrency_limit)
            if self._concurrency_limit > 0
            else None
        )
        self._active_requests = 0

    def configured_keys(self) -> list[str]:
        return get_configured_gemini_api_keys()

    def configured_key_count(self) -> int:
        return len(self.configured_keys())

    def is_configured(self) -> bool:
        return self.configured_key_count() > 0

    def _ordered_candidate_indexes(self) -> list[int]:
        keys = self.configured_keys()
        if not keys:
            return []
        with self._lock:
            start_index = self._active_index % len(keys)
        return [(start_index + offset) % len(keys) for offset in range(len(keys))]

    def _ordered_candidate_indexes_for_scope(self, *, scope: str) -> list[int]:
        keys = self.configured_keys()
        if not keys:
            return []
        with self._lock:
            scope_start = self._scope_active_indexes.get(scope)
            start_index = (
                scope_start % len(keys)
                if scope_start is not None
                else self._active_index % len(keys)
            )
        return [(start_index + offset) % len(keys) for offset in range(len(keys))]

    def _available_candidate_indexes(self, *, scope: str) -> list[int]:
        keys = self.configured_keys()
        ordered_indexes = self._ordered_candidate_indexes_for_scope(scope=scope)
        if not ordered_indexes:
            return []
        now = time.time()
        if self._scope_cooldowns.get(scope, 0.0) > now:
            return []
        available = [
            index
            for index in ordered_indexes
            if self._cooldowns.get((keys[index], scope), 0.0) <= now
        ]
        return available

    def get_scope_status(self, *, scope: str) -> dict[str, Any]:
        keys = self.configured_keys()
        now = time.time()
        with self._lock:
            scope_cooldown_until = self._scope_cooldowns.get(scope, 0.0)
            key_cooldowns = [
                self._cooldowns.get((key, scope), 0.0) for key in keys
            ]
            active_requests = self._active_requests
            concurrency_limit = self._concurrency_limit

        scope_wait_seconds = max(0.0, scope_cooldown_until - now)
        key_waits = [max(0.0, ts - now) for ts in key_cooldowns if ts > now]
        available_key_count = sum(1 for ts in key_cooldowns if ts <= now)
        cooldown_active = scope_wait_seconds > 0 or (
            bool(keys) and available_key_count == 0
        )
        retry_after_seconds = 0.0
        if scope_wait_seconds > 0:
            retry_after_seconds = scope_wait_seconds
        elif key_waits:
            retry_after_seconds = min(key_waits)

        return {
            "scope": scope,
            "cooldown_active": cooldown_active,
            "scope_cooldown_active": scope_wait_seconds > 0,
            "scope_cooldown_remaining_seconds": scope_wait_seconds,
            "retry_after_seconds": retry_after_seconds,
            "available_key_count": 0 if scope_wait_seconds > 0 else available_key_count,
            "total_key_count": len(keys),
            "active_requests": active_requests,
            "concurrency_limit": concurrency_limit,
        }

    def _client_for_key(self, key: str):
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None:
                return cached
        from google import genai

        client = genai.Client(api_key=key)
        with self._lock:
            self._clients[key] = client
        return client

    def _mark_success(self, *, index: int, key: str, key_count: int, scope: str) -> None:
        with self._lock:
            self._cooldowns.pop((key, scope), None)
            self._scope_cooldowns.pop(scope, None)
            next_index = (index + 1) % max(1, key_count)
            self._active_index = next_index
            self._scope_active_indexes[scope] = next_index

    def _mark_failure(
        self,
        *,
        index: int,
        key: str,
        exc: Exception,
        key_count: int,
        scope: str,
    ) -> None:
        retry_delay = _extract_retry_delay_seconds(exc) or 0.0
        cooldown_seconds = 0.0
        if is_gemini_invalid_key_error(exc):
            cooldown_seconds = max(GEMINI_INVALID_KEY_COOLDOWN_SECONDS, retry_delay)
        elif is_gemini_hard_quota_error(exc):
            cooldown_seconds = max(GEMINI_API_KEY_COOLDOWN_SECONDS, retry_delay)
        elif retry_delay > 0:
            cooldown_seconds = retry_delay
        elif is_gemini_transient_unavailable_error(exc):
            cooldown_seconds = GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS
        elif is_gemini_capacity_exhausted_error(exc):
            cooldown_seconds = GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS

        with self._lock:
            if cooldown_seconds > 0:
                self._cooldowns[(key, scope)] = time.time() + cooldown_seconds
            next_index = (index + 1) % max(1, key_count)
            self._active_index = next_index
            self._scope_active_indexes[scope] = next_index

    def _mark_scope_cooldown(self, *, scope: str, cooldown_seconds: float) -> None:
        if cooldown_seconds <= 0:
            return
        with self._lock:
            self._scope_cooldowns[scope] = time.time() + cooldown_seconds

    def _scope_cooldown_seconds_for_error(self, exc: Exception) -> float:
        retry_after = _extract_retry_delay_seconds(exc) or 0.0
        if is_gemini_scope_wide_quota_error(exc):
            return max(GEMINI_API_KEY_COOLDOWN_SECONDS, retry_after)
        if is_gemini_scope_wide_unavailable_error(exc):
            return max(GEMINI_SCOPE_COOLDOWN_SECONDS, retry_after)
        if is_gemini_transient_unavailable_error(exc) or is_gemini_capacity_exhausted_error(exc):
            return max(GEMINI_SCOPE_COOLDOWN_SECONDS, retry_after)
        return max(retry_after, GEMINI_SCOPE_COOLDOWN_SECONDS)

    def _acquire_concurrency_slot(self, *, operation_name: str, scope: str) -> None:
        semaphore = self._concurrency_semaphore
        if semaphore is None:
            return
        started_waiting_at = time.perf_counter()
        acquired = semaphore.acquire(
            timeout=GEMINI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS
            if GEMINI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS > 0
            else None
        )
        waited_seconds = time.perf_counter() - started_waiting_at
        if not acquired:
            raise RuntimeError(
                "Gemini concurrency limit is saturated. "
                "Retry after in-flight requests finish."
            )
        with self._lock:
            self._active_requests += 1
            active_requests = self._active_requests
        if waited_seconds >= GEMINI_CONCURRENCY_WAIT_LOG_THRESHOLD_SECONDS:
            logger.info(
                "Gemini %s waited %.2fs for concurrency slot | scope=%s | active=%s | limit=%s",
                operation_name,
                waited_seconds,
                scope,
                active_requests,
                self._concurrency_limit,
            )

    def _release_concurrency_slot(self) -> None:
        semaphore = self._concurrency_semaphore
        if semaphore is None:
            return
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
        semaphore.release()

    def _run_with_failover(
        self,
        *,
        operation_name: str,
        scope: str,
        request: Callable[[Any], _T],
    ) -> _T:
        keys = self.configured_keys()
        if not keys:
            raise RuntimeError(
                "No Gemini API keys configured. Set GEMINI_API_KEY, GEMINI_API_KEYS, "
                "or GEMINI_API_KEY_1..N."
            )

        last_error: Exception | None = None
        candidate_indexes = self._available_candidate_indexes(scope=scope)
        if not candidate_indexes:
            raise RuntimeError(
                "All configured Gemini API keys are temporarily cooling down after recent failures for this Gemini operation."
            )
        self._acquire_concurrency_slot(operation_name=operation_name, scope=scope)
        try:
            for attempt, index in enumerate(candidate_indexes, start=1):
                key = keys[index]
                try:
                    result = request(self._client_for_key(key))
                    self._mark_success(
                        index=index,
                        key=key,
                        key_count=len(keys),
                        scope=scope,
                    )
                    return result
                except Exception as exc:  # pragma: no cover - external dependency
                    last_error = exc
                    self._mark_failure(
                        index=index,
                        key=key,
                        exc=exc,
                        key_count=len(keys),
                        scope=scope,
                    )
                    logger.warning(
                        "Gemini %s failed with API key %s/%s: %s",
                        operation_name,
                        attempt,
                        len(candidate_indexes),
                        exc,
                    )
                    if not is_gemini_failover_error(exc):
                        raise
                    if (
                        (
                            is_gemini_scope_wide_quota_error(exc)
                            or is_gemini_scope_wide_unavailable_error(exc)
                        )
                        and attempt >= len(candidate_indexes)
                    ):
                        cooldown_seconds = self._scope_cooldown_seconds_for_error(exc)
                        self._mark_scope_cooldown(
                            scope=scope,
                            cooldown_seconds=cooldown_seconds,
                        )
                        logger.info(
                            "Gemini %s exhausted all %s keys for scope-wide failure | scope=%s | cooldown=%.1fs",
                            operation_name,
                            len(candidate_indexes),
                            scope,
                            cooldown_seconds,
                        )
                        break
                    if (
                        (
                            is_gemini_transient_unavailable_error(exc)
                            or is_gemini_capacity_exhausted_error(exc)
                        )
                        and attempt >= GEMINI_TRANSIENT_UNAVAILABLE_MAX_KEY_ATTEMPTS
                        and attempt >= len(candidate_indexes)
                    ):
                        cooldown_seconds = self._scope_cooldown_seconds_for_error(exc)
                        self._mark_scope_cooldown(
                            scope=scope,
                            cooldown_seconds=cooldown_seconds,
                        )
                        logger.info(
                            "Gemini %s stopping early after %s scope-wide failures | scope=%s | cooldown=%.1fs",
                            operation_name,
                            attempt,
                            scope,
                            cooldown_seconds,
                        )
                        break
                    if (
                        attempt < len(candidate_indexes)
                        and GEMINI_API_KEY_RETRY_DELAY_SECONDS > 0
                    ):
                        time.sleep(GEMINI_API_KEY_RETRY_DELAY_SECONDS)
        finally:
            self._release_concurrency_slot()

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Gemini {operation_name} failed before any client was tried.")

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        return self._run_with_failover(
            operation_name="generate_content",
            scope=f"generate_content:{model}",
            request=lambda client: client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            ),
        )

    def embed_content(self, *, model: str, contents: Any) -> Any:
        return self._run_with_failover(
            operation_name="embed_content",
            scope=f"embed_content:{model}",
            request=lambda client: client.models.embed_content(
                model=model,
                contents=contents,
            ),
        )

    def get_client(self) -> RotatingGeminiClient | None:
        if not self.is_configured():
            return None
        return RotatingGeminiClient(self)


_gemini_client_manager = GeminiClientManager()


def get_gemini_client_manager() -> GeminiClientManager:
    return _gemini_client_manager


def get_gemini_client() -> RotatingGeminiClient | None:
    return _gemini_client_manager.get_client()
