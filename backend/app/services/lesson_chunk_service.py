"""Lesson-scoped instructional chunk recommendation service."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence
import logging

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
from backend.app.services.lesson_semantic_query_service import (
    lesson_semantic_query_service,
)
from backend.app.services.recommendation_reranking_service import (
    ReRankingConfig,
    RecommendationRerankingService,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChunkScoringWeights:
    semantic_score: float = 0.40
    lexical_score: float = 0.20
    objective_coverage: float = 0.15
    instructional_role_fit: float = 0.15
    questionability_score: float = 0.10


class LessonChunkService:
    """Recommend lesson-scoped chunks as an instructional sequence."""

    _INDEX_LINE_PATTERN = re.compile(
        r"^[^\n]{2,120}?(?:,|\.)?\s+\d{1,4}(?:-\d{1,4})?\s*$"
    )
    _GENERIC_CONCEPT_TERMS = {
        "python",
        "lap trinh python",
        "lập trình python",
        "python nâng cao",
        "python nang cao",
        "nâng cao",
        "nang cao",
        "cơ bản",
        "co ban",
        "giới thiệu",
        "gioi thieu",
        "backend",
        "lesson",
        "bài học",
        "bai hoc",
        "chương",
        "chuong",
        "khái niệm",
        "khai niem",
        "tổng quan",
        "tong quan",
    }
    _DEFAULT_SEQUENCE = [
        "introduction",
        "explanation",
        "worked_example",
        "summary",
    ]
    _ROLE_FALLBACKS = {
        "introduction": ("explanation", "summary"),
        "explanation": ("introduction", "worked_example", "summary"),
        "worked_example": ("explanation", "summary"),
        "summary": ("explanation", "introduction"),
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
        "assessment_boost": {
            "questionability_score": 0.12,
            "objective_coverage": 0.18,
        },
    }
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
    def _dedupe_keep_order(values: Sequence[str]) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for value in values:
            item = str(value or "").strip()
            if not item:
                continue
            normalized = item.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(item)
        return ordered

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
        payload = self._lesson_semantic_query_payload(context)
        return payload.get("bilingual_query") or payload.get("english_query") or ""

    def _lesson_semantic_query_payload(self, context: Dict[str, Any]) -> Dict[str, Any]:
        lesson = context["lesson"]
        chapter = context["chapter"]
        subject = context["subject"]
        return lesson_semantic_query_service.build_query_payload(
            title=str(lesson.get("title") or ""),
            summary=str(lesson.get("summary") or ""),
            objectives=[str(item) for item in lesson.get("learning_objectives") or []],
            keywords=[str(item) for item in lesson.get("keywords") or []],
            chapter_title=str(chapter.get("title") or ""),
            chapter_description=str(chapter.get("description") or ""),
            subject_title=str(subject.get("title") or ""),
            subject_topic=str(subject.get("topic") or ""),
        )

    def _priority_terms(self, context: Dict[str, Any]) -> List[str]:
        lesson = context["lesson"]
        tokens: List[str] = []
        payload = self._lesson_semantic_query_payload(context)
        for source in [
            *payload.get("english_terms", []),
            *payload.get("vietnamese_terms", []),
            str(lesson.get("title") or ""),
            str(lesson.get("summary") or ""),
            *[str(item) for item in lesson.get("learning_objectives") or []],
            *[str(item) for item in lesson.get("keywords") or []],
        ]:
            for token in self._tokenize(source):
                if token not in tokens:
                    tokens.append(token)
        return tokens[:16]

    @classmethod
    def _clean_concept_phrase(cls, phrase: str) -> str:
        normalized = cls._normalize_text(phrase)
        normalized = re.sub(
            r"\b(?:python|advanced|beginner|intermediate|nâng cao|nang cao|cơ bản|co ban|giới thiệu|gioi thieu|tổng quan|tong quan|backend)\b",
            " ",
            normalized,
        )
        normalized = re.sub(r"\s+", " ", normalized).strip(" -,:;/")
        return normalized

    def _lesson_required_concepts(self, context: Dict[str, Any]) -> List[str]:
        lesson = context["lesson"]
        raw_candidates: List[str] = []
        title = str(lesson.get("title") or "").strip()
        summary = str(lesson.get("summary") or "").strip()
        keywords = [str(item) for item in lesson.get("keywords") or []]

        title_focus = title.split(":", 1)[1] if ":" in title else title
        for source in [title_focus, *keywords]:
            cleaned_source = str(source or "").replace("/", ",").replace(";", ",")
            raw_candidates.extend(
                part.strip() for part in re.split(r",|\band\b|\bvà\b", cleaned_source, flags=re.IGNORECASE)
            )

        if not raw_candidates and summary:
            raw_candidates.extend(
                match.strip()
                for match in re.findall(
                    r"(decorator|generator|context manager|iterator|metaclass|descriptor|asyncio|coroutine|yield|with statement)",
                    self._normalize_text(summary),
                )
            )

        concepts: List[str] = []
        for candidate in raw_candidates:
            cleaned = self._clean_concept_phrase(candidate)
            if (
                not cleaned
                or cleaned in self._GENERIC_CONCEPT_TERMS
                or len(cleaned) < 3
                or cleaned in concepts
            ):
                continue
            concepts.append(cleaned)

        return concepts[:6]

    def _resolve_required_concepts(
        self,
        *,
        context: Dict[str, Any],
        metadata: Dict[str, Any] | None,
    ) -> List[str]:
        metadata = metadata or {}
        requested: List[str] = []
        for source in (
            metadata.get("required_concepts"),
            metadata.get("target_concepts"),
            metadata.get("current_focus_concepts"),
        ):
            values = source if isinstance(source, list) else [source] if source else []
            for item in values:
                cleaned = self._clean_concept_phrase(str(item))
                if (
                    cleaned
                    and cleaned not in self._GENERIC_CONCEPT_TERMS
                    and len(cleaned) >= 3
                    and cleaned not in requested
                ):
                    requested.append(cleaned)
        if requested:
            return requested[:6]
        return self._lesson_required_concepts(context)

    def _lesson_anchor_phrases(self, context: Dict[str, Any]) -> List[str]:
        lesson = context["lesson"]
        payload = self._lesson_semantic_query_payload(context)
        raw_sources = [
            str(lesson.get("title") or ""),
            str(lesson.get("summary") or ""),
            *[str(item) for item in lesson.get("learning_objectives") or []],
            *[str(item) for item in lesson.get("keywords") or []],
            *payload.get("english_terms", []),
        ]
        normalized_sources = [self._normalize_text(item) for item in raw_sources if str(item).strip()]
        phrases: List[str] = []

        for source in raw_sources:
            compact = " ".join(self._tokenize(source))
            if len(compact.split()) >= 2 and len(compact) <= 48:
                phrases.append(compact)

        has_loop_context = any(
            ("vòng lặp" in item) or ("loop" in item)
            for item in normalized_sources
        )
        has_condition_context = any(
            ("điều kiện" in item) or ("condition" in item) or ("conditional" in item)
            for item in normalized_sources
        )

        if has_loop_context and any(re.search(r"\bfor\b", item) for item in normalized_sources):
            phrases.extend(["for loop", "vòng lặp for", "for statement"])
        if has_loop_context and any(re.search(r"\bwhile\b", item) for item in normalized_sources):
            phrases.extend(["while loop", "vòng lặp while", "while statement"])
        if any(re.search(r"\belif\b", item) for item in normalized_sources):
            phrases.extend(["elif", "elif statement"])
        if any(re.search(r"\bif\b", item) for item in normalized_sources) and (
            any(re.search(r"\belse\b", item) for item in normalized_sources) or has_condition_context
        ):
            phrases.extend(
                [
                    "if else",
                    "if/else",
                    "câu lệnh if",
                    "câu lệnh else",
                    "else branch",
                    "conditional branch",
                ]
            )

        return self._dedupe_keep_order([*phrases, *payload.get("english_terms", [])])[:18]

    @classmethod
    def _resource_text(cls, metadata: Dict[str, Any] | None) -> str:
        metadata = metadata or {}
        parts = [
            str(metadata.get("source_title") or ""),
            str(metadata.get("title") or ""),
            str(metadata.get("heading") or ""),
            str(metadata.get("section_title") or ""),
            str(metadata.get("chapter_title") or ""),
        ]
        return " ".join(part for part in parts if part).strip()

    @classmethod
    def _anchor_match_score(
        cls,
        *,
        content: str,
        metadata: Dict[str, Any] | None,
        anchor_phrases: Sequence[str],
    ) -> float:
        if not anchor_phrases:
            return 0.0
        haystack = cls._normalize_text(f"{cls._resource_text(metadata)} {content}")
        hits = 0
        for phrase in anchor_phrases:
            normalized = cls._normalize_text(phrase)
            if not normalized:
                continue
            if normalized in {"for", "while", "if", "else"}:
                continue
            if normalized in haystack:
                hits += 1
        return round(cls._clamp(hits / max(min(len(anchor_phrases), 4), 1)), 4)

    @classmethod
    def _is_structural_noise_chunk(
        cls,
        *,
        content: str,
        metadata: Dict[str, Any] | None,
    ) -> bool:
        resource_text = cls._normalize_text(cls._resource_text(metadata))
        content_prefix = cls._normalize_text((content or "")[:220])
        haystacks = [item for item in (resource_text, content_prefix) if item]
        heading_noise = any(
            any(item.startswith(noise) for noise in cls._STRUCTURAL_NOISE_HEADINGS)
            for item in haystacks
        )
        return heading_noise or cls._index_like_score(content=content, metadata=metadata) >= 0.58

    @classmethod
    def _index_like_score(
        cls,
        *,
        content: str,
        metadata: Dict[str, Any] | None,
    ) -> float:
        normalized_content = cls._normalize_text(content)
        normalized_resource_text = cls._normalize_text(cls._resource_text(metadata))
        if not normalized_content:
            return 0.0

        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if not lines:
            return 0.0

        page_ref_lines = sum(
            1 for line in lines if cls._INDEX_LINE_PATTERN.match(line)
        )
        short_lines = sum(1 for line in lines if len(line) <= 80)
        alpha_heading_lines = sum(
            1
            for line in lines
            if re.fullmatch(r"[A-Z]", line.strip()) or re.fullmatch(r"[A-Z]\s+[A-Z]", line.strip())
        )
        comma_number_hits = len(
            re.findall(r",\s*\d{1,4}(?:-\d{1,4})?", content or "")
        )
        page_number_hits = len(
            re.findall(r"\b\d{1,4}(?:-\d{1,4})?\b", content or "")
        )
        sentence_hits = len(
            re.findall(r"(?<=[.!?])\s+[A-ZÀ-ỸA-Z]", content or "")
        )
        keyword_noise = float(
            any(noise in normalized_content for noise in ("table of contents", "glossary", "bibliography"))
            or " index " in f" {normalized_content} "
            or normalized_resource_text.startswith("index")
        )

        line_count = max(len(lines), 1)
        score = (
            0.3 * cls._clamp(page_ref_lines / max(min(line_count, 10), 1) * 2.0)
            + 0.15 * cls._clamp(short_lines / line_count)
            + 0.15 * cls._clamp(alpha_heading_lines / 3.0)
            + 0.2 * cls._clamp(comma_number_hits / 8.0)
            + 0.1 * cls._clamp(page_number_hits / max(line_count, 1) / 2.0)
            + 0.1 * keyword_noise
        )
        if sentence_hits >= 2:
            score -= 0.18
        return round(cls._clamp(score), 4)

    def _passes_relevance_gate(
        self,
        *,
        candidate: Dict[str, Any],
        anchor_phrases: Sequence[str],
        strict: bool,
    ) -> bool:
        score_breakdown = candidate.get("score_breakdown", {}) or {}
        semantic_score = float(score_breakdown.get("semantic_score", 0.0))
        lexical_score = float(score_breakdown.get("lexical_score", 0.0))
        objective_coverage = float(score_breakdown.get("objective_coverage", 0.0))
        questionability_score = float(score_breakdown.get("questionability_score", 0.0))
        anchor_match_score = float(candidate.get("anchor_match_score", 0.0))
        index_like_score = float(candidate.get("index_like_score", 0.0))
        required_concept_match_score = float(
            candidate.get("required_concept_match_score", 0.0)
        )
        required_concepts = candidate.get("required_concepts") or []
        covered_concepts = candidate.get("covered_concepts") or []
        noisy_section = bool(candidate.get("structural_noise"))

        if index_like_score >= 0.58:
            return False
        if required_concepts and required_concept_match_score <= 0.0:
            return False
        if noisy_section and anchor_match_score < 0.34 and objective_coverage <= 0.0:
            return False
        if noisy_section and questionability_score < 0.45 and semantic_score < 0.74:
            return False
        if objective_coverage >= 0.2:
            return True
        if anchor_match_score >= (0.45 if strict else 0.26):
            return True
        if covered_concepts and anchor_match_score >= 0.2 and semantic_score >= 0.3:
            return True
        if semantic_score >= (0.7 if strict else 0.58) and lexical_score >= 0.12 and anchor_match_score >= 0.12:
            return True
        if questionability_score >= 0.72 and anchor_match_score >= 0.18:
            return True
        return False

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
        seeded_queries = [
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
        global_backfill_queries = [
            {
                "topic": str(
                    lesson.get("topic") or chapter.get("topic") or subject.get("topic") or ""
                ).strip()
                or None,
                "level": str(lesson.get("level") or subject.get("level") or "beginner"),
                "resource_ids": None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 10, 40)),
            },
            {
                "topic": str(
                    lesson.get("topic") or chapter.get("topic") or subject.get("topic") or ""
                ).strip()
                or None,
                "level": None,
                "resource_ids": None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 8, 32)),
            },
            {
                "topic": None,
                "level": str(lesson.get("level") or subject.get("level") or "beginner"),
                "resource_ids": None,
                "limit": min(self._MAX_CANDIDATES, max(max_chunks * 6, 28)),
            },
        ]
        queries = seeded_queries + (
            global_backfill_queries if requested_resource_ids else []
        )

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
            if len(candidates) >= max(max_chunks * 24, 90):
                break
        return candidates[: self._MAX_CANDIDATES]

    @staticmethod
    def _normalize_resource_ids(values: Sequence[Any] | None) -> set[str]:
        return {
            str(value).strip()
            for value in (values or [])
            if str(value or "").strip()
        }

    def _apply_path_diversity_penalty(
        self,
        candidates: List[Dict[str, Any]],
        *,
        avoid_resource_ids: Sequence[Any] | None,
    ) -> List[Dict[str, Any]]:
        normalized_avoid_ids = self._normalize_resource_ids(avoid_resource_ids)
        if not normalized_avoid_ids:
            return candidates

        adjusted: List[Dict[str, Any]] = []
        for candidate in candidates:
            resource_id = str(candidate.get("resource_id") or "").strip()
            if resource_id not in normalized_avoid_ids:
                adjusted.append(candidate)
                continue

            penalized = dict(candidate)
            base_score = float(candidate.get("base_score", candidate.get("score", 0.0)) or 0.0)
            next_score = max(0.0, round(base_score - 0.22, 6))
            penalized["base_score"] = next_score
            penalized["score"] = next_score
            penalized["is_recently_seen"] = True
            penalized["path_diversity_penalty"] = 0.22
            adjusted.append(penalized)
        return adjusted

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
        instructional_role_fit: float,
        questionability_score: float,
        weights: ChunkScoringWeights,
    ) -> float:
        return round(
            self._clamp(
                weights.semantic_score * semantic_score
                + weights.lexical_score * lexical_score
                + weights.objective_coverage * objective_coverage
                + weights.instructional_role_fit * instructional_role_fit
                + weights.questionability_score * questionability_score
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
        anchor_phrases: Sequence[str],
        required_concepts: Sequence[str],
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
        anchor_match_score = self._anchor_match_score(
            content=content,
            metadata=metadata,
            anchor_phrases=anchor_phrases,
        )
        normalized_required_concepts = [
            self._normalize_text(item) for item in required_concepts if self._normalize_text(item)
        ]
        concept_haystack = self._normalize_text(
            f"{self._resource_text(metadata)} {content}"
        )
        matched_required_concepts = [
            concept
            for concept in normalized_required_concepts
            if concept in concept_haystack
        ]
        required_concept_match_score = round(
            self._clamp(
                len(matched_required_concepts)
                / max(min(len(normalized_required_concepts), 2), 1)
            ),
            4,
        )
        index_like_score = self._index_like_score(content=content, metadata=metadata)
        structural_noise = self._is_structural_noise_chunk(content=content, metadata=metadata)

        semantic_score = round(self._cosine(query_vector, chunk_vector), 6)
        lexical_score = round(self._lexical_score(query_terms, content), 6)
        objective_coverage = round(
            self._clamp(len(covered_objectives) / max(len(objectives), 1)),
            6,
        )
        difficulty = str(
            metadata.get("difficulty")
            or metadata.get("level")
            or lesson.get("level")
            or "beginner"
        ).lower()
        instructional_role_fit = round(self._ROLE_BASE_FIT.get(role, 0.75), 6)
        estimated_read_time = self._estimate_read_time(content)
        preview = re.sub(r"\s+", " ", content).strip()[:280]

        score_breakdown = {
            "semantic_score": semantic_score,
            "lexical_score": lexical_score,
            "objective_coverage": objective_coverage,
            "instructional_role_fit": instructional_role_fit,
            "questionability_score": questionability_score,
            "anchor_match_score": anchor_match_score,
            "index_like_score": index_like_score,
        }
        score = self._score_chunk(
            semantic_score=semantic_score,
            lexical_score=lexical_score,
            objective_coverage=objective_coverage,
            instructional_role_fit=instructional_role_fit,
            questionability_score=questionability_score,
            weights=weights,
        )
        if index_like_score >= 0.4:
            score = round(
                self._clamp(score - min(0.45, index_like_score * 0.55)),
                6,
            )
        if normalized_required_concepts:
            if required_concept_match_score <= 0.0:
                score = round(self._clamp(score - 0.3), 6)
            else:
                score = round(
                    self._clamp(score + min(0.18, required_concept_match_score * 0.18)),
                    6,
                )

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
            "anchor_match_score": anchor_match_score,
            "index_like_score": index_like_score,
            "required_concepts": normalized_required_concepts,
            "matched_required_concepts": matched_required_concepts,
            "required_concept_match_score": required_concept_match_score,
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
            "structural_noise": structural_noise,
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
        required_concepts: Sequence[str] | None = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not candidates:
            return [], {
                "has_introduction": False,
                "has_explanation": False,
                "has_example": False,
                "has_summary": False,
                "roles_present": [],
                "missing_roles": self._DEFAULT_SEQUENCE[:max_chunks],
                "required_concepts": list(required_concepts or []),
                "covered_required_concepts": [],
                "missing_required_concepts": list(required_concepts or []),
            }

        desired_roles = self._DEFAULT_SEQUENCE[: max(max_chunks, 1)]
        normalized_required_concepts = [
            self._normalize_text(item)
            for item in (required_concepts or [])
            if self._normalize_text(item)
        ]
        covered_required_concepts: set[str] = set()
        unused = list(candidates)
        selected: List[Dict[str, Any]] = []

        for target_role in desired_roles:
            if not unused or len(selected) >= max_chunks:
                break
            best_item = None
            best_rank = float("-inf")
            for candidate in unused:
                role_fit = self._target_role_fit(candidate["instruction_role"], target_role)
                matched_required_concepts = {
                    self._normalize_text(item)
                    for item in (candidate.get("matched_required_concepts") or [])
                    if self._normalize_text(item)
                }
                new_required_concepts = matched_required_concepts - covered_required_concepts
                concept_bonus = 0.0
                if normalized_required_concepts:
                    if new_required_concepts:
                        concept_bonus += min(0.32, 0.16 * len(new_required_concepts))
                    elif matched_required_concepts:
                        concept_bonus += 0.04
                rank = (
                    0.68 * float(candidate.get("base_score", 0.0))
                    + 0.22 * role_fit
                    + concept_bonus
                )
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
            covered_required_concepts.update(
                self._normalize_text(item)
                for item in (best_item.get("matched_required_concepts") or [])
                if self._normalize_text(item)
            )
            unused = [item for item in unused if item["chunk_id"] != best_item["chunk_id"]]

        for candidate in sorted(
            unused,
            key=lambda item: (
                -len(
                    {
                        self._normalize_text(concept)
                        for concept in (item.get("matched_required_concepts") or [])
                        if self._normalize_text(concept)
                    }
                    - covered_required_concepts
                ),
                -float(item.get("base_score", 0.0)),
            ),
        ):
            if len(selected) >= max_chunks:
                break
            enriched = dict(candidate)
            enriched["sequence_target_role"] = candidate["instruction_role"]
            enriched["assigned_role_fit"] = 1.0
            selected.append(enriched)
            covered_required_concepts.update(
                self._normalize_text(item)
                for item in (candidate.get("matched_required_concepts") or [])
                if self._normalize_text(item)
            )

        finalized: List[Dict[str, Any]] = []
        for index, candidate in enumerate(selected, start=1):
            score_breakdown = dict(candidate.get("score_breakdown", {}))
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
                instructional_role_fit=float(score_breakdown.get("instructional_role_fit", 0.0)),
                questionability_score=float(score_breakdown.get("questionability_score", 0.0)),
                weights=weights,
            )
            enriched = dict(candidate)
            enriched["sequence_position"] = index
            enriched["score_breakdown"] = score_breakdown
            enriched["score"] = candidate_score
            enriched["final_base_score"] = candidate_score
            finalized.append(enriched)

        roles_present = [item["instruction_role"] for item in finalized]
        ordered_covered_required_concepts: List[str] = []
        for item in finalized:
            for concept in item.get("matched_required_concepts") or []:
                normalized_concept = self._normalize_text(concept)
                if (
                    normalized_concept
                    and normalized_concept in covered_required_concepts
                    and normalized_concept not in ordered_covered_required_concepts
                ):
                    ordered_covered_required_concepts.append(normalized_concept)
        sequence_metadata = {
            "has_introduction": "introduction" in roles_present,
            "has_explanation": "explanation" in roles_present,
            "has_example": "worked_example" in roles_present,
            "has_summary": "summary" in roles_present,
            "roles_present": roles_present,
            "missing_roles": [role for role in desired_roles if role not in roles_present],
            "required_concepts": normalized_required_concepts,
            "covered_required_concepts": ordered_covered_required_concepts,
            "missing_required_concepts": [
                concept
                for concept in normalized_required_concepts
                if concept not in ordered_covered_required_concepts
            ],
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
                    "matched_required_concepts": [],
                    "estimated_read_time": self._estimate_read_time(
                        str(chunk.get("content") or "")
                    ),
                    "questionability_score": 0.5,
                    "anchor_match_score": 0.0,
                    "index_like_score": 0.0,
                    "score_breakdown": {},
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

    def _stored_chunk_anchor_match_score(
        self,
        *,
        chunk: Dict[str, Any],
        anchor_phrases: Sequence[str],
    ) -> float:
        metadata = {
            "source_title": chunk.get("resource_title"),
            "title": chunk.get("resource_title"),
            "section_title": chunk.get("heading"),
        }
        return self._anchor_match_score(
            content=str(chunk.get("preview") or ""),
            metadata=metadata,
            anchor_phrases=anchor_phrases,
        )

    def _should_refresh_recommendation(
        self,
        *,
        recommendation: Dict[str, Any] | None,
        context: Dict[str, Any],
    ) -> tuple[bool, str]:
        if not recommendation:
            return True, "missing_recommendation"

        metadata = recommendation.get("metadata") or {}
        selection_strategy = str(recommendation.get("selection_strategy") or "")
        recommended_chunks = recommendation.get("recommended_chunks") or []
        if metadata.get("auto_refresh_disabled"):
            return False, "disabled"
        if not recommended_chunks:
            return True, "missing_chunks"
        if selection_strategy != "local_semantic_lesson_scope_v1":
            return True, "legacy_selection_strategy"
        if metadata.get("fallback"):
            return True, "fallback_recommendation"
        if not metadata.get("anchor_phrases") or "gated_candidate_count" not in metadata:
            return True, "missing_anchor_metadata"

        anchor_phrases = self._lesson_anchor_phrases(context)
        if not anchor_phrases:
            return False, "no_anchor_phrases"

        meaningful_chunks = 0
        noisy_chunks = 0
        for chunk in recommended_chunks:
            anchor_score = float(chunk.get("anchor_match_score") or 0.0)
            if anchor_score <= 0.0:
                anchor_score = self._stored_chunk_anchor_match_score(
                    chunk=chunk,
                    anchor_phrases=anchor_phrases,
                )
            structural_noise = self._is_structural_noise_chunk(
                content=str(chunk.get("preview") or ""),
                metadata={"source_title": chunk.get("resource_title")},
            )
            objective_hits = len(chunk.get("covered_objectives") or [])
            concept_hits = len(chunk.get("covered_concepts") or [])
            if structural_noise and anchor_score < 0.25 and objective_hits == 0:
                noisy_chunks += 1
                continue
            if anchor_score >= 0.2 or objective_hits > 0 or concept_hits > 0:
                meaningful_chunks += 1

        minimum_meaningful = max(2, min(len(recommended_chunks), 3))
        if meaningful_chunks < minimum_meaningful:
            return True, "low_lesson_alignment"
        if noisy_chunks >= max(2, len(recommended_chunks) // 2):
            return True, "structural_noise_detected"
        return False, "fresh"

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

        lesson_query_payload = self._lesson_semantic_query_payload(context)
        weights = self._weights_for_mode((metadata or {}).get("mode"))
        query_terms = self._priority_terms(context)
        anchor_phrases = self._lesson_anchor_phrases(context)
        required_concepts = self._resolve_required_concepts(
            context=context,
            metadata=metadata,
        )
        for concept in required_concepts:
            if concept not in query_terms:
                query_terms.append(concept)
            if len(concept.split()) >= 2 and concept not in anchor_phrases:
                anchor_phrases.append(concept)
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
                anchor_phrases=anchor_phrases,
                required_concepts=required_concepts,
                weights=weights,
            )
            for row in candidates
        ]
        analyzed = self._apply_path_diversity_penalty(
            analyzed,
            avoid_resource_ids=((metadata or {}).get("avoid_resource_ids") or []),
        )
        strict_candidates = [
            item
            for item in analyzed
            if self._passes_relevance_gate(
                candidate=item,
                anchor_phrases=anchor_phrases,
                strict=True,
            )
        ]
        relaxed_candidates = [
            item
            for item in analyzed
            if self._passes_relevance_gate(
                candidate=item,
                anchor_phrases=anchor_phrases,
                strict=False,
            )
        ]
        filtered_candidates = (
            strict_candidates
            if len(strict_candidates) >= max(3, min(max_chunks, 4))
            else relaxed_candidates or strict_candidates or analyzed
        )
        representatives = self._cluster_candidates(filtered_candidates)
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
            required_concepts=required_concepts,
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
                    "lesson_query_payload": lesson_query_payload,
                    "anchor_phrases": anchor_phrases,
                    "required_concepts": list(required_concepts),
                    "candidate_count": len(candidates),
                    "gated_candidate_count": len(filtered_candidates),
                    "strict_candidate_count": len(strict_candidates),
                    "cluster_count": len(representatives),
                    "selected_count": len(hydrated),
                    "scores": score_map,
                    "diversity_reranking": rerank_metadata,
                    "avoid_resource_ids": list(
                        self._normalize_resource_ids(
                            ((metadata or {}).get("avoid_resource_ids") or [])
                        )
                    ),
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
        context = self._get_lesson_context(lesson_id)
        should_refresh, reason = self._should_refresh_recommendation(
            recommendation=recommendation,
            context=context,
        )
        if should_refresh:
            lesson = context["lesson"]
            try:
                return self.recommend_chunks(
                    lesson_id=lesson_id,
                    max_chunks=max(
                        len((recommendation or {}).get("chunk_ids") or []),
                        8,
                    ),
                    selection_strategy="local_semantic_lesson_scope_v1",
                    enable_diversity_reranking=True,
                    diversity_lambda=None,
                    resource_ids=[
                        str(item)
                        for item in (
                            lesson.get("resource_ids")
                            or lesson.get("recommended_resource_ids")
                            or (recommendation or {}).get("resource_ids")
                            or []
                        )
                    ],
                    metadata={
                        **((recommendation or {}).get("metadata") or {}),
                        "auto_refreshed": True,
                        "refresh_reason": reason,
                    },
                )
            except Exception as exc:
                if recommendation:
                    logger.warning(
                        "Auto-refresh lesson recommendation failed for lesson_id=%s: %s",
                        lesson_id,
                        exc,
                    )
                else:
                    raise
        if not recommendation:
            raise ValueError("Lesson recommendation not found.")
        return self._serialize_recommendation(recommendation)


lesson_chunk_service = LessonChunkService()
