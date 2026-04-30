"""Target concept helpers for question generation."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Type

from backend.app.services.lesson_assessment_sizing_service import (
    lesson_assessment_sizing_service,
)
from backend.app.services.question_validator import ValidatedLessonQuestion


def resolve_matched_target_concepts(
    *,
    service: Any,
    question: ValidatedLessonQuestion,
    target_concepts: Sequence[str],
    chunk_map: Dict[str, Dict[str, Any]],
) -> List[str]:
    normalized_targets = service._extract_target_concepts(
        {"target_concepts": list(target_concepts or [])}
    )
    if not normalized_targets:
        return []
    candidates = service._collect_question_concept_candidates(
        question=question,
        chunk_map=chunk_map,
    )
    matched: List[str] = []
    for target in normalized_targets:
        if any(service._candidate_matches_concept(candidate, target) for candidate in candidates):
            matched.append(target)
    return lesson_assessment_sizing_service._normalize_concepts(matched)


def question_matches_target_concepts(
    *,
    service: Any,
    question: ValidatedLessonQuestion,
    target_concepts: Sequence[str],
    chunk_map: Dict[str, Dict[str, Any]],
) -> bool:
    return bool(
        resolve_matched_target_concepts(
            service=service,
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )
    )


def collect_keywords(
    *,
    service_cls: Type[object],
    sources: List[str],
    strict_mode: bool,
) -> List[str]:
    keywords: List[str] = []
    seen = set()
    alias_map = (
        service_cls._STRICT_CONCEPT_ALIASES
        if strict_mode
        else service_cls._CONCEPT_ALIASES
    )
    for term in sources:
        normalized = service_cls._normalize_text(term)
        for phrase, aliases in alias_map.items():
            if phrase in normalized:
                phrase_key = service_cls._normalize_text(phrase)
                if phrase_key not in seen:
                    seen.add(phrase_key)
                    keywords.append(phrase_key)
                for alias in aliases:
                    alias_key = service_cls._normalize_text(alias)
                    if alias_key not in seen:
                        seen.add(alias_key)
                        keywords.append(alias_key)
        for token in re.findall(r"\b[a-z][a-z0-9_]{2,}\b", normalized):
            if token in service_cls._FALLBACK_STOP_WORDS or token in seen:
                continue
            if not service_cls._is_domain_term(token):
                continue
            seen.add(token)
            keywords.append(token)
    return keywords
