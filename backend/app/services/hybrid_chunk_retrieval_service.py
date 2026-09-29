"""Pure chunk-level hybrid retrieval scoring shared by search and evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, List, Sequence

import numpy as np

from backend.app.services.lesson_semantic_query_service import (
    lesson_semantic_query_service,
)
from backend.app.services.question_nlp_service import question_nlp_service


@dataclass(frozen=True)
class HybridChunkRetrievalWeights:
    vector_score: float = 0.54
    lexical_score: float = 0.26
    metadata_score: float = 0.20


class HybridChunkRetrievalService:
    """Rank chunk candidates with vector, lexical, and metadata signals."""

    _LEVEL_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}

    def __init__(self, weights: HybridChunkRetrievalWeights | None = None) -> None:
        self.weights = weights or HybridChunkRetrievalWeights()

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _tokenize(cls, value: str) -> List[str]:
        return [
            token
            for token in re.findall(r"\w+", cls._normalize_text(value))
            if len(token) >= 3
        ]

    @classmethod
    def _dedupe_terms(
        cls, values: Iterable[str], *, limit: int | None = None
    ) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for value in values:
            token = cls._normalize_text(value)
            if not token or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
            if limit is not None and len(ordered) >= limit:
                break
        return ordered

    @classmethod
    def _goal_terms(
        cls,
        query: str,
        *,
        topic: str | None = None,
        level: str | None = None,
        extra_terms: Sequence[str] | None = None,
    ) -> List[str]:
        payload = lesson_semantic_query_service.build_query_payload(
            goal=str(query or ""),
            subject_topic=str(topic or ""),
            extra_terms=[str(item) for item in (extra_terms or []) if item],
        )
        return cls._dedupe_terms(
            [
                *payload.get("english_terms", []),
                *payload.get("vietnamese_terms", []),
                str(query or ""),
                str(topic or ""),
                str(level or ""),
                *[str(item) for item in (extra_terms or []) if item],
            ],
            limit=20,
        )

    @staticmethod
    def _cosine(left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0 or math.isnan(denominator):
            return 0.0
        return float(np.dot(left, right) / denominator)

    @classmethod
    def _lexical_overlap_score(cls, terms: Sequence[str], text: str) -> float:
        normalized_terms = cls._dedupe_terms(terms)
        if not normalized_terms:
            return 0.0
        normalized_text = cls._normalize_text(text)
        hits = 0
        for term in normalized_terms:
            if term in normalized_text:
                hits += 1
        return cls._clamp(hits / max(min(len(normalized_terms), 6), 1))

    @classmethod
    def _matched_terms(
        cls,
        *,
        terms: Sequence[str],
        searchable_text: str,
        metadata: Dict[str, Any],
        limit: int = 6,
    ) -> List[str]:
        normalized_text = cls._normalize_text(searchable_text)
        concept_terms = cls._dedupe_terms(
            [
                *[str(item) for item in metadata.get("covered_concepts", []) or []],
                *[str(item) for item in metadata.get("chunk_keywords", []) or []],
            ],
            limit=10,
        )
        return cls._dedupe_terms(
            [
                *[term for term in cls._dedupe_terms(terms) if term in normalized_text],
                *[term for term in concept_terms if term in normalized_text],
            ],
            limit=limit,
        )

    @classmethod
    def _metadata_score(
        cls,
        *,
        metadata: Dict[str, Any],
        topic: str | None,
        level: str | None,
        terms: Sequence[str],
        searchable_text: str,
    ) -> float:
        normalized_topic = cls._normalize_text(topic or "")
        normalized_level = cls._normalize_text(level or "")
        chunk_topic = cls._normalize_text(metadata.get("topic") or "")
        chunk_level = cls._normalize_text(metadata.get("level") or "")
        instruction_role = cls._normalize_text(metadata.get("instruction_role") or "")
        content_kind = cls._normalize_text(metadata.get("content_kind") or "")
        questionability = float(metadata.get("questionability_score") or 0.0)

        score = 0.0
        if normalized_topic:
            if normalized_topic == chunk_topic:
                score += 0.38
            elif normalized_topic and normalized_topic in cls._normalize_text(searchable_text):
                score += 0.18

        if normalized_level:
            if normalized_level == chunk_level:
                score += 0.24
            else:
                learner_rank = cls._LEVEL_ORDER.get(normalized_level, 1)
                chunk_rank = cls._LEVEL_ORDER.get(chunk_level, learner_rank)
                if abs(learner_rank - chunk_rank) == 1:
                    score += 0.12

        concept_overlap = cls._lexical_overlap_score(
            terms,
            " ".join(str(item) for item in metadata.get("covered_concepts", []) or []),
        )
        score += 0.24 * concept_overlap

        if instruction_role in {"definition", "explanation", "worked_example"}:
            score += 0.08
        if content_kind == "structural":
            score -= 0.22

        score += 0.08 * cls._clamp(questionability)
        return cls._clamp(score)

    @staticmethod
    def _searchable_text(chunk: Dict[str, Any]) -> str:
        metadata = chunk.get("metadata") or {}
        parts = [
            str(metadata.get("heading") or ""),
            str(metadata.get("section_title") or ""),
            str(metadata.get("chunk_summary") or ""),
            " ".join(str(item) for item in metadata.get("chunk_keywords", []) or []),
            " ".join(str(item) for item in metadata.get("covered_concepts", []) or []),
            str(chunk.get("content") or ""),
        ]
        return " ".join(part for part in parts if part).strip()

    def rank_chunks(
        self,
        *,
        query: str,
        chunks: Sequence[Dict[str, Any]],
        embed_fn: Callable[[str], List[float]],
        limit: int,
        min_score: float = 0.0,
        topic: str | None = None,
        level: str | None = None,
        extra_terms: Sequence[str] | None = None,
        timings: Dict[str, float] | None = None,
    ) -> List[Dict[str, Any]]:
        if not chunks:
            return []

        terms = self._goal_terms(
            query,
            topic=topic,
            level=level,
            extra_terms=extra_terms,
        )
        query_payload = lesson_semantic_query_service.build_query_payload(
            goal=str(query or ""),
            subject_topic=str(topic or ""),
            extra_terms=[str(item) for item in (extra_terms or []) if item],
        )
        query_text = (
            query_payload.get("bilingual_query")
            or query_payload.get("english_query")
            or str(query or "")
        )
        started_embedding = perf_counter()
        query_vector = np.array(embed_fn(query_text), dtype=float)
        if timings is not None:
            timings["sentence_transformers_embedding_ms"] = round(
                float(timings.get("sentence_transformers_embedding_ms", 0.0))
                + (perf_counter() - started_embedding) * 1000.0,
                3,
            )

        scored: List[Dict[str, Any]] = []
        for chunk in chunks:
            metadata = chunk.get("metadata") or {}
            searchable_text = self._searchable_text(chunk)
            lexical_overlap = self._lexical_overlap_score(terms, searchable_text)
            lexical_backend = question_nlp_service.lexical_relevance(
                searchable_text,
                terms[:10],
                timings=timings,
            )
            lexical_score = self._clamp(max(lexical_overlap, lexical_backend))

            try:
                chunk_vector = np.array(chunk.get("embedding") or [], dtype=float)
            except Exception:
                chunk_vector = np.array([], dtype=float)
            vector_score = (
                self._clamp(self._cosine(query_vector, chunk_vector))
                if chunk_vector.size > 0
                else 0.0
            )
            metadata_score = self._metadata_score(
                metadata=metadata,
                topic=topic,
                level=level,
                terms=terms,
                searchable_text=searchable_text,
            )
            matched_terms = self._matched_terms(
                terms=terms,
                searchable_text=searchable_text,
                metadata=metadata,
            )
            final_score = self._clamp(
                self.weights.vector_score * vector_score
                + self.weights.lexical_score * lexical_score
                + self.weights.metadata_score * metadata_score
            )
            if final_score < min_score:
                continue
            scored.append(
                {
                    **chunk,
                    "score": round(final_score, 6),
                    "score_breakdown": {
                        "vector_score": round(vector_score, 6),
                        "lexical_score": round(lexical_score, 6),
                        "metadata_score": round(metadata_score, 6),
                    },
                    "matched_terms": matched_terms,
                    "preview": re.sub(r"\s+", " ", str(chunk.get("content") or "")).strip()[
                        :240
                    ],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]


hybrid_chunk_retrieval_service = HybridChunkRetrievalService()
