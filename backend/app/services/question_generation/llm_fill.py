"""Question-generation LLM fill helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def collect_additional_llm_questions(
    service: Any,
    *,
    context: Dict[str, Any],
    recommendation: Dict[str, Any] | None,
    chunks: List[Dict[str, Any]],
    chunk_ids: List[str],
    existing_questions: List[Any],
    target_count: int,
    question_types: List[str],
    difficulty: str,
    bloom_levels: List[str],
    max_attempts: int,
) -> List[Any]:
    del chunk_ids

    if not existing_questions or target_count <= len(existing_questions):
        return []

    max_attempts = max(1, int(max_attempts or 1))
    merged_questions = list(existing_questions)
    used_chunk_ids = {
        chunk_id
        for question in existing_questions
        for chunk_id in getattr(question, "chunk_ids", [])
        if chunk_id
    }

    attempt = 0
    while len(merged_questions) < target_count and attempt < max_attempts:
        attempt += 1
        candidate_chunks = [
            chunk
            for chunk in chunks
            if str(chunk.get("_id") or "").strip() not in used_chunk_ids
        ]
        if not candidate_chunks:
            candidate_chunks = list(chunks)

        candidate_chunk_ids = [
            str(chunk.get("_id") or "").strip()
            for chunk in candidate_chunks
            if str(chunk.get("_id") or "").strip()
        ]
        if not candidate_chunk_ids:
            break

        fill_validation = service._run_generation(
            context=context,
            recommendation=recommendation,
            chunks=candidate_chunks,
            chunk_ids=candidate_chunk_ids,
            target_count=max(1, target_count - len(merged_questions)),
            question_types=question_types,
            difficulty=difficulty,
            bloom_levels=bloom_levels,
        )
        if not fill_validation or fill_validation.status != "ok":
            break

        merged_validation = service.question_validation_service.merge_deduplicate(
            question_groups=[merged_questions, list(fill_validation.questions)],
            target_count=target_count,
        )
        if not merged_validation.questions:
            break

        merged_questions = list(merged_validation.questions)
        used_chunk_ids = {
            chunk_id
            for question in merged_questions
            for chunk_id in getattr(question, "chunk_ids", [])
            if chunk_id
        }

    return [
        question
        for question in merged_questions
        if service._question_signature(question)
        not in {
            service._question_signature(item)
            for item in existing_questions
            if service._question_signature(item)
        }
    ]
