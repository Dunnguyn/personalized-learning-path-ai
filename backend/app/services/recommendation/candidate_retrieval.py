"""Adaptive resource recommendation service with streamlined scoring."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Dict, List, Sequence

import numpy as np

from backend.app.repositories.chunk_repository import ResourceChunkRepository
from backend.app.repositories.recommendation_repository import RecommendationRepository
from backend.app.services.embedding_service import embed_text, semantic_search
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.learner_profile_service import learner_profile_service
from backend.app.services.lesson_semantic_query_service import (
    lesson_semantic_query_service,
)
from backend.app.services.recommendation.filters import (
    apply_hard_filters as apply_recommendation_hard_filters,
)
from backend.app.services.recommendation.explanations import (
    build_explanation as build_recommendation_explanation,
    build_recommendation_payload as build_recommendation_item_payload,
    persist_explanation_record as persist_recommendation_explanation_record,
)
from backend.app.services.recommendation.reranking import (
    rerank_scored_items as rerank_recommendation_items,
)
from backend.app.services.recommendation.scoring import (
    compute_final_score as compute_recommendation_final_score,
    concept_gap_fit as compute_recommendation_concept_gap_fit,
    expected_learning_gain as compute_recommendation_expected_gain,
    fatigue_penalty as compute_recommendation_fatigue_penalty,
)
from backend.app.services.recommendation_explanation_service import (
    recommendation_explanation_service,
)
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)
from backend.app.services.resource_quality_service import resource_quality_service


@dataclass(frozen=True)
class ResourceRecommendationWeights:
    semantic_match: float = 0.26
    chunk_match_score: float = 0.17
    chunk_coverage_score: float = 0.09
    concept_gap_fit: float = 0.20
    difficulty_fit: float = 0.10
    goal_fit: float = 0.11
    resource_type_fit: float = 0.04
    time_budget_fit: float = 0.03
    quality_score: float = 0.04
    engagement_fit: float = 0.03
    expected_learning_gain: float = 0.08
    fatigue_penalty: float = 0.03


class HybridRecommendationService:
    """Build top-level resource recommendations for multiple adaptive modes."""

    _LEVEL_ORDER = {"beginner": 1, "intermediate": 2, "advanced": 3}
    _MODE_ALIASES = {"quick_review": "continue_learning"}
    _INDEX_LINE_PATTERN = re.compile(
        r"^[^\n]{2,120}?(?:,|\.)?\s+\d{1,4}(?:-\d{1,4})?\s*$"
    )
    _STRUCTURAL_NOISE_HEADINGS = (
        "afterword",
        "appendix",
        "appendices",
        "acknowledgments",
        "acknowledgements",
        "preface",
        "foreword",
        "table of contents",
        "contents",
        "index",
        "glossary",
        "references",
        "bibliography",
    )
    _MODE_OVERRIDES: Dict[str, Dict[str, float]] = {
        "continue_learning": {
            "semantic_match": 0.24,
            "chunk_match_score": 0.19,
            "chunk_coverage_score": 0.10,
            "concept_gap_fit": 0.18,
            "goal_fit": 0.11,
            "engagement_fit": 0.04,
            "expected_learning_gain": 0.08,
            "fatigue_penalty": 0.02,
        },
        "reinforce_weaknesses": {
            "semantic_match": 0.23,
            "chunk_match_score": 0.18,
            "chunk_coverage_score": 0.10,
            "concept_gap_fit": 0.28,
            "difficulty_fit": 0.10,
            "goal_fit": 0.10,
            "engagement_fit": 0.03,
            "expected_learning_gain": 0.10,
            "fatigue_penalty": 0.02,
        },
        "learn_new": {
            "semantic_match": 0.30,
            "chunk_match_score": 0.17,
            "chunk_coverage_score": 0.08,
            "concept_gap_fit": 0.15,
            "difficulty_fit": 0.13,
            "goal_fit": 0.13,
            "quality_score": 0.04,
            "engagement_fit": 0.02,
            "expected_learning_gain": 0.07,
            "fatigue_penalty": 0.02,
        },
    }

    def __init__(self) -> None:
        self.repository = RecommendationRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.reranker = RecommendationRerankingService(
            ReRankingConfig(enabled=True, lambda_relevance=0.76, exploration_weight=0.03)
        )
        self.learner_state_service = learner_state_service
        self.learner_profile_service = learner_profile_service
        self.resource_quality_service = resource_quality_service
        self.explanation_service = recommendation_explanation_service
        self.explanation_collection = self.repository.db["recommendation_explanations"]
        self.explanation_collection.create_index([("user_id", 1), ("resource_key", 1), ("mode", 1)])
        self.chunk_repository.ensure_indexes()

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
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _tokenize(cls, value: str) -> List[str]:
        return [
            token
            for token in re.findall(r"\w+", cls._normalize_text(value))
            if len(token) >= 3
        ]

    @classmethod
    def _dedupe_terms(cls, values: Sequence[str], *, limit: int | None = None) -> List[str]:
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

    @staticmethod
    def _goal_tokens(goal: str) -> List[str]:
        return [
            token.lower()
            for token in __import__("re").findall(r"\w+", goal or "")
            if len(token) >= 3
            and token.lower()
            not in {
                "hoc",
                "học",
                "mot",
                "một",
                "ngon",
                "ngôn",
                "ngu",
                "ngữ",
                "moi",
                "mới",
                "learn",
                "study",
                "course",
                "lesson",
                "basic",
                "basics",
            }
        ]

    @staticmethod
    def _cosine(left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator <= 0:
            return 0.0
        return HybridRecommendationService._clamp(float(np.dot(left, right) / denominator))

    def _normalize_mode(self, mode: str | None) -> str:
        normalized = str(mode or "continue_learning").strip().lower()
        normalized = self._MODE_ALIASES.get(normalized, normalized)
        if normalized not in {"continue_learning", "reinforce_weaknesses", "learn_new"}:
            return "continue_learning"
        return normalized

    def _weights_for_mode(self, mode: str) -> ResourceRecommendationWeights:
        weights = ResourceRecommendationWeights()
        overrides = self._MODE_OVERRIDES.get(mode, {})
        for field, value in overrides.items():
            weights = replace(weights, **{field: value})
        return weights

    def _semantic_match(self, goal_vector: np.ndarray | None, resource: Dict[str, Any]) -> float:
        vector = resource.get("embedding")
        if goal_vector is None or not vector:
            return 0.0
        try:
            return self._cosine(goal_vector, np.array(vector, dtype=float))
        except Exception:
            return 0.0

    def _goal_fit(self, goal_tokens: Sequence[str], resource: Dict[str, Any]) -> float:
        if not goal_tokens:
            return 0.0
        text = " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str((resource.get("metadata") or {}).get("summary") or ""),
            ]
        ).lower()
        matched = sum(1 for token in goal_tokens if token in text)
        return self._clamp(matched / max(len(goal_tokens), 1))

    @classmethod
    def _lexical_overlap_score(cls, terms: Sequence[str], text: str) -> float:
        normalized_terms = cls._dedupe_terms(terms)
        if not normalized_terms:
            return 0.0
        tokens = set(cls._tokenize(text))
        if not tokens:
            return 0.0
        hits = 0
        for term in normalized_terms:
            if term in tokens:
                hits += 1
        return cls._clamp(hits / max(min(len(normalized_terms), 6), 1))

    @classmethod
    def _phrase_hit_score(cls, phrases: Sequence[str], text: str) -> tuple[float, List[str]]:
        normalized_text = cls._normalize_text(text)
        matched: List[str] = []
        for phrase in cls._dedupe_terms(phrases):
            if not phrase or len(phrase) < 3:
                continue
            if phrase in normalized_text:
                matched.append(phrase)
        denominator = max(min(len(cls._dedupe_terms(phrases)), 5), 1)
        return cls._clamp(len(matched) / denominator), matched[:6]

    @classmethod
    def _chunk_heading_text(cls, chunk: Dict[str, Any]) -> str:
        metadata = chunk.get("metadata") or {}
        parts = [
            str(metadata.get("source_title") or ""),
            str(metadata.get("title") or ""),
            str(metadata.get("heading") or ""),
            str(metadata.get("section_title") or ""),
            str(metadata.get("chapter_title") or ""),
            str(metadata.get("chunk_summary") or ""),
            " ".join(str(item) for item in metadata.get("chunk_keywords", []) or []),
        ]
        return " ".join(part for part in parts if part).strip()

    @classmethod
    def _chunk_noise_penalty(cls, chunk: Dict[str, Any]) -> float:
        content = str(chunk.get("content") or "")
        metadata = chunk.get("metadata") or {}
        heading_text = cls._normalize_text(cls._chunk_heading_text(chunk))
        normalized_content = cls._normalize_text(content)
        if not normalized_content:
            return 1.0

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        index_like_lines = sum(1 for line in lines if cls._INDEX_LINE_PATTERN.match(line))
        short_lines = sum(1 for line in lines if len(line) <= 80)
        numeric_refs = len(re.findall(r"\b\d{1,4}(?:-\d{1,4})?\b", content))
        sentence_hits = len(re.findall(r"(?<=[.!?])\s+", content))

        noise = 0.0
        if str(metadata.get("content_kind") or "").strip().lower() == "structural":
            noise += 0.5
        if any(heading_text.startswith(item) for item in cls._STRUCTURAL_NOISE_HEADINGS):
            noise += 0.45
        if any(item in normalized_content for item in ("table of contents", "glossary", "bibliography")):
            noise += 0.30
        if lines:
            noise += 0.25 * cls._clamp(index_like_lines / max(min(len(lines), 6), 1) * 2.0)
            noise += 0.10 * cls._clamp(short_lines / len(lines))
        noise += 0.10 * cls._clamp(numeric_refs / max(len(lines), 1) / 2.0)
        if sentence_hits >= 2:
            noise -= 0.12
        if len(cls._tokenize(content)) <= 18:
            noise += 0.10
        return cls._clamp(noise)

    def _difficulty_fit(self, learner_level: str, resource_level: str) -> float:
        learner_rank = self._LEVEL_ORDER.get(str(learner_level).lower(), 1)
        resource_rank = self._LEVEL_ORDER.get(str(resource_level).lower(), learner_rank)
        distance = abs(learner_rank - resource_rank)
        if distance == 0:
            return 1.0
        if distance == 1:
            return 0.68
        return 0.32

    def _engagement_fit(self, quality: Dict[str, Any]) -> float:
        engagement = self._safe_float(quality.get("engagement_rate"), 0.45)
        completion = self._safe_float(quality.get("avg_completion_rate"), 0.4)
        helpfulness = self._safe_float(quality.get("avg_helpfulness"), 0.6)
        return self._clamp(0.45 * engagement + 0.35 * completion + 0.20 * helpfulness)

    def _resource_type_fit(
        self, preferred_resource_type: str, resource: Dict[str, Any]
    ) -> float:
        preferred = str(preferred_resource_type or "mixed").strip().lower()
        if preferred == "mixed":
            return 1.0

        resource_type = str(resource.get("type") or "").strip().lower()
        source = str(resource.get("source") or "").strip().lower()
        pedagogy = str((resource.get("metadata") or {}).get("pedagogy_type") or "").strip().lower()
        title = str(resource.get("title") or "").strip().lower()

        if preferred == "video":
            return 1.0 if resource_type in {"youtube", "video"} or source == "youtube" or pedagogy == "video" else 0.42
        if preferred == "pdf":
            return 1.0 if resource_type == "pdf" or source == "pdf" else 0.4
        if preferred == "practice":
            practice_match = resource_type in {"quiz", "practice"} or pedagogy == "quiz" or any(
                token in title for token in ("practice", "exercise", "quiz")
            )
            return 1.0 if practice_match else 0.35
        return 0.7

    def _time_budget_fit(self, time_budget_minutes: int, estimated_time: int) -> float:
        if time_budget_minutes <= 0 or estimated_time <= 0:
            return 1.0
        recommended_session = max(15, min(int(round(time_budget_minutes / 5.0)), 90))
        if estimated_time <= recommended_session:
            return 1.0
        overflow_ratio = (estimated_time - recommended_session) / max(
            recommended_session, 1
        )
        return self._clamp(1.0 - (overflow_ratio * 0.5), minimum=0.25, maximum=1.0)

    def _concept_gap_fit(
        self,
        *,
        mastery: float,
        confidence: float,
        focus_concepts: Sequence[str],
        resource: Dict[str, Any],
    ) -> float:
        topic = str(resource.get("topic") or "").lower()
        metadata = resource.get("metadata") or {}
        concepts = metadata.get("primary_concepts") or metadata.get("covered_concepts") or []
        concept_text = " ".join([topic, *(str(item).lower() for item in concepts if item)])
        focus_bonus = 0.0
        if any(str(concept).lower() in concept_text for concept in focus_concepts):
            focus_bonus = 0.18
        gap = 1.0 - ((mastery + confidence) / 2.0)
        return self._clamp(0.82 * gap + focus_bonus)

    def _expected_learning_gain(
        self,
        *,
        quality: Dict[str, Any],
        concept_gap_fit: float,
    ) -> float:
        assessment_uplift = self._safe_float(quality.get("assessment_uplift_rate"), 0.0)
        avg_completion_rate = self._safe_float(quality.get("avg_completion_rate"), 0.0)
        clarity_readability = self._safe_float(quality.get("clarity_readability"), 0.0)
        if assessment_uplift > 0:
            return self._clamp(
                0.4 * concept_gap_fit
                + 0.3 * assessment_uplift
                + 0.2 * avg_completion_rate
                + 0.1 * clarity_readability
            )
        quality_score = self._safe_float(quality.get("quality_score"), 0.0)
        engagement_fit = self._engagement_fit(quality)
        return self._clamp(
            0.5 * concept_gap_fit + 0.3 * quality_score + 0.2 * engagement_fit
        )

    def _fatigue_penalty(
        self,
        *,
        learner_state: Dict[str, Any],
        explanation_time: int,
    ) -> float:
        avg_session = max(self._safe_float(learner_state.get("avg_session_duration"), 15.0), 1.0)
        unfinished = self._safe_float(learner_state.get("unfinished_resources"), 0.0)
        learning_velocity = self._safe_float(learner_state.get("learning_velocity"), 0.5)
        time_ratio = self._clamp(explanation_time / max(avg_session, 1.0) / 2.0)
        unfinished_pressure = self._clamp(unfinished / 6.0)
        low_velocity_pressure = self._clamp((0.6 - learning_velocity) / 0.6)
        return self._clamp(
            0.45 * time_ratio + 0.35 * unfinished_pressure + 0.20 * low_velocity_pressure
        )

    def _compute_final_score(
        self,
        *,
        components: Dict[str, float],
        weights: ResourceRecommendationWeights,
    ) -> float:
        score = (
            weights.semantic_match * components["semantic_match"]
            + weights.chunk_match_score * components["chunk_match_score"]
            + weights.chunk_coverage_score * components["chunk_coverage_score"]
            + weights.concept_gap_fit * components["concept_gap_fit"]
            + weights.difficulty_fit * components["difficulty_fit"]
            + weights.goal_fit * components["goal_fit"]
            + weights.resource_type_fit * components["resource_type_fit"]
            + weights.time_budget_fit * components["time_budget_fit"]
            + weights.quality_score * components["quality_score"]
            + weights.engagement_fit * components["engagement_fit"]
            + weights.expected_learning_gain * components["expected_learning_gain"]
            - weights.fatigue_penalty * components["fatigue_penalty"]
        )
        return self._clamp(score)

    @staticmethod
    def _resource_chunk_lookup_key(resource: Dict[str, Any]) -> str:
        identifier = resource.get("_id")
        if identifier is not None:
            return str(identifier)
        return str(resource.get("resource_id") or "")

    def _resource_query_phrases(
        self,
        *,
        goal: str,
        lesson_context: Dict[str, Any] | None,
        focus_concepts: Sequence[str],
    ) -> Dict[str, List[str]]:
        lesson_context = lesson_context or {}
        lesson_payload = lesson_semantic_query_service.build_query_payload(
            title=str(lesson_context.get("title") or ""),
            summary=str(lesson_context.get("summary") or ""),
            objectives=[
                str(item)
                for item in lesson_context.get("learning_objectives", [])
                if item
            ],
            keywords=[
                str(item) for item in lesson_context.get("keywords", []) if item
            ],
            subject_topic=str(lesson_context.get("topic") or ""),
            goal=str(goal or ""),
            extra_terms=[str(item) for item in focus_concepts if item],
        )
        lesson_terms = self._dedupe_terms(
            [
                *lesson_payload.get("english_terms", []),
                str(lesson_context.get("topic") or ""),
                str(lesson_context.get("title") or ""),
                *[str(item) for item in lesson_context.get("keywords", []) if item],
                *[
                    str(item)
                    for item in lesson_context.get("learning_objectives", [])
                    if item
                ],
            ],
            limit=14,
        )
        focus_terms = self._dedupe_terms(
            [
                *[str(item) for item in focus_concepts if item],
                *lesson_payload.get("english_terms", []),
            ],
            limit=10,
        )
        goal_terms = self._dedupe_terms(
            [
                *lesson_payload.get("english_terms", []),
                *self._goal_tokens(goal),
            ],
            limit=14,
        )
        anchor_phrases = self._dedupe_terms(
            [
                *lesson_terms,
                *focus_terms,
                *lesson_payload.get("vietnamese_terms", []),
                *[
                    phrase
                    for phrase in re.split(r",|;|\n", str(goal or ""))
                    if len(self._tokenize(phrase)) >= 2
                ],
            ],
            limit=14,
        )
        return {
            "goal_terms": goal_terms,
            "lesson_terms": lesson_terms,
            "focus_terms": focus_terms,
            "anchor_phrases": anchor_phrases,
        }

    def _analyze_resource_chunks(
        self,
        *,
        resource: Dict[str, Any],
        chunks: Sequence[Dict[str, Any]],
        query_vector: np.ndarray | None,
        goal_terms: Sequence[str],
        lesson_terms: Sequence[str],
        focus_terms: Sequence[str],
        anchor_phrases: Sequence[str],
    ) -> Dict[str, Any]:
        if not chunks:
            return {
                "chunk_match_score": 0.0,
                "chunk_coverage_score": 0.0,
                "matched_chunk_preview": "",
                "matched_chunk_terms": [],
                "supporting_chunk_count": 0,
                "top_chunk_scores": [],
            }

        desired_terms = self._dedupe_terms(
            [*goal_terms, *lesson_terms, *focus_terms],
            limit=8,
        )
        analyzed_chunks: List[Dict[str, Any]] = []
        for chunk in chunks:
            content = str(chunk.get("content") or "")
            heading = self._chunk_heading_text(chunk)
            metadata = chunk.get("metadata") or {}
            keyword_text = " ".join(str(item) for item in metadata.get("chunk_keywords", []) or [])
            searchable_text = f"{heading} {keyword_text} {content}".strip()
            try:
                chunk_vector = np.array(chunk.get("embedding") or [], dtype=float)
            except Exception:
                chunk_vector = np.array([], dtype=float)
            semantic_score = (
                self._cosine(query_vector, chunk_vector)
                if query_vector is not None and chunk_vector.size > 0
                else 0.0
            )
            goal_overlap = self._lexical_overlap_score(goal_terms, searchable_text)
            lesson_overlap = self._lexical_overlap_score(lesson_terms, searchable_text)
            focus_overlap = self._lexical_overlap_score(focus_terms, searchable_text)
            anchor_score, matched_phrases = self._phrase_hit_score(anchor_phrases, searchable_text)
            noise_penalty = self._chunk_noise_penalty(chunk)
            metadata_questionability = self._safe_float(
                metadata.get("questionability_score"), 0.0
            )
            instruction_role = str(metadata.get("instruction_role") or "").strip().lower()
            role_bonus = 0.0
            if instruction_role in {"definition", "explanation", "worked_example"}:
                role_bonus = 0.04

            chunk_score = self._clamp(
                0.42 * semantic_score
                + 0.18 * goal_overlap
                + 0.18 * lesson_overlap
                + 0.12 * focus_overlap
                + 0.10 * anchor_score
                + 0.08 * metadata_questionability
                + role_bonus
                - 0.30 * noise_penalty
            )
            preview = re.sub(r"\s+", " ", content).strip()[:220]
            matched_terms = self._dedupe_terms(
                [
                    *[
                        term
                        for term in desired_terms
                        if term in self._normalize_text(searchable_text)
                    ],
                    *matched_phrases,
                ],
                limit=8,
            )
            analyzed_chunks.append(
                {
                    "score": round(chunk_score, 6),
                    "semantic_score": round(semantic_score, 6),
                    "goal_overlap": round(goal_overlap, 6),
                    "lesson_overlap": round(lesson_overlap, 6),
                    "focus_overlap": round(focus_overlap, 6),
                    "anchor_score": round(anchor_score, 6),
                    "noise_penalty": round(noise_penalty, 6),
                    "matched_terms": matched_terms,
                    "preview": preview,
                }
            )

        analyzed_chunks.sort(key=lambda item: item["score"], reverse=True)
        top_chunks = analyzed_chunks[:3]
        best_score = float(top_chunks[0]["score"])
        avg_top_two = sum(float(item["score"]) for item in top_chunks[:2]) / max(
            min(len(top_chunks), 2), 1
        )
        supporting_chunk_count = sum(1 for item in analyzed_chunks if item["score"] >= 0.48)
        covered_terms = self._dedupe_terms(
            [term for item in top_chunks for term in item.get("matched_terms", [])],
            limit=8,
        )
        coverage_score = self._clamp(
            len(covered_terms) / max(min(len(desired_terms), 5), 1)
        )
        chunk_match_score = self._clamp(
            0.60 * best_score
            + 0.25 * avg_top_two
            + 0.15 * self._clamp(supporting_chunk_count / 3.0)
        )
        return {
            "chunk_match_score": round(chunk_match_score, 6),
            "chunk_coverage_score": round(coverage_score, 6),
            "matched_chunk_preview": str(top_chunks[0].get("preview") or ""),
            "matched_chunk_terms": covered_terms[:6],
            "supporting_chunk_count": supporting_chunk_count,
            "top_chunk_scores": [round(float(item["score"]), 6) for item in top_chunks],
        }

    def _build_chunk_signal_map(
        self,
        *,
        resources: Sequence[Dict[str, Any]],
        query_vector: np.ndarray | None,
        goal: str,
        lesson_context: Dict[str, Any] | None,
        focus_concepts: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        lookup_ids = [
            resource.get("_id")
            for resource in resources
            if resource.get("_id") is not None
        ]
        chunks = self.chunk_repository.get_by_resource_ids(lookup_ids) if lookup_ids else []
        grouped_chunks: Dict[str, List[Dict[str, Any]]] = {}
        for chunk in chunks:
            grouped_chunks.setdefault(str(chunk.get("resource_id")), []).append(chunk)

        query_terms = self._resource_query_phrases(
            goal=goal,
            lesson_context=lesson_context,
            focus_concepts=focus_concepts,
        )
        payload: Dict[str, Dict[str, Any]] = {}
        for resource in resources:
            key = self.repository.get_resource_key(resource)
            chunk_lookup_key = self._resource_chunk_lookup_key(resource)
            payload[key] = self._analyze_resource_chunks(
                resource=resource,
                chunks=grouped_chunks.get(chunk_lookup_key, []),
                query_vector=query_vector,
                goal_terms=query_terms["goal_terms"],
                lesson_terms=query_terms["lesson_terms"],
                focus_terms=query_terms["focus_terms"],
                anchor_phrases=query_terms["anchor_phrases"],
            )
        return payload

    def _select_candidate_concept_ids(
        self,
        *,
        mode: str,
        goal_concepts: List[Dict[str, Any]],
        completed_concepts: Sequence[int],
        mastery_map: Dict[int, float],
        confidence_map: Dict[int, float],
    ) -> List[int]:
        completed_set = set(int(item) for item in completed_concepts)
        if mode == "learn_new":
            ordered = [
                int(item["concept_id"])
                for item in goal_concepts
                if int(item["concept_id"]) not in completed_set
                and mastery_map.get(int(item["concept_id"]), 0.0) <= 0.25
            ]
        elif mode == "reinforce_weaknesses":
            ordered = [
                int(item["concept_id"])
                for item in sorted(
                    goal_concepts,
                    key=lambda item: (
                        mastery_map.get(int(item["concept_id"]), 0.0),
                        confidence_map.get(int(item["concept_id"]), 0.0),
                    ),
                )
            ]
        else:
            ordered = [
                int(item["concept_id"])
                for item in goal_concepts
                if int(item["concept_id"]) not in completed_set
            ]
        fallback = [int(item["concept_id"]) for item in goal_concepts]
        unique: List[int] = []
        for concept_id in ordered + fallback:
            if concept_id not in unique:
                unique.append(concept_id)
        return unique[:10]

    def _resolve_goal_concepts(
        self,
        *,
        goal: str,
        limit: int = 60,
    ) -> List[Dict[str, Any]]:
        goal_concepts = self.repository.find_goal_concepts(goal=goal, limit=limit)
        if goal_concepts:
            return goal_concepts
        return self.repository.list_default_concepts(limit=min(limit, 20))

    def _resolve_candidate_resources(
        self,
        *,
        goal: str,
        candidate_concept_ids: Sequence[int],
        lesson_context: Dict[str, Any] | None,
        preferred_levels: Sequence[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        seen_ids: set[str] = set()
        ordered_resources: List[Dict[str, Any]] = []
        lesson_resource_ids = [
            str(item)
            for item in (lesson_context or {}).get("resource_ids", [])
            if str(item).strip()
        ]

        hybrid_hits = semantic_search(
            query=goal,
            k=max(limit, 8),
            topic=str((lesson_context or {}).get("topic") or "") or None,
            level=list(preferred_levels)[0] if preferred_levels else None,
            min_score=0.22,
        )
        hybrid_resource_ids = [
            str(item.get("resource_id"))
            for item in hybrid_hits
            if str(item.get("resource_id") or "").strip()
        ]
        if hybrid_resource_ids:
            hybrid_resources = self.repository.find_resources_by_ids(
                resource_ids=hybrid_resource_ids,
                preferred_levels=list(preferred_levels),
                limit=max(limit, len(hybrid_resource_ids)),
            )
            for resource in hybrid_resources:
                key = str(resource.get("_id"))
                if key and key not in seen_ids:
                    ordered_resources.append(resource)
                    seen_ids.add(key)

        if lesson_resource_ids:
            lesson_resources = self.repository.find_resources_by_ids(
                resource_ids=lesson_resource_ids,
                preferred_levels=list(preferred_levels),
                limit=max(limit, len(lesson_resource_ids)),
            )
            for resource in lesson_resources:
                key = str(resource.get("_id"))
                if key and key not in seen_ids:
                    ordered_resources.append(resource)
                    seen_ids.add(key)

        resources = self.repository.find_resources_for_concepts(
            concept_ids=list(candidate_concept_ids),
            preferred_levels=list(preferred_levels),
            limit=limit,
        )
        for resource in resources:
            key = str(resource.get("_id"))
            if key and key not in seen_ids:
                ordered_resources.append(resource)
                seen_ids.add(key)

        goal_resources = self.repository.find_resources_for_goal(
            goal=goal,
            preferred_levels=list(preferred_levels),
            limit=limit,
        )
        for resource in goal_resources:
            key = str(resource.get("_id"))
            if key and key not in seen_ids:
                ordered_resources.append(resource)
                seen_ids.add(key)
            if len(ordered_resources) >= limit:
                break
        return ordered_resources[:limit]

    def _level_distance(self, learner_level: str, resource_level: str) -> int:
        learner_rank = self._LEVEL_ORDER.get(str(learner_level).lower(), 1)
        resource_rank = self._LEVEL_ORDER.get(str(resource_level).lower(), learner_rank)
        return abs(learner_rank - resource_rank)

    @staticmethod
    def _resource_text(resource: Dict[str, Any]) -> str:
        metadata = resource.get("metadata") or {}
        concepts = metadata.get("primary_concepts") or metadata.get("covered_concepts") or []
        chunk_profile = metadata.get("chunk_profile") or {}
        return " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str(metadata.get("summary") or ""),
                " ".join(str(item) for item in concepts if item),
                " ".join(str(item) for item in chunk_profile.get("top_keywords", []) if item),
            ]
        ).lower()

    def _matches_any_term(self, resource: Dict[str, Any], terms: Sequence[str]) -> bool:
        normalized_terms = [str(term).strip().lower() for term in terms if str(term).strip()]
        if not normalized_terms:
            return False
        text = self._resource_text(resource)
        return any(term in text for term in normalized_terms)

    def _build_relevance_query(
        self,
        *,
        goal: str,
        learner_state: Dict[str, Any],
        lesson_context: Dict[str, Any] | None,
        profile_context: Dict[str, Any] | None = None,
    ) -> str:
        lesson_context = lesson_context or {}
        profile_context = profile_context or {}
        payload = lesson_semantic_query_service.build_query_payload(
            title=str(lesson_context.get("title") or ""),
            summary=str(lesson_context.get("summary") or ""),
            objectives=[
                str(item)
                for item in lesson_context.get("learning_objectives", [])
                if item
            ],
            keywords=[
                str(item) for item in lesson_context.get("keywords", []) if item
            ],
            subject_topic=str(lesson_context.get("topic") or ""),
            goal=str(goal or ""),
            extra_terms=[
                str(item)
                for item in learner_state.get("current_focus_concepts", [])
                if item
            ],
        )
        parts = [
            payload.get("bilingual_query") or "",
            payload.get("english_query") or "",
            str(goal or ""),
            str(profile_context.get("target_role") or ""),
            str(profile_context.get("target_outcome") or ""),
            " ".join(
                str(item)
                for item in learner_state.get("current_focus_concepts", [])
                if item
            ),
            " ".join(
                str(item)
                for item in (profile_context.get("diagnostic_scores") or {}).keys()
                if item
            ),
        ]
        return " ".join(part for part in parts if part).strip()

    def _apply_hard_filters(
        self,
        *,
        resources: Sequence[Dict[str, Any]],
        user_id: str | int,
        mode: str,
        learner_level: str,
        lesson_context: Dict[str, Any] | None,
        focus_concepts: Sequence[str],
        query_tokens: Sequence[str],
        chunk_signal_map: Dict[str, Dict[str, Any]] | None,
        limit: int,
    ) -> List[Dict[str, Any]]:
        completed_resource_ids = set(self.repository.get_recently_completed_resources(user_id))
        recently_seen_resource_ids = set(self.repository.get_recently_seen_resources(user_id, limit=40))
        lesson_context = lesson_context or {}
        lesson_resource_ids = {
            str(item) for item in lesson_context.get("resource_ids", []) if str(item).strip()
        }
        unfinished_lesson_resource_ids = lesson_resource_ids.intersection(
            recently_seen_resource_ids - completed_resource_ids
        )
        lesson_terms = [
            str(lesson_context.get("topic") or "").lower(),
            *[str(item).lower() for item in lesson_context.get("keywords", []) if item],
            *[
                str(item).lower()
                for item in lesson_context.get("learning_objectives", [])
                if item
            ],
        ]
        focus_terms = [str(item).lower() for item in focus_concepts if str(item).strip()]

        base: List[Dict[str, Any]] = []
        for resource in resources:
            resource_key = self.repository.get_resource_key(resource)
            if resource_key in completed_resource_ids:
                continue
            if self._level_distance(learner_level, str(resource.get("level") or learner_level)) > 1:
                continue
            base.append(resource)

        if not base:
            base = [
                resource
                for resource in resources
                if self.repository.get_resource_key(resource) not in completed_resource_ids
            ]

        strict: List[Dict[str, Any]] = []
        for resource in base:
            resource_key = self.repository.get_resource_key(resource)
            lesson_match = bool(lesson_resource_ids and resource_key in lesson_resource_ids)
            focus_match = self._matches_any_term(resource, focus_terms)
            context_match = self._matches_any_term(resource, lesson_terms)
            chunk_signal = (chunk_signal_map or {}).get(resource_key, {})
            chunk_match = self._safe_float(chunk_signal.get("chunk_match_score"), 0.0)
            chunk_coverage = self._safe_float(
                chunk_signal.get("chunk_coverage_score"), 0.0
            )

            if mode == "reinforce_weaknesses" and focus_terms and not (
                focus_match or lesson_match or chunk_match >= 0.52 or chunk_coverage >= 0.22
            ):
                continue
            if mode == "continue_learning" and lesson_resource_ids and not (
                lesson_match or context_match or chunk_match >= 0.5 or chunk_coverage >= 0.2
            ):
                continue
            strict.append(resource)

        filtered = strict if len(strict) >= max(limit, 3) else base
        return sorted(
            filtered,
            key=lambda resource: (
                self.repository.get_resource_key(resource) in unfinished_lesson_resource_ids,
                self.repository.get_resource_key(resource) in lesson_resource_ids,
                self._safe_float(
                    (chunk_signal_map or {})
                    .get(self.repository.get_resource_key(resource), {})
                    .get("chunk_match_score"),
                    0.0,
                ),
                self._safe_float(
                    (chunk_signal_map or {})
                    .get(self.repository.get_resource_key(resource), {})
                    .get("chunk_coverage_score"),
                    0.0,
                ),
                self._matches_any_term(resource, focus_terms),
                self._matches_any_term(resource, lesson_terms),
                self._matches_any_term(resource, query_tokens),
            ),
            reverse=True,
        )

    def recommend_resources(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
        mode: str = "continue_learning",
    ) -> Dict[str, Any]:
        mode = self._normalize_mode(mode)
        learner_state = self.learner_state_service.build_state(user_id)
        lesson_context = self.repository.get_recent_lesson_context(user_id)
        profile_context = self.learner_profile_service.personalization_context(
            user_id=str(user_id),
            goal=goal,
            level=level,
        )
        goal = str(profile_context.get("goal") or goal or "").strip()
        level = str(profile_context.get("level") or level or "beginner").strip().lower()
        progress_rows = self.repository.get_user_progress(user_id)
        mastery_map = {
            int(item.get("concept_id", 0)): self._safe_float(item.get("mastery"), 0.0)
            for item in progress_rows
        }
        confidence_map = {
            int(item.get("concept_id", 0)): self._safe_float(item.get("confidence"), 0.0)
            for item in progress_rows
        }

        relevance_query = self._build_relevance_query(
            goal=goal,
            learner_state=learner_state,
            lesson_context=lesson_context,
            profile_context=profile_context,
        )
        goal_concepts = self._resolve_goal_concepts(
            goal=relevance_query or goal,
            limit=60,
        )
        completed = [
            int(item["concept_id"])
            for item in goal_concepts
            if mastery_map.get(int(item["concept_id"]), 0.0) >= 0.8
        ]

        candidate_concept_ids = self._select_candidate_concept_ids(
            mode=mode,
            goal_concepts=goal_concepts,
            completed_concepts=completed,
            mastery_map=mastery_map,
            confidence_map=confidence_map,
        )
        fallback_level = {
            "beginner": "intermediate",
            "intermediate": "advanced",
            "advanced": "advanced",
        }
        preferred_levels = [level, fallback_level.get(level, level)]
        resources = self._resolve_candidate_resources(
            goal=relevance_query or goal,
            candidate_concept_ids=candidate_concept_ids,
            lesson_context=lesson_context,
            preferred_levels=preferred_levels,
            limit=max(limit * 5, 25),
        )
        if not resources:
            progress_percentage = (len(completed) / len(goal_concepts) * 100.0) if goal_concepts else 0.0
            return {
                "recommended": [],
                "completed_concepts": len(completed),
                "total_concepts": len(goal_concepts),
                "progress_percentage": round(progress_percentage, 2),
                "reranking": {"strategy": "none", "diversity_ratio": 0.0},
                "learner_state": learner_state,
                "recommendation_mode": mode,
                "query_debug": {
                    "relevance_query": relevance_query,
                    "lesson_query_payload": lesson_semantic_query_service.build_query_payload(
                        title=str((lesson_context or {}).get("title") or ""),
                        summary=str((lesson_context or {}).get("summary") or ""),
                        objectives=[
                            str(item)
                            for item in (lesson_context or {}).get(
                                "learning_objectives", []
                            )
                            if item
                        ],
                        keywords=[
                            str(item)
                            for item in (lesson_context or {}).get("keywords", [])
                            if item
                        ],
                        subject_topic=str((lesson_context or {}).get("topic") or ""),
                        goal=str(goal or ""),
                        extra_terms=[
                            str(item)
                            for item in learner_state.get(
                                "current_focus_concepts", []
                            )
                            if item
                        ],
                    ),
                },
            }

        try:
            goal_vector = np.array(embed_text(relevance_query or goal), dtype=float)
        except Exception:
            goal_vector = None
        goal_tokens = self._goal_tokens(relevance_query or goal)
        focus_concepts = [str(item).lower() for item in learner_state.get("current_focus_concepts", [])]
        preferred_resource_type = str(
            profile_context.get("preferred_resource_type") or "mixed"
        )
        time_budget_minutes = int(profile_context.get("time_budget_minutes") or 0)
        lesson_query_payload = lesson_semantic_query_service.build_query_payload(
            title=str((lesson_context or {}).get("title") or ""),
            summary=str((lesson_context or {}).get("summary") or ""),
            objectives=[
                str(item)
                for item in (lesson_context or {}).get("learning_objectives", [])
                if item
            ],
            keywords=[
                str(item) for item in (lesson_context or {}).get("keywords", []) if item
            ],
            subject_topic=str((lesson_context or {}).get("topic") or ""),
            goal=str(goal or ""),
            extra_terms=[str(item) for item in focus_concepts if item],
        )
        chunk_signal_map = self._build_chunk_signal_map(
            resources=resources,
            query_vector=goal_vector,
            goal=relevance_query or goal,
            lesson_context=lesson_context,
            focus_concepts=focus_concepts,
        )
        resources = self._apply_hard_filters(
            resources=resources,
            user_id=user_id,
            mode=mode,
            learner_level=level,
            lesson_context=lesson_context,
            focus_concepts=focus_concepts,
            query_tokens=goal_tokens,
            chunk_signal_map=chunk_signal_map,
            limit=limit,
        )
        weights = self._weights_for_mode(mode)

        scored_items: List[Dict[str, Any]] = []
        for resource in resources:
            resource_key = self.repository.get_resource_key(resource)
            metadata = resource.get("metadata") or {}
            concept_id = int(resource.get("concept_id") or metadata.get("concept_id") or 0)
            mastery = mastery_map.get(concept_id, 0.0)
            confidence = confidence_map.get(concept_id, 0.0)
            quality = self.resource_quality_service.get_resource_quality(resource)
            chunk_signal = chunk_signal_map.get(resource_key, {})

            concept_gap_fit = self._concept_gap_fit(
                mastery=mastery,
                confidence=confidence,
                focus_concepts=focus_concepts,
                resource=resource,
            )
            expected_learning_gain = self._expected_learning_gain(
                quality=quality,
                concept_gap_fit=concept_gap_fit,
            )
            preview_explanation = self._build_explanation(
                resource=resource,
                mode=mode,
                learner_state=learner_state,
                goal=goal,
                level=level,
                quality_score=self._safe_float(quality.get("quality_score"), 0.0),
                expected_learning_gain=expected_learning_gain,
                concept_gap_fit=concept_gap_fit,
                difficulty_fit=self._difficulty_fit(level, str(resource.get("level") or level)),
                lesson_context=lesson_context,
                chunk_match_score=self._safe_float(chunk_signal.get("chunk_match_score"), 0.0),
                matched_chunk_terms=chunk_signal.get("matched_chunk_terms") or [],
            )
            fatigue_penalty = self._fatigue_penalty(
                learner_state=learner_state,
                explanation_time=int(preview_explanation.get("estimated_time") or 12),
            )

            components = {
                "semantic_match": round(self._semantic_match(goal_vector, resource), 6),
                "chunk_match_score": round(
                    self._safe_float(chunk_signal.get("chunk_match_score"), 0.0), 6
                ),
                "chunk_coverage_score": round(
                    self._safe_float(chunk_signal.get("chunk_coverage_score"), 0.0), 6
                ),
                "concept_gap_fit": round(concept_gap_fit, 6),
                "difficulty_fit": round(
                    self._difficulty_fit(level, str(resource.get("level") or level)),
                    6,
                ),
                "goal_fit": round(self._goal_fit(goal_tokens, resource), 6),
                "resource_type_fit": round(
                    self._resource_type_fit(preferred_resource_type, resource), 6
                ),
                "time_budget_fit": round(
                    self._time_budget_fit(
                        time_budget_minutes,
                        int(preview_explanation.get("estimated_time") or 12),
                    ),
                    6,
                ),
                "quality_score": round(self._safe_float(quality.get("quality_score"), 0.0), 6),
                "engagement_fit": round(self._engagement_fit(quality), 6),
                "expected_learning_gain": round(expected_learning_gain, 6),
                "fatigue_penalty": round(fatigue_penalty, 6),
            }
            final_score = self._compute_final_score(components=components, weights=weights)

            scored_items.append(
                {
                    "resource": resource,
                    "resource_key": resource_key,
                    "components": components,
                    "quality": quality,
                    "final_base_score": round(final_score, 6),
                    "source": resource.get("source"),
                    "type": resource.get("type"),
                    "topic": resource.get("topic"),
                    "level": resource.get("level"),
                    "embedding": resource.get("embedding"),
                    "chunk_signal": chunk_signal,
                }
            )

        scored_items.sort(key=lambda item: item["final_base_score"], reverse=True)
        reranking_result = self._rerank_scored_items(
            scored_items=scored_items,
            limit=limit,
            enable_reranking=enable_reranking,
        )

        recommended: List[Dict[str, Any]] = []
        for rank, item in enumerate(reranking_result.get("items", []), start=1):
            resource = item["resource"]
            quality = item["quality"]
            components = dict(item["components"])
            final_score = self._safe_float(item.get("rerank_score"), item.get("final_base_score", 0.0))
            explanation = self._build_explanation(
                resource=resource,
                mode=mode,
                learner_state=learner_state,
                goal=goal,
                level=level,
                quality_score=self._safe_float(quality.get("quality_score"), 0.0),
                expected_learning_gain=self._safe_float(components.get("expected_learning_gain"), 0.0),
                concept_gap_fit=self._safe_float(components.get("concept_gap_fit"), 0.0),
                difficulty_fit=self._safe_float(components.get("difficulty_fit"), 0.0),
                lesson_context=lesson_context,
                chunk_match_score=self._safe_float(components.get("chunk_match_score"), 0.0),
                matched_chunk_terms=item.get("chunk_signal", {}).get("matched_chunk_terms") or [],
            )
            enriched_item = dict(item)
            enriched_item["explanation"] = explanation
            payload, resource_identifier = self._build_recommendation_payload(
                item=enriched_item,
                rank=rank,
                mode=mode,
                level=level,
            )
            recommended.append(payload)
            self._persist_explanation_record(
                user_id=user_id,
                resource_identifier=resource_identifier,
                mode=mode,
                payload=payload,
            )

        progress_percentage = (len(completed) / len(goal_concepts) * 100.0) if goal_concepts else 0.0
        return {
            "recommended": recommended,
            "completed_concepts": len(completed),
            "total_concepts": len(goal_concepts),
            "progress_percentage": round(progress_percentage, 2),
                "reranking": reranking_result.get("metadata", {}),
                "learner_state": learner_state,
                "profile_context": {
                    "preferred_resource_type": preferred_resource_type,
                    "time_budget_minutes": time_budget_minutes,
                    "learning_pace": profile_context.get("learning_pace"),
                    "target_role": profile_context.get("target_role"),
                    "target_outcome": profile_context.get("target_outcome"),
                },
                "recommendation_mode": mode,
                "query_debug": {
                    "relevance_query": relevance_query,
                "lesson_query_payload": lesson_query_payload,
            },
        }

    def recommendation_debug_snapshot(
        self,
        *,
        user_id: str | int,
        goal: str,
        level: str,
        limit: int,
        enable_reranking: bool,
        mode: str = "continue_learning",
    ) -> Dict[str, Any]:
        normalized_mode = self._normalize_mode(mode)
        result = self.recommend_resources(
            user_id=user_id,
            goal=goal,
            level=level,
            limit=limit,
            enable_reranking=enable_reranking,
            mode=normalized_mode,
        )
        return {
            "input": {
                "user_id": str(user_id),
                "goal": goal,
                "level": level,
                "limit": limit,
                "mode": normalized_mode,
                "enable_reranking": enable_reranking,
            },
            "learner_state": result.get("learner_state", {}),
            "profile_context": result.get("profile_context", {}),
            "query_debug": result.get("query_debug", {}),
            "reranking": result.get("reranking", {}),
            "recommended_debug": result.get("recommended", []),
        }

    def _apply_hard_filters(
        self,
        *,
        resources: Sequence[Dict[str, Any]],
        user_id: str | int,
        mode: str,
        learner_level: str,
        lesson_context: Dict[str, Any] | None,
        focus_concepts: Sequence[str],
        query_tokens: Sequence[str],
        chunk_signal_map: Dict[str, Dict[str, Any]] | None,
        limit: int,
    ) -> List[Dict[str, Any]]:
        return apply_recommendation_hard_filters(
            self,
            resources=resources,
            user_id=user_id,
            mode=mode,
            learner_level=learner_level,
            lesson_context=lesson_context,
            focus_concepts=focus_concepts,
            query_tokens=query_tokens,
            chunk_signal_map=chunk_signal_map,
            limit=limit,
        )

    def _build_explanation(
        self,
        *,
        resource: Dict[str, Any],
        mode: str,
        learner_state: Dict[str, Any],
        goal: str,
        level: str,
        quality_score: float,
        expected_learning_gain: float,
        concept_gap_fit: float,
        difficulty_fit: float,
        lesson_context: Dict[str, Any] | None,
        chunk_match_score: float,
        matched_chunk_terms: list[str],
    ) -> Dict[str, Any]:
        return build_recommendation_explanation(
            self,
            resource=resource,
            mode=mode,
            learner_state=learner_state,
            goal=goal,
            level=level,
            quality_score=quality_score,
            expected_learning_gain=expected_learning_gain,
            concept_gap_fit=concept_gap_fit,
            difficulty_fit=difficulty_fit,
            lesson_context=lesson_context,
            chunk_match_score=chunk_match_score,
            matched_chunk_terms=matched_chunk_terms,
        )

    def _build_recommendation_payload(
        self,
        *,
        item: Dict[str, Any],
        rank: int,
        mode: str,
        level: str,
    ) -> tuple[Dict[str, Any], str]:
        return build_recommendation_item_payload(
            self,
            item=item,
            rank=rank,
            mode=mode,
            level=level,
        )

    def _persist_explanation_record(
        self,
        *,
        user_id: str | int,
        resource_identifier: str,
        mode: str,
        payload: Dict[str, Any],
    ) -> None:
        persist_recommendation_explanation_record(
            self,
            user_id=user_id,
            resource_identifier=resource_identifier,
            mode=mode,
            payload=payload,
        )

    def _concept_gap_fit(
        self,
        *,
        mastery: float,
        confidence: float,
        focus_concepts: Sequence[str],
        resource: Dict[str, Any],
    ) -> float:
        return compute_recommendation_concept_gap_fit(
            self,
            mastery=mastery,
            confidence=confidence,
            focus_concepts=focus_concepts,
            resource=resource,
        )

    def _expected_learning_gain(
        self,
        *,
        quality: Dict[str, Any],
        concept_gap_fit: float,
    ) -> float:
        return compute_recommendation_expected_gain(
            self,
            quality=quality,
            concept_gap_fit_value=concept_gap_fit,
        )

    def _fatigue_penalty(
        self,
        *,
        learner_state: Dict[str, Any],
        explanation_time: int,
    ) -> float:
        return compute_recommendation_fatigue_penalty(
            self,
            learner_state=learner_state,
            explanation_time=explanation_time,
        )

    def _compute_final_score(
        self,
        *,
        components: Dict[str, float],
        weights: ResourceRecommendationWeights,
    ) -> float:
        return compute_recommendation_final_score(
            self,
            components=components,
            weights=weights,
        )

    def _rerank_scored_items(
        self,
        *,
        scored_items: List[Dict[str, Any]],
        limit: int,
        enable_reranking: bool,
    ) -> Dict[str, Any]:
        return rerank_recommendation_items(
            self,
            scored_items=scored_items,
            limit=limit,
            enable_reranking=enable_reranking,
        )


hybrid_recommendation_service = HybridRecommendationService()
