"""Cloud-only LLM client for curriculum generation."""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict

from backend.app.utils.gemini import get_gemini_client

logger = logging.getLogger(__name__)

CURRICULUM_PROVIDER = os.getenv("LEARNING_PATH_LLM_PROVIDER", "gemini").lower()
CURRICULUM_MODEL = os.getenv(
    "LEARNING_PATH_LLM_MODEL",
    os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
)
CURRICULUM_MAX_RETRIES = int(os.getenv("LEARNING_PATH_LLM_MAX_RETRIES", "1"))
CURRICULUM_QUOTA_COOLDOWN_SECONDS = int(
    os.getenv("LEARNING_PATH_LLM_QUOTA_COOLDOWN_SECONDS", "300")
)
CURRICULUM_REPAIR_MAX_OUTPUT_TOKENS = int(
    os.getenv("LEARNING_PATH_LLM_REPAIR_MAX_OUTPUT_TOKENS", "2200")
)


class CurriculumLLMClient:
    """Thin provider client used only for curriculum generation."""

    def __init__(self) -> None:
        self.provider = CURRICULUM_PROVIDER
        self.model = CURRICULUM_MODEL
        self.cooldown_until_ts: float = 0.0
        self.last_error: str | None = None
        self.client = self._init_client()

    def is_available(self) -> bool:
        return self.client is not None

    def status(self) -> Dict[str, object]:
        cooldown_remaining = max(0.0, self.cooldown_until_ts - time.time())
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
            "model": self.model,
            "last_error": self.last_error,
        }

    def generate(
        self,
        prompt: str,
        *,
        max_output_tokens: int = 3200,
        temperature: float = 0.1,
    ) -> str:
        """Generate curriculum JSON text with simple retry logic."""
        if not self.client:
            return ""
        if time.time() < self.cooldown_until_ts:
            wait_seconds = max(1, int(self.cooldown_until_ts - time.time()))
            self.last_error = (
                f"Curriculum LLM cooldown active after quota exhaustion. Retry in {wait_seconds}s."
            )
            return ""

        for attempt in range(1, CURRICULUM_MAX_RETRIES + 1):
            try:
                if self.provider == "gemini":
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config={
                            "temperature": temperature,
                            "max_output_tokens": max_output_tokens,
                            "response_mime_type": "application/json",
                        },
                    )
                    text = getattr(response, "text", None)
                    if text:
                        self.last_error = None
                        return str(text).strip()
                return ""
            except Exception as exc:  # pragma: no cover - external dependency
                self.last_error = str(exc)
                logger.warning(
                    "Curriculum LLM request failed on attempt %s/%s: %s",
                    attempt,
                    CURRICULUM_MAX_RETRIES,
                    exc,
                )
                cooldown = self._extract_quota_cooldown_seconds(exc)
                if cooldown is not None:
                    self.cooldown_until_ts = time.time() + max(
                        CURRICULUM_QUOTA_COOLDOWN_SECONDS,
                        cooldown,
                    )
                    logger.warning(
                        "Curriculum LLM quota exhausted; cooldown active for %ss",
                        max(CURRICULUM_QUOTA_COOLDOWN_SECONDS, cooldown),
                    )
                    break
                time.sleep(min(attempt, 3))
        return ""

    def repair_json(self, partial_json: str) -> str:
        """Repair or complete partial curriculum JSON returned by the model."""
        if not self.client:
            return ""
        snippet = str(partial_json or "").strip()
        if not snippet:
            return ""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=(
                    "You repair incomplete JSON for a curriculum planner.\n"
                    "Complete and fix the partial JSON below.\n"
                    "Return valid JSON only.\n"
                    "Requirements:\n"
                    '- Use top-level key "chapters".\n'
                    "- Keep the structure compact.\n"
                    "- Preserve the existing meaning when possible.\n"
                    "- If a field is missing, fill it with a short sensible value.\n"
                    "- Each chapter must have a title and lessons.\n"
                    "- Each lesson must include title, summary, objectives, prerequisites, "
                    "target_concepts, prerequisite_concepts, difficulty, and lesson_kind.\n\n"
                    f"Partial JSON:\n{snippet}"
                ),
                config={
                    "temperature": 0.0,
                    "max_output_tokens": CURRICULUM_REPAIR_MAX_OUTPUT_TOKENS,
                    "response_mime_type": "application/json",
                },
            )
            text = getattr(response, "text", None)
            return str(text).strip() if text else ""
        except Exception as exc:  # pragma: no cover - external dependency
            self.last_error = str(exc)
            logger.warning("Curriculum JSON repair failed: %s", exc)
            cooldown = self._extract_quota_cooldown_seconds(exc)
            if cooldown is not None:
                self.cooldown_until_ts = time.time() + max(
                    CURRICULUM_QUOTA_COOLDOWN_SECONDS,
                    cooldown,
                )
            return ""

    @staticmethod
    def _extract_quota_cooldown_seconds(exc: Exception) -> int | None:
        message = str(exc)
        if "RESOURCE_EXHAUSTED" not in message and "Quota exceeded" not in message and "429" not in message:
            return None
        match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", message, re.IGNORECASE)
        if not match:
            match = re.search(r"retryDelay': '([0-9]+)s'", message)
        if match:
            return int(float(match.group(1)))
        return CURRICULUM_QUOTA_COOLDOWN_SECONDS

    def _init_client(self):
        if self.provider == "gemini":
            try:
                return get_gemini_client()
            except Exception as exc:  # pragma: no cover - external dependency
                logger.warning("Could not initialize curriculum Gemini client: %s", exc)
                return None

        logger.warning("Unsupported curriculum provider: %s", self.provider)
        return None
