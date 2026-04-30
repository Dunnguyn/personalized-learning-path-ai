"""Question-generation template-fill helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def build_template_validation(
    service: Any,
    *,
    lesson_title: str,
    lesson_summary: str,
    chunks: List[Dict[str, Any]],
    target_count: int,
    question_types: List[str],
    difficulty: str,
    bloom_levels: List[str],
    chunk_ids: List[str],
    chunk_text_by_id: Dict[str, str],
    max_per_chunk: int,
) -> Any:
    template_candidates = service.question_template_service.build_candidates(
        lesson_title=lesson_title,
        lesson_summary=lesson_summary,
        chunks=chunks,
        target_count=target_count,
        question_types=question_types,
        difficulty=difficulty,
        bloom_levels=bloom_levels,
        max_per_chunk=max_per_chunk,
    )
    return service.question_validation_service.validate_candidates(
        candidates=template_candidates,
        allowed_chunk_ids=chunk_ids,
        chunk_text_by_id=chunk_text_by_id,
        default_difficulty=difficulty,
        default_bloom_levels=bloom_levels,
    )
