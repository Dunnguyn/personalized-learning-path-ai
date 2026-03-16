from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from backend.app.services.question_generation.lesson_content import LessonChunk
from backend.app.services.question_generation.prompt_builder import (
    LessonQuestionPromptBuilder,
    LessonQuestionPromptInput,
)

logger = logging.getLogger(__name__)

LESSON_QUESTION_LLM_MODEL = os.getenv("LESSON_QUESTION_LLM_MODEL", os.getenv("RAG_MODEL", "models/gemini-2.5-flash"))
LESSON_QUESTION_LLM_PROVIDER = os.getenv("LESSON_QUESTION_LLM_PROVIDER", "gemini").lower()
LESSON_QUESTION_LLM_ENABLED = os.getenv("LESSON_QUESTION_LLM_ENABLED", "true").lower() == "true"


@dataclass(frozen=True)
class GeneratedLessonQuestion:
    question: str
    answer: str
    explanation: str
    keywords: List[str]
    difficulty: int
    concept: str
    source_excerpt: str
    source_chunk_id: str
    options: List[Dict[str, str]]
    correct_option: str


class LessonLLMQuestionGenerator:
    """
    MVP LLM generator.

    Notes:
    - Default provider is Gemini because the repo already initializes it elsewhere.
    - The interface stays provider-agnostic so GPT/Llama/Mistral can be plugged in later.
    """

    def __init__(self) -> None:
        self.provider = LESSON_QUESTION_LLM_PROVIDER
        self.model = LESSON_QUESTION_LLM_MODEL
        self.prompt_builder = LessonQuestionPromptBuilder()
        self.client = self._init_client()

    def is_available(self) -> bool:
        return LESSON_QUESTION_LLM_ENABLED and self.client is not None

    def generate(
        self,
        *,
        lesson_id: str,
        lesson_title: str,
        concepts: Sequence[str],
        chunks: Sequence[LessonChunk],
        target_count: int,
    ) -> List[GeneratedLessonQuestion]:
        if not self.is_available():
            return []

        prompt = self.prompt_builder.build(
            prompt_input=LessonQuestionPromptInput(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                concepts=list(concepts),
                target_count=target_count,
            ),
            chunks=chunks,
        )
        raw_text = self._call_llm(prompt)
        if not raw_text:
            return []

        parsed = self._parse_json_array(raw_text)
        results: List[GeneratedLessonQuestion] = []
        for item in parsed:
            try:
                results.append(
                    GeneratedLessonQuestion(
                        question=str(item["question"]).strip(),
                        answer=str(item["answer"]).strip(),
                        explanation=str(item["explanation"]).strip(),
                        keywords=self._normalize_keywords(item.get("keywords")),
                        difficulty=max(1, min(5, int(item["difficulty"]))),
                        concept=str(item["concept"]).strip(),
                        source_excerpt=str(item["source_excerpt"]).strip(),
                        source_chunk_id=str(item["source_chunk_id"]).strip(),
                        options=self._normalize_options(item.get("options")),
                        correct_option=str(item.get("correct_option", "")).strip().upper(),
                    )
                )
            except Exception as exc:
                logger.debug("Skipping malformed generated question item: %s | item=%s", exc, item)
        return results

    def _init_client(self) -> Optional[Any]:
        if not LESSON_QUESTION_LLM_ENABLED:
            return None

        if self.provider == "gemini":
            try:
                from google import genai

                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key:
                    return None
                return genai.Client(api_key=api_key)
            except Exception as exc:
                logger.warning("Failed to initialize Gemini client for lesson question generation: %s", exc)
                return None

        logger.warning("Unsupported lesson question provider '%s'. Generator disabled.", self.provider)
        return None

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "gemini" and self.client is not None:
            try:
                response = self.client.models.generate_content(model=self.model, contents=prompt)
                text = getattr(response, "text", None)
                if text:
                    return str(text)
            except Exception as exc:
                logger.warning("Gemini question generation failed: %s", exc)
        return ""

    @staticmethod
    def _parse_json_array(raw_text: str) -> List[Dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return []

        for candidate in [text, LessonLLMQuestionGenerator._extract_json_block(text)]:
            if not candidate:
                continue
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return [item for item in parsed if isinstance(item, dict)]
            except Exception:
                continue
        return []

    @staticmethod
    def _extract_json_block(text: str) -> str:
        fenced = re.search(r"```json\s*(\[.*?\])\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()

        array_match = re.search(r"(\[\s*\{.*\}\s*\])", text, flags=re.DOTALL)
        if array_match:
            return array_match.group(1).strip()
        return ""

    @staticmethod
    def _normalize_options(raw_options: Any) -> List[Dict[str, str]]:
        if not isinstance(raw_options, list):
            return []

        normalized: List[Dict[str, str]] = []
        for index, item in enumerate(raw_options[:4]):
            if isinstance(item, dict):
                key = str(item.get("key") or chr(ord("A") + index)).strip().upper()
                text = str(item.get("text") or "").strip()
            else:
                key = chr(ord("A") + index)
                text = str(item).strip()
            if not text:
                continue
            normalized.append({"key": key, "text": text})
        return normalized

    @staticmethod
    def _normalize_keywords(raw_keywords: Any) -> List[str]:
        if not isinstance(raw_keywords, list):
            return []
        normalized: List[str] = []
        for item in raw_keywords:
            keyword = str(item).strip()
            if not keyword:
                continue
            normalized.append(keyword)
        return normalized[:5]


def generate_grounded_lesson_questions(
    *,
    lesson_id: str,
    lesson_title: str,
    concepts: Sequence[str],
    chunks: Sequence[LessonChunk],
    target_count: int,
) -> List[GeneratedLessonQuestion]:
    generator = LessonLLMQuestionGenerator()
    return generator.generate(
        lesson_id=lesson_id,
        lesson_title=lesson_title,
        concepts=concepts,
        chunks=chunks,
        target_count=target_count,
    )
