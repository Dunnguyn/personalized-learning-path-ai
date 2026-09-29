"""Semantic retrieval over chunk collection."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional

import numpy as np

from backend.app.ai_module.embedding import cosine_similarity, embedding_service
from backend.app.repositories import ResourceChunkRepository, ResourceRepository
from backend.app.services.hybrid_chunk_retrieval_service import (
    hybrid_chunk_retrieval_service,
)

logger = logging.getLogger(__name__)


class SemanticRetrievalService:
    """Retrieve top-k chunks and hydrate parent resources."""

    _INDEX_LINE_PATTERN = re.compile(
        r"^[^\n]{2,120}?(?:,|\.)?\s+\d{1,4}(?:-\d{1,4})?\s*$"
    )
    _STRUCTURAL_NOISE_HEADINGS = (
        "table of contents",
        "contents",
        "index",
        "glossary",
        "bibliography",
        "references",
        "appendix",
        "appendices",
    )

    def __init__(self) -> None:
        self.embedding_service = embedding_service
        self.chunk_repository = ResourceChunkRepository()
        self.resource_repository = ResourceRepository()

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float = 0.35,
        topic: Optional[str] = None,
        level: Optional[str] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Return best matching chunks grouped by parent resource."""
        search_started = perf_counter()
        embedding_started = perf_counter()
        query_embedding = self.embedding_service.embed_text(query)
        if timings is not None:
            timings["semantic_search_embedding_ms"] = round(
                float(timings.get("semantic_search_embedding_ms", 0.0))
                + (perf_counter() - embedding_started) * 1000.0,
                3,
            )
        where: Dict[str, Any] = {}
        if topic:
            where["topic"] = topic
        if level:
            where["level"] = level

        vector_hits = self.embedding_service.vector_store.query(
            query_embedding,
            limit=max(k * 6, 20),
            where=where or None,
        )
        vector_hit_scores: Dict[str, float] = {}
        for hit in vector_hits:
            metadata = hit.get("metadata") or {}
            key = f"{metadata.get('resource_id')}:{metadata.get('chunk_index')}"
            vector_hit_scores[key] = max(0.0, 1.0 - float(hit.get("distance", 1.0)))

        mongo_candidates = self.chunk_repository.candidate_chunks(
            topic=topic,
            level=level,
            limit=max(k * 30, 180),
        )
        ranked_candidates = hybrid_chunk_retrieval_service.rank_chunks(
            query=query,
            chunks=mongo_candidates,
            embed_fn=self.embedding_service.embed_text,
            limit=max(k * 8, 24),
            min_score=min_score * 0.8,
            topic=topic,
            level=level,
            timings=timings,
        )
        candidates: List[Dict[str, Any]] = []
        for item in ranked_candidates:
            metadata = item.get("metadata") or {}
            key = f"{item.get('resource_id')}:{item.get('chunk_index')}"
            score_breakdown = dict(item.get("score_breakdown") or {})
            vector_store_score = round(vector_hit_scores.get(key, 0.0), 6)
            final_score = self._clamp(
                0.86 * float(item.get("score") or 0.0) + 0.14 * vector_store_score
            )
            candidates.append(
                {
                    **item,
                    "score": round(final_score, 4),
                    "score_breakdown": {
                        **score_breakdown,
                        "vector_store_score": vector_store_score,
                    },
                }
            )

        grouped: Dict[str, Dict[str, Any]] = {}
        for candidate in candidates:
            score = float(candidate.get("score", 0.0))
            if score < min_score:
                continue
            resource_id = str(candidate["resource_id"])
            resource = grouped.get(resource_id)
            if resource is None or score > resource["score"]:
                parent = self.resource_repository.get(resource_id)
                if not parent:
                    continue
                grouped[resource_id] = {
                    "resource_id": resource_id,
                    "title": parent.get("title"),
                    "topic": parent.get("topic"),
                    "level": parent.get("metadata", {}).get("level"),
                    "source": parent.get("source"),
                    "type": parent.get("type"),
                    "score": round(score, 4),
                    "snippet": self._best_snippet(candidate),
                    "matched_chunk": candidate.get("chunk_index"),
                    "matched_chunk_metadata": candidate.get("metadata") or {},
                    "matched_terms": candidate.get("matched_terms") or [],
                    "retrieval_signals": candidate.get("score_breakdown") or {},
                    "metadata": parent.get("metadata", {}),
                    "content_summary": parent.get("content_summary"),
                }

        results = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)
        if timings is not None:
            timings["semantic_search_total_ms"] = round(
                float(timings.get("semantic_search_total_ms", 0.0))
                + (perf_counter() - search_started) * 1000.0,
                3,
            )
        return results[:k]

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    def _search_mongo_candidates(
        self,
        *,
        query_embedding: np.ndarray,
        k: int,
        min_score: float,
        topic: Optional[str],
        level: Optional[str],
    ) -> List[Dict[str, Any]]:
        candidates = self.chunk_repository.candidate_chunks(
            topic=topic, level=level, limit=max(k, 100)
        )
        scored: List[Dict[str, Any]] = []
        for chunk in candidates:
            embedding = np.array(chunk.get("embedding") or [], dtype=float)
            if embedding.size == 0:
                continue
            score = self._candidate_score(
                base_score=cosine_similarity(query_embedding, embedding),
                metadata=chunk.get("metadata") or {},
                content=str(chunk.get("content") or ""),
            )
            if score < min_score:
                continue
            scored.append({**chunk, "score": round(score, 4)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _chunk_noise_penalty(cls, *, metadata: Dict[str, Any], content: str) -> float:
        normalized_content = cls._normalize_text(content)
        if not normalized_content:
            return 1.0
        heading = cls._normalize_text(
            " ".join(
                [
                    str(metadata.get("heading") or ""),
                    str(metadata.get("section_title") or ""),
                    str(metadata.get("chunk_summary") or ""),
                ]
            )
        )
        lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
        index_like_lines = sum(1 for line in lines if cls._INDEX_LINE_PATTERN.match(line))
        penalty = 0.0
        if str(metadata.get("content_kind") or "").strip().lower() == "structural":
            penalty += 0.45
        if any(heading.startswith(item) for item in cls._STRUCTURAL_NOISE_HEADINGS):
            penalty += 0.25
        if any(item in normalized_content for item in cls._STRUCTURAL_NOISE_HEADINGS):
            penalty += 0.2
        if lines:
            penalty += min(index_like_lines / max(len(lines), 1) * 1.5, 0.4)
        return min(max(penalty, 0.0), 1.0)

    @classmethod
    def _candidate_score(
        cls,
        *,
        base_score: float,
        metadata: Dict[str, Any],
        content: str,
    ) -> float:
        questionability = float(metadata.get("questionability_score") or 0.0)
        role = str(metadata.get("instruction_role") or "").strip().lower()
        role_bonus = 0.0
        if role in {"definition", "explanation", "worked_example"}:
            role_bonus = 0.04
        noise_penalty = cls._chunk_noise_penalty(metadata=metadata, content=content)
        score = float(base_score) + 0.08 * questionability + role_bonus - 0.18 * noise_penalty
        return min(max(score, 0.0), 1.0)

    @staticmethod
    def _best_snippet(candidate: Dict[str, Any]) -> str:
        metadata = candidate.get("metadata") or {}
        summary = str(metadata.get("chunk_summary") or "").strip()
        if summary:
            return summary[:600]
        return str(candidate.get("content") or "")[:600]
