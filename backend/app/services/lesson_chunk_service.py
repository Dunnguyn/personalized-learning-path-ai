"""Local-only lesson chunk recommendation service."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List
import unicodedata

import numpy as np
from bson import ObjectId

from backend.app.ai_module import cosine_similarity
from backend.app.repositories import (
    LessonRecommendedChunkRepository,
    ResourceChunkRepository,
    ResourceRepository,
)
from backend.app.services.embedding_service import embed_text
from backend.app.services.lesson_service import lesson_structure_service
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)


class LessonChunkRecommendationService:
    """Recommend and freeze chunks for a lesson using local retrieval only."""

    _CONCEPT_ALIASES = {
        "bien": ["variable", "variables", "assignment", "value"],
        "kieu du lieu": [
            "data",
            "type",
            "types",
            "string",
            "integer",
            "float",
            "boolean",
        ],
        "toan tu": [
            "operator",
            "operators",
            "expression",
            "arithmetic",
            "comparison",
            "logical",
        ],
        "list": ["list", "lists", "append", "sort", "index", "slice"],
        "dict": [
            "dict",
            "dictionary",
            "dictionaries",
            "key",
            "value",
            "keys",
            "values",
            "items",
        ],
        "dictionary": [
            "dict",
            "dictionary",
            "dictionaries",
            "key",
            "value",
            "keys",
            "values",
            "items",
        ],
        "tuple": ["tuple", "tuples", "pair", "pairs"],
        "set": ["set", "sets", "unique"],
        "ham": ["function", "functions", "method", "methods", "def", "return"],
        "vong lap": ["loop", "loops", "while", "for", "iteration", "iterable"],
        "dieu kien": ["condition", "conditional", "if", "elif", "else", "boolean"],
        "chuoi": ["string", "strings", "text", "split", "strip"],
        "tep": ["file", "files", "open", "read", "write"],
        "mang": ["array", "list", "lists", "index"],
        "xu ly du lieu": [
            "data",
            "processing",
            "analysis",
            "count",
            "parse",
            "extract",
        ],
    }
    _STOP_WORDS = {
        "and",
        "are",
        "bai",
        "backend",
        "beginner",
        "chapter",
        "cho",
        "cua",
        "data",
        "for",
        "from",
        "goal",
        "hoc",
        "intermediate",
        "advanced",
        "lesson",
        "muc",
        "python",
        "subject",
        "tai",
        "the",
        "this",
        "thuc",
        "tieu",
        "trinh",
        "va",
        "voi",
        "xu",
    }

    def __init__(self) -> None:
        self.lesson_structure_service = lesson_structure_service
        self.chunk_repository = ResourceChunkRepository()
        self.resource_repository = ResourceRepository()
        self.recommendation_repository = LessonRecommendedChunkRepository()

        self.chunk_repository.ensure_indexes()
        self.resource_repository.ensure_indexes()
        self.recommendation_repository.ensure_indexes()
        self.reranking_service = RecommendationRerankingService(
            ReRankingConfig(
                enabled=True,
                lambda_relevance=0.78,
                exploration_weight=0.02,
            )
        )

    def recommend_chunks(
        self,
        *,
        lesson_id: str,
        max_chunks: int,
        selection_strategy: str,
        enable_diversity_reranking: bool,
        diversity_lambda: float | None,
        resource_ids: List[str],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self.lesson_structure_service.get_lesson_context(lesson_id)
        subject = context["subject"]
        chapter = context["chapter"]
        lesson = context["lesson"]

        query_text = self._build_lesson_query(
            subject=subject, chapter=chapter, lesson=lesson
        )
        query_embedding = np.array(embed_text(query_text), dtype=float)
        lexical_terms = self._build_search_terms(
            subject=subject, chapter=chapter, lesson=lesson
        )
        preferred_phrases = self._build_preferred_phrases(
            chapter=chapter, lesson=lesson
        )

        scoped_resource_ids = resource_ids or [
            str(item) for item in lesson.get("resource_ids", [])
        ]
        candidate_chunks = self.chunk_repository.candidate_chunks(
            topic=lesson.get("topic") or chapter.get("topic") or subject.get("topic"),
            level=lesson.get("level"),
            resource_ids=scoped_resource_ids or None,
            limit=max(max_chunks * 25, 100),
        )
        if not candidate_chunks:
            candidate_chunks = self.chunk_repository.candidate_chunks(
                level=lesson.get("level"),
                resource_ids=scoped_resource_ids or None,
                limit=max(max_chunks * 25, 100),
            )
        if not candidate_chunks:
            raise ValueError("No candidate chunks available for recommendation.")

        ranked_chunks = []
        resource_map: Dict[str, Dict[str, Any]] = {}
        candidate_resource_ids = sorted(
            {
                str(chunk.get("resource_id"))
                for chunk in candidate_chunks
                if chunk.get("resource_id")
            }
        )
        if candidate_resource_ids:
            resources = self.resource_repository.get_many(candidate_resource_ids)
            resource_map = {str(item.get("_id")): item for item in resources}

        for chunk in candidate_chunks:
            embedding = np.array(chunk.get("embedding") or [], dtype=float)
            if embedding.size == 0:
                continue
            semantic_score = float(cosine_similarity(query_embedding, embedding))
            lexical_score = self._calculate_lexical_score(
                content=str(chunk.get("content") or ""),
                search_terms=lexical_terms,
                preferred_phrases=preferred_phrases,
            )
            base_score = self._blend_scores(
                semantic_score=semantic_score, lexical_score=lexical_score
            )
            resource_id = str(chunk["resource_id"])
            resource_doc = resource_map.get(resource_id, {})
            resource_metadata = (
                resource_doc.get("metadata", {})
                if isinstance(resource_doc, dict)
                else {}
            )
            ranked_chunks.append(
                {
                    "chunk_id": str(chunk["_id"]),
                    "resource_id": resource_id,
                    "chunk_index": int(chunk.get("chunk_index", 0)),
                    "page_number": self._resolve_page_number(chunk),
                    "score": round(base_score, 4),
                    "final_base_score": round(base_score, 6),
                    "semantic_score": round(semantic_score, 4),
                    "lexical_score": round(lexical_score, 4),
                    "preview": str(chunk.get("content") or "")[:240],
                    "source": resource_doc.get("source"),
                    "type": resource_doc.get("type"),
                    "topic": resource_doc.get("topic")
                    or chunk.get("metadata", {}).get("topic"),
                    "level": resource_doc.get("level")
                    or chunk.get("metadata", {}).get("level"),
                    "pedagogy_type": resource_metadata.get("pedagogy_type")
                    or resource_doc.get("pedagogy_type"),
                    "embedding": chunk.get("embedding"),
                    "popularity": 0.0,
                    "is_recently_seen": False,
                }
            )

        ranked_chunks.sort(
            key=lambda item: (item["score"], -item["chunk_index"]), reverse=True
        )
        rerank_metadata: Dict[str, Any] = {
            "strategy": "disabled",
            "diversity_ratio": 0.0,
        }
        if enable_diversity_reranking and ranked_chunks:
            original_lambda = self.reranking_service.config.lambda_relevance
            if diversity_lambda is not None:
                self.reranking_service.config.lambda_relevance = float(diversity_lambda)
            rerank_result = self.reranking_service.rerank(
                ranked_chunks[: max(max_chunks * 3, max_chunks)], max_chunks
            )
            selected_chunks = rerank_result.get("items", [])
            rerank_metadata = rerank_result.get("metadata", rerank_metadata)
            self.reranking_service.config.lambda_relevance = original_lambda
        else:
            selected_chunks = ranked_chunks[:max_chunks]

        for item in selected_chunks:
            if item.get("rerank_score") is not None:
                item["score"] = round(
                    float(
                        item.get("rerank_score") or item.get("final_base_score") or 0.0
                    ),
                    4,
                )

        selected_chunk_ids = [item["chunk_id"] for item in selected_chunks]
        selected_resource_ids = sorted(
            {item["resource_id"] for item in selected_chunks}
        )
        if not selected_chunk_ids:
            raise ValueError("Chunk recommendation produced no scoped chunks.")

        recommendation = self.recommendation_repository.upsert_for_lesson(
            lesson_id,
            {
                "subject_id": subject["_id"],
                "chapter_id": chapter["_id"],
                "lesson_id": lesson["_id"],
                "chunk_ids": [ObjectId(item) for item in selected_chunk_ids],
                "resource_ids": [ObjectId(item) for item in selected_resource_ids],
                "selection_strategy": selection_strategy,
                "metadata": {
                    **metadata,
                    "query_text": query_text,
                    "lexical_terms": sorted(lexical_terms),
                    "preferred_phrases": preferred_phrases,
                    "candidate_count": len(candidate_chunks),
                    "selected_count": len(selected_chunks),
                    "diversity_reranking": {
                        "enabled": enable_diversity_reranking,
                        **rerank_metadata,
                    },
                    "scores": {
                        item["chunk_id"]: item["score"] for item in selected_chunks
                    },
                },
            },
        )
        return self._serialize_recommendation(recommendation, selected_chunks)

    def get_recommendation(self, lesson_id: str) -> Dict[str, Any]:
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id)
        if not recommendation:
            raise ValueError("No recommended chunks stored for this lesson.")
        chunk_ids = [str(item) for item in recommendation.get("chunk_ids", [])]
        chunks = self.chunk_repository.get_by_ids(chunk_ids)
        chunk_map = {str(chunk["_id"]): chunk for chunk in chunks}
        selected_chunks = []
        scores = recommendation.get("metadata", {}).get("scores", {})
        for chunk_id in chunk_ids:
            chunk = chunk_map.get(chunk_id)
            if not chunk:
                continue
            selected_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "resource_id": str(chunk["resource_id"]),
                    "chunk_index": int(chunk.get("chunk_index", 0)),
                    "page_number": self._resolve_page_number(chunk),
                    "score": float(scores.get(chunk_id, 0.0)),
                    "preview": str(chunk.get("content") or "")[:240],
                }
            )
        return self._serialize_recommendation(recommendation, selected_chunks)

    @staticmethod
    def _build_lesson_query(
        *, subject: Dict[str, Any], chapter: Dict[str, Any], lesson: Dict[str, Any]
    ) -> str:
        parts = [
            subject.get("title"),
            subject.get("description"),
            chapter.get("title"),
            chapter.get("description"),
            lesson.get("title"),
            lesson.get("summary"),
            " ".join(lesson.get("learning_objectives", [])),
            " ".join(lesson.get("keywords", [])),
        ]
        return " | ".join([str(item).strip() for item in parts if item]).strip()

    @classmethod
    def _build_search_terms(
        cls,
        *,
        subject: Dict[str, Any],
        chapter: Dict[str, Any],
        lesson: Dict[str, Any],
    ) -> set[str]:
        terms: set[str] = set()
        sources = [
            lesson.get("title"),
            lesson.get("summary"),
            chapter.get("title"),
            subject.get("title"),
            " ".join(lesson.get("keywords", [])),
            " ".join(lesson.get("learning_objectives", [])),
        ]
        for source in sources:
            for token in re.findall(
                r"\b\w+\b", str(source or "").lower(), flags=re.UNICODE
            ):
                if len(token) < 3 or token.isdigit() or token in cls._STOP_WORDS:
                    continue
                terms.add(token)
            terms.update(cls._expand_alias_terms(str(source or "")))
        return terms

    @classmethod
    def _build_preferred_phrases(
        cls, *, chapter: Dict[str, Any], lesson: Dict[str, Any]
    ) -> List[str]:
        phrases = [
            str(lesson.get("title") or "").strip(),
            *[str(item).strip() for item in lesson.get("keywords", [])],
            str(chapter.get("title") or "").strip(),
        ]
        normalized_phrases = [
            cls._normalize_text(item) for item in phrases if item and len(item) >= 4
        ]
        expanded = set(normalized_phrases)
        for phrase in phrases:
            expanded.update(cls._expand_alias_terms(str(phrase or "")))
        return sorted(item for item in expanded if item)

    @classmethod
    def _calculate_lexical_score(
        cls,
        *,
        content: str,
        search_terms: set[str],
        preferred_phrases: List[str],
    ) -> float:
        normalized = cls._normalize_text(content)
        if not normalized:
            return 0.0

        chunk_terms = {
            token
            for token in re.findall(r"\b\w+\b", normalized, flags=re.UNICODE)
            if len(token) >= 3 and not token.isdigit()
        }
        overlap = search_terms.intersection(chunk_terms)
        overlap_score = len(overlap) / max(len(search_terms), 1)
        phrase_bonus = 0.0
        for phrase in preferred_phrases:
            phrase_terms = [
                token
                for token in re.findall(r"\b\w+\b", phrase, flags=re.UNICODE)
                if len(token) >= 3
            ]
            if not phrase_terms:
                continue
            if phrase in normalized:
                phrase_bonus += 0.35
                continue
            matched_terms = sum(1 for token in phrase_terms if token in chunk_terms)
            if matched_terms:
                phrase_bonus += 0.12 * (matched_terms / len(phrase_terms))
        return min(1.0, overlap_score + phrase_bonus)

    @staticmethod
    def _blend_scores(*, semantic_score: float, lexical_score: float) -> float:
        if lexical_score > 0:
            return lexical_score * 0.85 + semantic_score * 0.15
        return max(0.0, semantic_score) * 0.05

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_text.lower()).strip()

    @classmethod
    def _expand_alias_terms(cls, value: str) -> set[str]:
        normalized = cls._normalize_text(value)
        expanded: set[str] = set()
        for phrase, aliases in cls._CONCEPT_ALIASES.items():
            if phrase in normalized:
                expanded.update(aliases)
        return expanded

    @staticmethod
    def _resolve_page_number(chunk: Dict[str, Any]) -> int | None:
        metadata = (
            chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        )
        page_number = metadata.get("page_number")
        if isinstance(page_number, int) and page_number > 0:
            return page_number
        return None

    def _serialize_recommendation(
        self, recommendation: Dict[str, Any], selected_chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        resource_ids = [
            item.get("resource_id")
            for item in selected_chunks
            if item.get("resource_id")
        ]
        resources = (
            self.resource_repository.get_many(resource_ids) if resource_ids else []
        )
        resource_map = {
            str(resource["_id"]): resource
            for resource in resources
            if resource.get("_id")
        }

        enriched_chunks = []
        for item in selected_chunks:
            resource = resource_map.get(str(item.get("resource_id")))
            resource_metadata = (
                resource.get("metadata", {}) if isinstance(resource, dict) else {}
            )
            enriched_chunks.append(
                {
                    **item,
                    "resource_title": (
                        str(resource.get("title") or "") if resource else None
                    ),
                    "resource_source": (
                        str(resource.get("source") or "") if resource else None
                    ),
                    "resource_url": (
                        str(resource_metadata.get("url") or "").strip()
                        if resource_metadata.get("url")
                        else None
                    ),
                }
            )

        return {
            "recommendation_id": str(recommendation["_id"]),
            "subject_id": str(recommendation["subject_id"]),
            "chapter_id": str(recommendation["chapter_id"]),
            "lesson_id": str(recommendation["lesson_id"]),
            "chunk_ids": [str(item) for item in recommendation.get("chunk_ids", [])],
            "resource_ids": [
                str(item) for item in recommendation.get("resource_ids", [])
            ],
            "selection_strategy": recommendation.get("selection_strategy"),
            "metadata": recommendation.get("metadata", {}),
            "recommended_chunks": enriched_chunks,
            "created_at": recommendation.get("created_at", datetime.utcnow()),
        }


lesson_chunk_service = LessonChunkRecommendationService()
