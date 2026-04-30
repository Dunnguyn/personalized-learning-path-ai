"""Question-generation scope loading helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.services.question_generation.noise_filter import (
    assess_question_generation_noise,
)


def load_generation_scope(
    service: Any,
    *,
    lesson_id: str,
    context: Dict[str, Any],
    recommendation: Dict[str, Any] | None,
) -> tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
    """Resolve the recommended lesson chunks used as the question-generation scope."""
    del lesson_id

    if not recommendation:
        raise ValueError(
            "Lesson has no recommended chunks. Generate recommended chunks first."
        )

    chunk_ids = [str(item) for item in recommendation.get("chunk_ids", [])]
    if not chunk_ids:
        raise ValueError("Lesson recommendation does not contain chunk ids.")

    chunks = service.chunk_repository.get_by_ids(chunk_ids)
    if not chunks:
        raise ValueError("Recommended chunks could not be loaded.")

    if len(chunks) != len(chunk_ids):
        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        chunks = [chunk_map[item] for item in chunk_ids if item in chunk_map]

    recommended_chunk_map = {
        str(item.get("chunk_id") or ""): item
        for item in recommendation.get("recommended_chunks", [])
        if str(item.get("chunk_id") or "").strip()
    }
    keyword_profile = (
        service._build_keyword_profile(
            context,
            metadata={"target_concepts": list(context.get("target_concepts") or [])},
        )
        if hasattr(service, "_build_keyword_profile")
        else {"strict": [], "broad": []}
    )

    filtered_chunks: List[Dict[str, Any]] = []
    filtered_chunk_ids: List[str] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("_id") or "").strip()
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        recommendation_chunk = recommended_chunk_map.get(chunk_id, {})
        noise_signals = assess_question_generation_noise(
            content=str(chunk.get("content") or ""),
            metadata=metadata,
            strict_keywords=keyword_profile.get("strict", []),
            broad_keywords=keyword_profile.get("broad", []),
            target_concepts=(
                recommendation_chunk.get("matched_required_concepts")
                or context.get("target_concepts")
                or []
            ),
            covered_concepts=(
                recommendation_chunk.get("covered_concepts")
                or chunk.get("covered_concepts")
                or metadata.get("covered_concepts")
                or []
            ),
        )
        if noise_signals["resource_noise"]:
            continue
        filtered_chunks.append(chunk)
        filtered_chunk_ids.append(chunk_id)

    if filtered_chunks:
        return recommendation, filtered_chunk_ids, filtered_chunks

    return recommendation, chunk_ids, chunks
