"""Normalize and validate lesson target concepts against lesson context."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Dict, List, Sequence


_NOISE_TOKENS = {
    "and",
    "bai",
    "chapter",
    "chuong",
    "content",
    "example",
    "lesson",
    "noi",
    "python",
    "section",
    "text",
}


@dataclass(frozen=True)
class ConceptNormalizationResult:
    normalized_target_concepts: List[str]
    rejected_target_concepts: List[str]
    concept_mapping_debug: List[Dict[str, Any]]


class ConceptNormalizationService:
    """Normalize target concepts and reject noisy tokens that do not map to the lesson."""

    def normalize_target_concepts(
        self,
        raw_target_concepts: Sequence[str] | None,
        lesson_context: Dict[str, Any] | None,
    ) -> ConceptNormalizationResult:
        canonical_concepts = self._collect_lesson_concepts(lesson_context)
        normalized_target_concepts: List[str] = []
        rejected_target_concepts: List[str] = []
        concept_mapping_debug: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for raw_value in raw_target_concepts or []:
            raw_text = str(raw_value or "").strip()
            cleaned = self._normalize_text(raw_text)
            debug_entry: Dict[str, Any] = {
                "raw": raw_text,
                "normalized": cleaned,
                "matched": None,
                "accepted": False,
                "reason": None,
            }
            if not self._is_candidate_token(cleaned):
                debug_entry["reason"] = "invalid_or_noisy_token"
                rejected_target_concepts.append(raw_text or cleaned)
                concept_mapping_debug.append(debug_entry)
                continue

            matched = self._match_canonical_concept(cleaned, canonical_concepts)
            if not matched:
                debug_entry["reason"] = "no_lesson_match"
                rejected_target_concepts.append(raw_text or cleaned)
                concept_mapping_debug.append(debug_entry)
                continue

            debug_entry["matched"] = matched
            debug_entry["accepted"] = True
            if matched not in seen:
                seen.add(matched)
                normalized_target_concepts.append(matched)
            concept_mapping_debug.append(debug_entry)

        return ConceptNormalizationResult(
            normalized_target_concepts=normalized_target_concepts,
            rejected_target_concepts=rejected_target_concepts,
            concept_mapping_debug=concept_mapping_debug,
        )

    def extract_fallback_target_concepts(
        self,
        lesson_context: Dict[str, Any] | None,
        *,
        limit: int = 3,
    ) -> List[str]:
        counter: Counter[str] = Counter()
        context = lesson_context or {}
        for chunk in context.get("chunks") or []:
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            for source in (chunk.get("covered_concepts"), metadata.get("covered_concepts")):
                values = source if isinstance(source, list) else [source] if source else []
                for value in values:
                    token = self._normalize_text(value)
                    if self._is_candidate_token(token):
                        counter[token] += 1
        if counter:
            return [item for item, _ in counter.most_common(max(1, int(limit or 3)))]
        return self._collect_lesson_concepts(context)[: max(1, int(limit or 3))]

    def _collect_lesson_concepts(self, lesson_context: Dict[str, Any] | None) -> List[str]:
        context = lesson_context or {}
        lesson = context.get("lesson") if isinstance(context.get("lesson"), dict) else {}
        lesson_metadata = lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        values: List[str] = []
        for source in (
            lesson_metadata.get("covered_concepts"),
            lesson_metadata.get("keywords"),
            lesson.get("keywords"),
            lesson.get("learning_objectives"),
            lesson.get("topic"),
            lesson_metadata.get("main_concept"),
        ):
            source_values = source if isinstance(source, list) else [source] if source else []
            values.extend(str(item) for item in source_values)

        for chunk in context.get("chunks") or []:
            metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            for source in (chunk.get("covered_concepts"), metadata.get("covered_concepts")):
                source_values = source if isinstance(source, list) else [source] if source else []
                values.extend(str(item) for item in source_values)

        result: List[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_text(value)
            if not self._is_candidate_token(normalized) or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _match_canonical_concept(
        self,
        normalized_target: str,
        canonical_concepts: Sequence[str],
    ) -> str | None:
        if not normalized_target:
            return None

        singular_target = self._singularize(normalized_target)
        for candidate in canonical_concepts:
            singular_candidate = self._singularize(candidate)
            if (
                normalized_target == candidate
                or singular_target == singular_candidate
                or normalized_target in candidate
                or candidate in normalized_target
            ):
                return candidate

        scored: List[tuple[float, str]] = []
        for candidate in canonical_concepts:
            ratio = SequenceMatcher(None, singular_target, self._singularize(candidate)).ratio()
            if ratio >= 0.8:
                scored.append((ratio, candidate))
        if scored:
            scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
            return scored[0][1]
        return None

    @staticmethod
    def _is_candidate_token(value: str) -> bool:
        token = str(value or "").strip()
        if len(token) < 3:
            return False
        if token in _NOISE_TOKENS:
            return False
        if token.isdigit():
            return False
        if re.fullmatch(r"[a-z]{1,2}", token):
            return False
        return True

    @staticmethod
    def _singularize(value: str) -> str:
        token = str(value or "").strip()
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith("es") and len(token) > 4:
            return token[:-2]
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[_\-/]+", " ", text)
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


concept_normalization_service = ConceptNormalizationService()
