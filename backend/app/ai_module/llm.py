"""LLM utilities for non-authoritative YouTube summaries."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from backend.app.utils.gemini import get_gemini_client

logger = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
SUMMARY_MAX_RETRIES = int(os.getenv("YOUTUBE_SUMMARY_MAX_RETRIES", "3"))


class YouTubeSummaryService:
    """Generate clearly-labeled AI summaries when transcripts are unavailable."""

    def __init__(self) -> None:
        self.client = None
        try:
            self.client = get_gemini_client()
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("Gemini summary client unavailable: %s", exc)

    def generate_summary(
        self,
        *,
        video_title: str,
        topic: str,
        level: str,
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return an explicitly AI-generated learning summary."""
        prompt = (
            "Create a study summary for a YouTube video without transcript.\n"
            "Important: this summary is AI-generated guidance, not ground truth.\n"
            f"Topic: {topic}\n"
            f"Level: {level}\n"
            f"Title: {video_title}\n"
            f"Additional context: {additional_context or 'N/A'}\n"
            "Produce a concise, structured summary for study notes."
        )

        generated_text = self._call_with_retry(prompt)
        if not generated_text:
            generated_text = self._fallback_template(
                video_title=video_title, topic=topic, level=level
            )

        return {
            "content": generated_text,
            "is_ai_generated": True,
            "model": GEMINI_MODEL if self.client else "template-fallback",
        }

    def _call_with_retry(self, prompt: str) -> Optional[str]:
        if not self.client:
            return None
        for attempt in range(1, SUMMARY_MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config={"temperature": 0.4, "max_output_tokens": 1200},
                )
                text = (getattr(response, "text", None) or "").strip()
                if text:
                    return text
            except Exception as exc:  # pragma: no cover - optional dependency
                logger.warning(
                    "Summary generation failed on attempt %s: %s", attempt, exc
                )
                time.sleep(min(attempt, 3))
        return None

    @staticmethod
    def _fallback_template(*, video_title: str, topic: str, level: str) -> str:
        return (
            f"Study summary for '{video_title}'. "
            f"This AI-generated outline introduces {topic} for {level} learners, "
            "highlights major ideas, and suggests reviewing the original video for exact details."
        )
