"""Lesson-scoped instructional chunk recommendation service."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
from bson import ObjectId

from backend.app.repositories import (
    ChapterRepository,
    LessonRecommendedChunkRepository,
    LessonRepository,
    ResourceChunkRepository,
    ResourceRepository,
    SubjectRepository,
)
from backend.app.services.embedding_service import embed_text
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)


@dataclass(frozen=True)
class ChunkScoringWeights:
    semantic_score: float = 0.30
    lexical_score: float = 0.15
    objective_coverage: float = 0.10
    concept_coverage: float = 0.10
    difficulty_fit: float = 0.10
    instructional_role_fit: float = 0.10
    questionability_score: float = 0.10
    novelty_score: float = 0.05


class LessonChunkService:
    """Recommend lesson-scoped chunks as an instructional sequence."""

    _DEFAULT_SEQUENCE = [
        "introduction",
        "explanation",
        "worked_example",
        "misconception_fix",
        "summary",
        "practice_hint",
    ]
    _ROLE_FALLBACKS = {
        "introduction": ("explanation", "summary"),
        "explanation": ("introduction", "worked_example", "summary"),
        "worked_example": ("practice_hint", "explanation"),
        "misconception_fix": ("explanation", "summary"),
        "summary": ("practice_hint", "explanation"),
        "practice_hint": ("worked_example", "summary"),
    }
    _ROLE_BASE_FIT = {
        "introduction": 0.86,
        "explanation": 0.92,
        "worked_example": 0.94,
        "practice_hint": 0.82,
        "summary": 0.80,
        "misconception_fix": 0.88,
    }
    _LEVEL_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}
    _CLUSTER_THRESHOLD = float(
        os.getenv("LESSON_CHUNK_CLUSTER_SIMILARITY_THRESHOLD", "0.92")
    )
    _MAX_CANDIDATES = int(os.getenv("LESSON_CHUNK_MAX_CANDIDATES", "180"))
    _MODE_WEIGHT_OVERRIDES = {
        "quick_review": {"instructional_role_fit": 0.14, "novelty_score": 0.08},
        "assessment_boost": {
            "questionability_score": 0.15,
            "objective_coverage": 0.12,
        },
    }

    def __init__(self) -> None:
        self.subject_repository = SubjectRepository()
        self.chapter_repository = ChapterRepository()
        self.lesson_repository = LessonRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.resource_repository = ResourceRepository()
        self.recommendation_repository = LessonRecommendedChunkRepository()
        self.reranker = RecommendationRerankingService(
            ReRankingConfig(enabled=True, lambda_relevance=0.78, exploration_weight=0.02)
        )

        self.chunk_repository.ensure_indexes()
        self.recommendation_repository.ensure_indexes()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip()).lower()

    @classmethod
    def _tokenize(cls, value: str) -> List[str]:
        return [token for token in re.findall(r"\w+", cls._normalize_text(value)) if len(token) >= 3]

    @staticmethod
    def _to_vector(value: Any) -> np.ndarray | None:
        if value is None or value == []:
            return None
        try:
            vector = np.array(value, dtype=float)
            if vector.size == 0:
                return None
            return vector
        except Exception:
            return None

    @classmethod
    def _cosine(cls, left: np.ndarray | None, right: np.ndarray | None) -> float:
        if left is None or right is None:
            return 0.0
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            return 0.0
        return cls._clamp(float(np.dot(left, right) / denominator))

    def _weights_for_mode(self, mode: str | None) -> ChunkScoringWeights:
        weights = ChunkScoringWeights()
        overrides = self._MODE_WEIGHT_OVERRIDES.get(str(mode or "").lower(), {})
        for field, value in overrides.items():
            weights = replace(weights, **{field: value})
        return weights

    def _get_lesson_context(self, lesson_id: str) -> Dict[str, Any]:
        lesson = self.lesson_repository.get(lesson_id)
        if not lesson:
            raise ValueError("Lesson not found.")
        chapter = self.chapter_repository.get(lesson["chapter_id"])
        subject = self.subject_repository.get(lesson["subject_id"])
        if not chapter or not subject:
            raise ValueError("Lesson hierarchy is incomplete.")
        return {"lesson": lesson, "chapter": chapter, "subject": subject}

    def _build_query_text(self, context: Dict[str, Any]) -> str:
        lesson = context["lesson"]
        chapter = context["chapter"]
        subject = context["subject"]
        objectives = lesson.get("learning_objectives") or []
        keywords = lesson.get("keywords") or []
        parts = [
            str(subject.get("title") or ""),
            str(subject.get("topic") or ""),
            str(chapter.get("title") or ""),
            str(chapter.get("description") or ""),
            str(lesson.get("title") or ""),
            str(lesson.get("summary") or ""),
            " ".join(str(item) for item in objectives if item),
            " ".join(str(item) for item in keywords if item),
        ]
        return " ".join(part for part in parts if part).strip()

    def _priority_terms(self, context: Dict[str, Any]) -> List[str]:
        lesson = context["lesson"]
        tokens: List[str] = []
        for source in [
            str(lesson.get("title") or ""),
            str(lesson.get("summary") or ""),
            *[str(item) for item in lesson.get("learning_objectives") or []],
            *[str(item) for item in lesson.get("keywords") or []],
        ]:
            for token in self._tokenize(source):
                if token not in tokens:
                    tokens.append(token)
        return tokens[:16]

    def _candidate_chunks(
        self,
        *,
        context: Dict[str, Any],
        resource_ids: Sequence[str] | None,
        max_chunks: int,
    ) -> List[Dict[str, Any]]:
        lesson = context["lesson"]
        chapter = context["chapter"]
        subject = context["subject"]
        requested_resource_ids = list(resource_ids or lesson.get("resource_ids") or [])
        queries = [
            {
                "topic": str(
                    lesson.get("topic") or chapter.get("topic") or subject.get("topic") or ""
                ).strip()
                or None,
                "level": str(lesson.get("level") or subject.get("level") or "beginner"),
                "resource_ids": requested_resource_ids or None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 24, 80)),
            },
            {
                "topic": str(
                    lesson.get("topic") or chapter.get("topic") or subject.get("topic") or ""
                ).strip()
                or None,
                "level": None,
                "resource_ids": requested_resource_ids or None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 16, 60)),
            },
            {
                "topic": None,
                "level": str(lesson.get("level") or subject.get("level") or "beginner"),
                "resource_ids": requested_resource_ids or None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 12, 50)),
            },
            {
                "topic": None,
                "level": None,
                "resource_ids": requested_resource_ids or None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 8, 40)),
            },
        ]

        seen: set[str] = set()
        candidates: List[Dict[str, Any]] = []
        for query in queries:
            rows = self.chunk_repository.candidate_chunks(**query)
            for row in rows:
                key = str(row.get("_id"))
                if not key or key in seen:
                    continue
                seen.add(key)
                candidates.append(row)
            if len(candidates) >= max(max_chunks * 18, 60):
                break
        return candidates[: self._MAX_CANDIDATES]

    @staticmethod
    def _resolve_page_number(chunk: Dict[str, Any]) -> int | None:
        metadata = chunk.get("metadata") or {}
        page_number = metadata.get("page_number")
        if isinstance(page_number, int) and page_number > 0:
            return page_number
        if isinstance(page_number, float) and page_number >= 1:
            return int(page_number)
        for key in ("page", "page_start", "pdf_page"):
            value = metadata.get(key)
            if isinstance(value, int) and value > 0:
                return value
        page_numbers = metadata.get("page_numbers")
        if isinstance(page_numbers, list):
            for value in page_numbers:
                if isinstance(value, int) and value > 0:
                    return value
        return None

    @classmethod
    def _estimate_read_time(cls, content: str) -> int:
        words = len(re.findall(r"\w+", content or ""))
        return max(1, int(math.ceil(words / 180.0)))

    @classmethod
    def _detect_instruction_role(cls, content: str, metadata: Dict[str, Any] | None = None) -> str:
        metadata = metadata or {}
        explicit = str(
            metadata.get("instruction_role")
            or metadata.get("role")
            or metadata.get("chunk_role")
            or ""
        ).strip().lower()
        if explicit in cls._ROLE_BASE_FIT:
            return explicit

        normalized = cls._normalize_text(content)
        if not normalized:
            return "explanation"

        if any(
            phrase in normalized
            for phrase in (
                "common mistake",
                "common mistakes",
                "pitfall",
                "pitfalls",
                "lỗi thường gặp",
                "nhầm lẫn",
                "sai lầm",
            )
        ):
            return "misconception_fix"
        if any(
            phrase in normalized
            for phrase in (
                "for example",
                "example:",
                "ví dụ",
                "walkthrough",
                "sample output",
                "code sample",
            )
        ) or "```" in content:
            return "worked_example"
        if any(
            phrase in normalized
            for phrase in (
                "practice",
                "exercise",
                "hint",
                "try this",
                "gợi ý",
                "bài tập",
                "thử",
            )
        ):
            return "practice_hint"
        if any(
            phrase in normalized
            for phrase in (
                "in summary",
                "to summarize",
                "summary",
                "tóm tắt",
                "kết luận",
            )
        ):
            return "summary"
        if any(
            phrase in normalized
            for phrase in (
                "introduction",
                "overview",
                "what is",
                "overview of",
                "giới thiệu",
                "tổng quan",
                "là gì",
            )
        ):
            return "introduction"
        return "explanation"

    @classmethod
    def _covered_objectives(cls, content: str, objectives: Sequence[str]) -> List[str]:
        normalized_content = cls._normalize_text(content)
        content_tokens = set(cls._tokenize(content))
        covered: List[str] = []
        for objective in objectives:
            objective_text = str(objective).strip()
            if not objective_text:
                continue
            normalized_objective = cls._normalize_text(objective_text)
            objective_tokens = set(cls._tokenize(objective_text))
            overlap = len(content_tokens & objective_tokens) / max(len(objective_tokens), 1)
            if normalized_objective in normalized_content or overlap >= 0.35:
                covered.append(objective_text)
        return covered

    @classmethod
    def _covered_concepts(
        cls,
        content: str,
        *,
        metadata: Dict[str, Any] | None,
        priority_terms: Sequence[str],
        topic: str | None,
    ) -> List[str]:
        metadata = metadata or {}
        normalized_content = cls._normalize_text(content)
        concepts: List[str] = []
        for source in (
            metadata.get("primary_concepts"),
            metadata.get("covered_concepts"),
            metadata.get("concepts"),
        ):
            if isinstance(source, list):
                for item in source:
                    token = str(item or "").strip()
                    if token and token not in concepts:
                        concepts.append(token)
            elif source:
                token = str(source).strip()
                if token and token not in concepts:
                    concepts.append(token)

        for term in priority_terms:
            if term in normalized_content and term not in concepts:
                concepts.append(term)

        if topic and topic not in concepts and cls._normalize_text(topic) in normalized_content:
            concepts.append(topic)
        return concepts[:8]

    @classmethod
    def _fact_density_score(cls, content: str) -> float:
        sentences = [item for item in re.split(r"(?<=[.!?])\s+", content or "") if item.strip()]
        tokens = re.findall(r"\w+", content or "")
        numbers = re.findall(r"\b\d+(?:\.\d+)?\b", content or "")
        definition_hits = len(
            re.findall(
                r"\b(is|are|means|refers to|defined as|là|gọi là)\b",
                cls._normalize_text(content),
            )
        )
        score = (
            0.45 * cls._clamp(len(sentences) / 8.0)
            + 0.25 * cls._clamp(len(numbers) / 5.0)
            + 0.30 * cls._clamp((definition_hits + len(tokens) / 80.0) / 3.0)
        )
        return round(cls._clamp(score), 4)

    @classmethod
    def _example_presence_score(cls, content: str) -> float:
        normalized = cls._normalize_text(content)
        has_example_phrase = any(
            phrase in normalized
            for phrase in ("for example", "example", "ví dụ", "sample", "walkthrough")
        )
        has_code = "```" in content or bool(re.search(r"\bfor\b.*:|\bwhile\b.*:|;", content))
        list_markers = len(re.findall(r"^\s*(?:[-*]|\d+\.)\s+", content or "", flags=re.MULTILINE))
        score = (
            0.45 * float(has_example_phrase)
            + 0.40 * float(has_code)
            + 0.15 * cls._clamp(list_markers / 4.0)
        )
        return round(cls._clamp(score), 4)

    @classmethod
    def _concept_explicitness_score(cls, content: str, priority_terms: Sequence[str]) -> float:
        normalized = cls._normalize_text(content)
        definition_hits = len(
            re.findall(
                r"\b(is|means|refers to|defined as|là|là một|được gọi là)\b",
                normalized,
            )
        )
        matched_terms = sum(1 for term in priority_terms if term in normalized)
        score = 0.55 * cls._clamp(definition_hits / 3.0) + 0.45 * cls._clamp(
            matched_terms / max(len(priority_terms), 1) * 3.0
        )
        return round(cls._clamp(score), 4)

    @classmethod
    def _questionability_score(
        cls,
        *,
        fact_density_score: float,
        concept_explicitness_score: float,
        example_presence_score: float,
        role: str,
    ) -> float:
        role_bonus = {
            "worked_example": 0.10,
            "explanation": 0.08,
            "misconception_fix": 0.08,
            "summary": 0.03,
            "introduction": 0.02,
            "practice_hint": 0.05,
        }.get(role, 0.0)
        score = (
            0.40 * fact_density_score
            + 0.35 * concept_explicitness_score
            + 0.25 * example_presence_score
            + role_bonus
        )
        return round(cls._clamp(score), 4)

    @classmethod
    def _difficulty_fit(cls, lesson_level: str, chunk_level: str) -> float:
        lesson_rank = cls._LEVEL_ORDER.get(str(lesson_level).lower(), 1)
        chunk_rank = cls._LEVEL_ORDER.get(str(chunk_level).lower(), lesson_rank)
        distance = abs(lesson_rank - chunk_rank)
        if distance == 0:
            return 1.0
        if distance == 1:
            return 0.68
        return 0.36

    @classmethod
    def _lexical_score(cls, query_terms: Sequence[str], content: str) -> float:
        if not query_terms:
            return 0.0
        content_tokens = set(cls._tokenize(content))
        overlap = sum(1 for term in query_terms if term in content_tokens)
        return round(cls._clamp(overlap / max(len(query_terms), 1) * 2.5), 4)

    def _score_chunk(
        self,
        *,
        semantic_score: float,
        lexical_score: float,
        objective_coverage: float,
        concept_coverage: float,
        difficulty_fit: float,
        instructional_role_fit: float,
        questionability_score: float,
        novelty_score: float,
        weights: ChunkScoringWeights,
    ) -> float:
        return round(
            self._clamp(
                weights.semantic_score * semantic_score
                + weights.lexical_score * lexical_score
                + weights.objective_coverage * objective_coverage
                + weights.concept_coverage * concept_coverage
                + weights.difficulty_fit * difficulty_fit
                + weights.instructional_role_fit * instructional_role_fit
                + weights.questionability_score * questionability_score
                + weights.novelty_score * novelty_score
            ),
            6,
        )

    def _analyze_candidate(
        self,
        *,
        chunk: Dict[str, Any],
        context: Dict[str, Any],
        query_vector: np.ndarray | None,
        query_terms: Sequence[str],
        weights: ChunkScoringWeights,
    ) -> Dict[str, Any]:
        lesson = context["lesson"]
        metadata = chunk.get("metadata") or {}
        content = str(chunk.get("content") or "")
        role = self._detect_instruction_role(content, metadata)
        chunk_vector = self._to_vector(chunk.get("embedding"))
        objectives = lesson.get("learning_objectives") or []
        priority_terms = self._priority_terms(context)
        covered_objectives = self._covered_objectives(content, objectives)
        covered_concepts = self._covered_concepts(
            content,
            metadata=metadata,
            priority_terms=priority_terms,
            topic=str(lesson.get("topic") or ""),
        )
        fact_density_score = self._fact_density_score(content)
        concept_explicitness_score = self._concept_explicitness_score(content, priority_terms)
        example_presence_score = self._example_presence_score(content)
        questionability_score = self._questionability_score(
            fact_density_score=fact_density_score,
            concept_explicitness_score=concept_explicitness_score,
            example_presence_score=example_presence_score,
            role=role,
        )

        semantic_score = round(self._cosine(query_vector, chunk_vector), 6)
        lexical_score = round(self._lexical_score(query_terms, content), 6)
        objective_coverage = round(
            self._clamp(len(covered_objectives) / max(len(objectives), 1)),
            6,
        )
        concept_coverage = round(
            self._clamp(len(covered_concepts) / max(len(priority_terms[:8]), 1)),
            6,
        )
        difficulty = str(
            metadata.get("difficulty")
            or metadata.get("level")
            or lesson.get("level")
            or "beginner"
        ).lower()
        difficulty_fit = round(
            self._difficulty_fit(str(lesson.get("level") or "beginner"), difficulty),
            6,
        )
        instructional_role_fit = round(self._ROLE_BASE_FIT.get(role, 0.75), 6)
        estimated_read_time = self._estimate_read_time(content)
        preview = re.sub(r"\s+", " ", content).strip()[:280]

        score_breakdown = {
            "semantic_score": semantic_score,
            "lexical_score": lexical_score,
            "objective_coverage": objective_coverage,
            "concept_coverage": concept_coverage,
            "difficulty_fit": difficulty_fit,
            "instructional_role_fit": instructional_role_fit,
            "questionability_score": questionability_score,
            "novelty_score": 1.0,
        }
        score = self._score_chunk(weights=weights, **score_breakdown)

        return {
            "chunk_id": str(chunk["_id"]),
            "chunk_oid": chunk["_id"],
            "resource_id": str(chunk["resource_id"]),
            "resource_oid": chunk["resource_id"],
            "chunk_index": int(chunk.get("chunk_index", 0)),
            "page_number": self._resolve_page_number(chunk),
            "preview": preview,
            "instruction_role": role,
            "difficulty": difficulty,
            "covered_objectives": covered_objectives,
            "covered_concepts": covered_concepts,
            "estimated_read_time": estimated_read_time,
            "questionability_score": questionability_score,
            "fact_density_score": fact_density_score,
            "concept_explicitness_score": concept_explicitness_score,
            "example_presence_score": example_presence_score,
            "score_breakdown": score_breakdown,
            "score": score,
            "base_score": score,
            "embedding": chunk.get("embedding"),
            "content": content,
            "metadata": metadata,
            "sequence_position": None,
            "cluster_id": None,
            "selected_as_representative": False,
            "sequence_target_role": None,
            "resource_source": None,
            "resource_title": None,
            "resource_url": None,
            "level": difficulty,
            "topic": str(metadata.get("topic") or lesson.get("topic") or ""),
            "source": str(metadata.get("source") or ""),
            "type": str(metadata.get("resource_type") or ""),
            "pedagogy_type": str(metadata.get("pedagogy_type") or ""),
            "popularity": 0.0,
            "is_recently_seen": False,
            "final_base_score": score,
        }

    def _cluster_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        ordered = sorted(candidates, key=lambda item: item.get("base_score", 0.0), reverse=True)
        clusters: List[Dict[str, Any]] = []
        for candidate in ordered:
            candidate_vector = self._to_vector(candidate.get("embedding"))
            assigned_cluster = None
            for cluster in clusters:
                similarity = self._cosine(candidate_vector, cluster.get("representative_vector"))
                if similarity >= self._CLUSTER_THRESHOLD:
                    assigned_cluster = cluster
                    break
            if assigned_cluster is None:
                cluster_id = f"cluster_{len(clusters) + 1}"
                clusters.append(
                    {
                        "cluster_id": cluster_id,
                        "representative": candidate,
                        "representative_vector": candidate_vector,
                        "members": [candidate],
                    }
                )
                continue

            assigned_cluster["members"].append(candidate)
            if candidate.get("base_score", 0.0) > assigned_cluster["representative"].get(
                "base_score", 0.0
            ):
                assigned_cluster["representative"] = candidate
                assigned_cluster["representative_vector"] = candidate_vector

        representatives: List[Dict[str, Any]] = []
        for cluster in clusters:
            representative = dict(cluster["representative"])
            representative["cluster_id"] = cluster["cluster_id"]
            representative["selected_as_representative"] = True
            representative["cluster_size"] = len(cluster["members"])
            representatives.append(representative)
        return representatives

    def _rerank_candidates(
        self,
        *,
        candidates: List[Dict[str, Any]],
        limit: int,
        enable_diversity_reranking: bool,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not candidates:
            return [], {"strategy": "empty", "diversity_ratio": 0.0}
        if not enable_diversity_reranking:
            ordered = sorted(candidates, key=lambda item: item.get("base_score", 0.0), reverse=True)
            return ordered[:limit], {"strategy": "disabled", "diversity_ratio": 0.0}

        result = self.reranker.rerank(candidates, limit=max(limit * 2, limit))
        reranked = result.get("items", [])
        return reranked[: max(limit * 2, limit)], result.get("metadata", {})

    def _target_role_fit(self, actual_role: str, target_role: str) -> float:
        if actual_role == target_role:
            return 1.0
        fallback_roles = self._ROLE_FALLBACKS.get(target_role, ())
        if actual_role in fallback_roles:
            position = fallback_roles.index(actual_role)
            return 0.84 - position * 0.08
        return 0.62

    def _build_sequence(
        self,
        *,
        candidates: List[Dict[str, Any]],
        max_chunks: int,
        weights: ChunkScoringWeights,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not candidates:
            return [], {
                "has_introduction": False,
                "has_explanation": False,
                "has_example": False,
                "has_summary": False,
                "roles_present": [],
                "missing_roles": self._DEFAULT_SEQUENCE[:max_chunks],
            }

        desired_roles = self._DEFAULT_SEQUENCE[: max(max_chunks, 1)]
        unused = list(candidates)
        selected: List[Dict[str, Any]] = []

        for target_role in desired_roles:
            if not unused or len(selected) >= max_chunks:
                break
            best_item = None
            best_rank = float("-inf")
            for candidate in unused:
                role_fit = self._target_role_fit(candidate["instruction_role"], target_role)
                rank = 0.75 * float(candidate.get("base_score", 0.0)) + 0.25 * role_fit
                if rank > best_rank:
                    best_rank = rank
                    best_item = candidate
            if best_item is None:
                continue
            enriched = dict(best_item)
            enriched["sequence_target_role"] = target_role
            enriched["assigned_role_fit"] = round(
                self._target_role_fit(best_item["instruction_role"], target_role), 6
            )
            selected.append(enriched)
            unused = [item for item in unused if item["chunk_id"] != best_item["chunk_id"]]

        for candidate in sorted(unused, key=lambda item: item.get("base_score", 0.0), reverse=True):
            if len(selected) >= max_chunks:
                break
            enriched = dict(candidate)
            enriched["sequence_target_role"] = candidate["instruction_role"]
            enriched["assigned_role_fit"] = 1.0
            selected.append(enriched)

        finalized: List[Dict[str, Any]] = []
        selected_vectors: List[np.ndarray] = []
        for index, candidate in enumerate(selected, start=1):
            vector = self._to_vector(candidate.get("embedding"))
            max_similarity = max(
                (self._cosine(vector, existing_vector) for existing_vector in selected_vectors),
                default=0.0,
            )
            novelty_score = round(self._clamp(1.0 - max_similarity), 6)
            score_breakdown = dict(candidate.get("score_breakdown", {}))
            score_breakdown["novelty_score"] = novelty_score
            score_breakdown["instructional_role_fit"] = round(
                float(
                    candidate.get(
                        "assigned_role_fit",
                        candidate.get("score_breakdown", {}).get("instructional_role_fit", 0.75),
                    )
                ),
                6,
            )
            candidate_score = self._score_chunk(
                semantic_score=float(score_breakdown.get("semantic_score", 0.0)),
                lexical_score=float(score_breakdown.get("lexical_score", 0.0)),
                objective_coverage=float(score_breakdown.get("objective_coverage", 0.0)),
                concept_coverage=float(score_breakdown.get("concept_coverage", 0.0)),
                difficulty_fit=float(score_breakdown.get("difficulty_fit", 0.0)),
                instructional_role_fit=float(score_breakdown.get("instructional_role_fit", 0.0)),
                questionability_score=float(score_breakdown.get("questionability_score", 0.0)),
                novelty_score=novelty_score,
                weights=weights,
            )
            enriched = dict(candidate)
            enriched["sequence_position"] = index
            enriched["score_breakdown"] = score_breakdown
            enriched["score"] = candidate_score
            enriched["final_base_score"] = candidate_score
            finalized.append(enriched)
            if vector is not None:
                selected_vectors.append(vector)

        roles_present = [item["instruction_role"] for item in finalized]
        sequence_metadata = {
            "has_introduction": "introduction" in roles_present,
            "has_explanation": "explanation" in roles_present,
            "has_example": "worked_example" in roles_present,
            "has_summary": "summary" in roles_present,
            "has_practice_hint": "practice_hint" in roles_present,
            "has_misconception_fix": "misconception_fix" in roles_present,
            "roles_present": roles_present,
            "missing_roles": [role for role in desired_roles if role not in roles_present],
        }
        return finalized, sequence_metadata

    def _hydrate_resource_metadata(
        self, recommended_chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not recommended_chunks:
            return []
        resource_ids = [
            ObjectId(item["resource_id"])
            for item in recommended_chunks
            if ObjectId.is_valid(item["resource_id"])
        ]
        resources = self.resource_repository.get_many(resource_ids) if resource_ids else []
        resource_map = {str(item["_id"]): item for item in resources}

        hydrated: List[Dict[str, Any]] = []
        for item in recommended_chunks:
            resource = resource_map.get(item["resource_id"], {})
            metadata = resource.get("metadata") or {}
            enriched = dict(item)
            enriched["resource_title"] = str(
                resource.get("title") or item.get("resource_title") or ""
            )
            enriched["resource_source"] = str(
                resource.get("source") or item.get("resource_source") or ""
            )
            enriched["resource_url"] = (
                metadata.get("url") or resource.get("url") or item.get("resource_url")
            )
            hydrated.append(enriched)
        return hydrated

    @staticmethod
    def _stringify_ids(values: Iterable[Any]) -> List[str]:
        return [str(value) for value in values if value is not None]

    def _serialize_recommendation(
        self,
        recommendation: Dict[str, Any],
        recommended_chunks: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        raw_chunks = recommended_chunks or recommendation.get("recommended_chunks") or []
        if not raw_chunks and recommendation.get("chunk_ids"):
            loaded_chunks = self.chunk_repository.get_by_ids(
                [str(item) for item in recommendation.get("chunk_ids", [])]
            )
            raw_chunks = [
                {
                    "chunk_id": str(chunk["_id"]),
                    "resource_id": str(chunk["resource_id"]),
                    "chunk_index": int(chunk.get("chunk_index", 0)),
                    "page_number": self._resolve_page_number(chunk),
                    "score": 0.0,
                    "preview": str(chunk.get("content") or "")[:280],
                    "instruction_role": "explanation",
                    "difficulty": str(
                        (chunk.get("metadata") or {}).get("level") or "beginner"
                    ),
                    "covered_objectives": [],
                    "covered_concepts": [],
                    "estimated_read_time": self._estimate_read_time(
                        str(chunk.get("content") or "")
                    ),
                    "questionability_score": 0.5,
                    "fact_density_score": 0.5,
                    "concept_explicitness_score": 0.5,
                    "example_presence_score": 0.2,
                    "score_breakdown": {},
                    "cluster_id": None,
                    "selected_as_representative": True,
                }
                for chunk in loaded_chunks
            ]

        hydrated_chunks = self._hydrate_resource_metadata(raw_chunks)
        chunk_ids = [item["chunk_id"] for item in hydrated_chunks]
        resource_ids = list(dict.fromkeys(item["resource_id"] for item in hydrated_chunks))
        metadata = recommendation.get("metadata") or {}

        return {
            "recommendation_id": str(recommendation.get("_id") or ""),
            "subject_id": str(recommendation.get("subject_id") or ""),
            "chapter_id": str(recommendation.get("chapter_id") or ""),
            "lesson_id": str(recommendation.get("lesson_id") or ""),
            "chunk_ids": chunk_ids or self._stringify_ids(recommendation.get("chunk_ids", [])),
            "resource_ids": resource_ids
            or self._stringify_ids(recommendation.get("resource_ids", [])),
            "selection_strategy": str(recommendation.get("selection_strategy") or ""),
            "metadata": metadata,
            "sequence_metadata": recommendation.get("sequence_metadata")
            or metadata.get("sequence_metadata")
            or {},
            "recommended_chunks": hydrated_chunks,
            "created_at": recommendation.get("created_at") or datetime.utcnow(),
        }

    def recommend_chunks(
        self,
        *,
        lesson_id: str,
        max_chunks: int = 8,
        selection_strategy: str = "local_semantic_lesson_scope_v1",
        enable_diversity_reranking: bool = True,
        diversity_lambda: float | None = None,
        resource_ids: Sequence[str] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if max_chunks <= 0:
            raise ValueError("max_chunks must be positive.")

        context = self._get_lesson_context(lesson_id)
        query_text = self._build_query_text(context)
        if not query_text:
            raise ValueError("Lesson does not contain enough context for chunk recommendation.")

        try:
            query_vector = self._to_vector(embed_text(query_text))
        except Exception:
            query_vector = None

        weights = self._weights_for_mode((metadata or {}).get("mode"))
        query_terms = self._priority_terms(context)
        candidates = self._candidate_chunks(
            context=context,
            resource_ids=resource_ids,
            max_chunks=max_chunks,
        )
        if not candidates:
            raise ValueError("No candidate chunks available for this lesson.")

        analyzed = [
            self._analyze_candidate(
                chunk=row,
                context=context,
                query_vector=query_vector,
                query_terms=query_terms,
                weights=weights,
            )
            for row in candidates
        ]
        representatives = self._cluster_candidates(analyzed)
        if diversity_lambda is not None:
            self.reranker.config.lambda_relevance = max(
                0.0, min(1.0, float(diversity_lambda))
            )
        reranked_candidates, rerank_metadata = self._rerank_candidates(
            candidates=representatives,
            limit=max_chunks,
            enable_diversity_reranking=enable_diversity_reranking,
        )
        selected, sequence_metadata = self._build_sequence(
            candidates=reranked_candidates,
            max_chunks=max_chunks,
            weights=weights,
        )
        hydrated = self._hydrate_resource_metadata(selected)
        score_map = {
            item["chunk_id"]: round(float(item.get("score", 0.0)), 6) for item in hydrated
        }

        recommendation_doc = self.recommendation_repository.upsert_for_lesson(
            lesson_id,
            {
                "subject_id": context["subject"]["_id"],
                "chapter_id": context["chapter"]["_id"],
                "lesson_id": context["lesson"]["_id"],
                "chunk_ids": [
                    ObjectId(item["chunk_id"])
                    for item in hydrated
                    if ObjectId.is_valid(item["chunk_id"])
                ],
                "resource_ids": [
                    ObjectId(resource_id)
                    for resource_id in dict.fromkeys(item["resource_id"] for item in hydrated)
                    if ObjectId.is_valid(resource_id)
                ],
                "selection_strategy": selection_strategy,
                "metadata": {
                    **(metadata or {}),
                    "query_text": query_text[:600],
                    "candidate_count": len(candidates),
                    "cluster_count": len(representatives),
                    "selected_count": len(hydrated),
                    "scores": score_map,
                    "diversity_reranking": rerank_metadata,
                    "selection_strategy": selection_strategy,
                    "instructional_roles": [item["instruction_role"] for item in hydrated],
                    "chunk_cluster_map": {
                        item["chunk_id"]: item.get("cluster_id") for item in hydrated
                    },
                    "sequence_metadata": sequence_metadata,
                },
                "sequence_metadata": sequence_metadata,
                "recommended_chunks": hydrated,
            },
        )
        return self._serialize_recommendation(recommendation_doc, hydrated)

    def get_recommendation(self, lesson_id: str) -> Dict[str, Any]:
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id)
        if not recommendation:
            raise ValueError("Lesson recommendation not found.")
        return self._serialize_recommendation(recommendation)


lesson_chunk_service = LessonChunkService()
