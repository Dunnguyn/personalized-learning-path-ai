"""Gemini client utilities with API key rotation support."""

from __future__ import annotations

import logging
import os
import re
import time
from threading import Lock
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
        self._active_index = 0

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

    def _available_candidate_indexes(self, *, scope: str) -> list[int]:
        keys = self.configured_keys()
        ordered_indexes = self._ordered_candidate_indexes()
        if not ordered_indexes:
            return []
        now = time.time()
        available = [
            index
            for index in ordered_indexes
            if self._cooldowns.get((keys[index], scope), 0.0) <= now
        ]
        return available

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
            self._active_index = index % max(1, key_count)

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
        if is_gemini_hard_quota_error(exc):
            cooldown_seconds = max(GEMINI_API_KEY_COOLDOWN_SECONDS, retry_delay)
        elif retry_delay > 0:
            cooldown_seconds = retry_delay
        elif is_gemini_transient_unavailable_error(exc):
            cooldown_seconds = GEMINI_API_KEY_TRANSIENT_COOLDOWN_SECONDS

        with self._lock:
            if cooldown_seconds > 0:
                self._cooldowns[(key, scope)] = time.time() + cooldown_seconds
            self._active_index = (index + 1) % max(1, key_count)

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
                if attempt < len(candidate_indexes) and GEMINI_API_KEY_RETRY_DELAY_SECONDS > 0:
                    time.sleep(GEMINI_API_KEY_RETRY_DELAY_SECONDS)

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
