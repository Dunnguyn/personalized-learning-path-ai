"""Lightweight cross-verification heuristics for generated lesson questions."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from backend.app.services.question_nlp_service import question_nlp_service


QUESTION_VERIFICATION_MIN_SCORE = float(
    os.getenv("LESSON_QUESTION_VERIFICATION_MIN_SCORE", "0.55")
)
QUESTION_VERIFICATION_HARD_FAIL_SCORE = float(
    os.getenv("LESSON_QUESTION_VERIFICATION_HARD_FAIL_SCORE", "0.35")
)


@dataclass(frozen=True)
class QuestionVerificationResult:
    overall_score: float
    concept_score: float
    bloom_score: float
    distractor_score: float
    grounding_score: float
    predicted_bloom_level: str
    matched_target_concepts: List[str]
    blockers: List[str]
    passed: bool
    hard_fail: bool


class QuestionCrossVerificationService:
    """Rule-based verification layer to improve question quality before save."""

    _BLOOM_HINTS = {
        "remember": [
            "khai niệm nào",
            "khái niệm nào",
            "đáp án nào",
            "term nào",
            "nêu",
            "nhắc lại",
            "xuất hiện",
            "trực tiếp",
        ],
        "understand": [
            "mô tả đúng",
            "mô tả đúng nhất",
            "giải thích",
            "ý nghĩa",
            "phù hợp nhất",
            "khớp nhất",
            "tóm tắt",
            "vai trò của",
        ],
        "apply": [
            "áp dụng",
            "sử dụng",
            "trong tình huống",
            "nếu áp dụng",
            "kết quả nào",
            "thực hiện",
            "minh họa",
        ],
        "analyze": [
            "phân tích",
            "so sánh",
            "vì sao",
            "liên quan nhất",
            "quan hệ",
            "ảnh hưởng",
            "thành phần nào",
        ],
    }

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _predict_bloom_level(self, *, question_text: str, question_type: str) -> str:
        normalized = self._normalize_text(question_text)
        if not normalized:
            return "remember"
        for level in ("analyze", "apply", "understand", "remember"):
            if any(hint in normalized for hint in self._BLOOM_HINTS[level]):
                return level
        if question_type == "short_answer":
            return "understand"
        return "remember"

    def _score_bloom_alignment(
        self,
        *,
        question_text: str,
        question_type: str,
        labeled_bloom_level: str,
        requested_bloom_levels: Sequence[str],
    ) -> tuple[float, str]:
        predicted = self._predict_bloom_level(
            question_text=question_text,
            question_type=question_type,
        )
        labeled = self._normalize_text(labeled_bloom_level)
        requested = {
            self._normalize_text(value)
            for value in (requested_bloom_levels or [])
            if self._normalize_text(value)
        }
        score = 0.45
        if not requested:
            score += 0.15
        elif labeled in requested:
            score += 0.3
        elif predicted in requested:
            score += 0.2
        if predicted == labeled:
            score += 0.25
        elif labeled in {"apply", "analyze"} and predicted in {"remember", "understand"}:
            score -= 0.2
        return max(0.0, min(score, 1.0)), predicted

    def _score_concept_alignment(
        self,
        *,
        question: Any,
        target_concepts: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> tuple[float, List[str]]:
        metadata = question.metadata if isinstance(getattr(question, "metadata", None), dict) else {}
        normalized_targets = [
            self._normalize_text(value)
            for value in (target_concepts or [])
            if self._normalize_text(value)
        ]
        matched_existing = [
            self._normalize_text(value)
            for value in (metadata.get("matched_target_concepts") or [])
            if self._normalize_text(value)
        ]
        if matched_existing:
            return 1.0, matched_existing

        candidate_parts: List[str] = [
            str(metadata.get("concept_focus") or ""),
            str(metadata.get("question_focus") or ""),
            str(metadata.get("source_excerpt") or ""),
            str(getattr(question, "question", "") or ""),
            str(getattr(question, "correct_answer", "") or ""),
        ]
        for key in ("covered_concepts", "target_concepts"):
            for value in metadata.get(key) or []:
                candidate_parts.append(str(value))
        for chunk_id in getattr(question, "chunk_ids", []) or []:
            chunk = chunk_map.get(str(chunk_id)) or {}
            chunk_metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            for source in (
                chunk.get("covered_concepts"),
                chunk.get("matched_required_concepts"),
                chunk_metadata.get("covered_concepts"),
                chunk_metadata.get("matched_required_concepts"),
            ):
                values = source if isinstance(source, list) else [source] if source else []
                for value in values:
                    candidate_parts.append(str(value))

        candidate_text = " ".join(self._normalize_text(value) for value in candidate_parts if value).strip()
        if not normalized_targets:
            score = 0.8 if candidate_text else 0.45
            return score, []

        matched: List[str] = []
        for target in normalized_targets:
            if target and target in candidate_text:
                matched.append(target)
        semantic = question_nlp_service.semantic_similarity(candidate_text, normalized_targets)
        lexical = question_nlp_service.lexical_relevance(candidate_text, normalized_targets)
        score = max(0.0, min(1.0, (semantic * 0.6) + (lexical * 0.4)))
        if matched:
            score = max(score, 0.85)
        return score, matched

    def _score_distractor_quality(self, *, question: Any) -> float:
        if getattr(question, "question_type", "") != "multiple_choice":
            return 0.78 if getattr(question, "question_type", "") == "short_answer" else 0.7

        correct_answer = self._normalize_text(getattr(question, "correct_answer", ""))
        distractors = [
            self._normalize_text(value)
            for value in (getattr(question, "distractors", []) or [])
            if self._normalize_text(value)
        ]
        if len(distractors) != 3:
            return 0.0

        unique_count = len({correct_answer, *distractors})
        score = 0.25 if unique_count == 4 else 0.0
        plausible_hits = 0
        for distractor in distractors:
            similarity = question_nlp_service.semantic_similarity(distractor, [correct_answer])
            if 0.05 <= similarity <= 0.92:
                plausible_hits += 1
            if 3 <= len(distractor) <= 80:
                score += 0.08
        score += plausible_hits * 0.17
        return max(0.0, min(score, 1.0))

    def _score_grounding_quality(self, *, metadata: Dict[str, Any]) -> float:
        source_excerpt = self._normalize_text(metadata.get("source_excerpt"))
        evidence_score = float(metadata.get("evidence_score", 0.0) or 0.0)
        source_score = float(metadata.get("source_score", 0.0) or 0.0)
        score = 0.0
        if 45 <= len(source_excerpt) <= 280:
            score += 0.4
        elif source_excerpt:
            score += 0.2
        score += min(1.0, evidence_score / 4.0) * 0.35
        score += min(1.0, source_score) * 0.25
        return max(0.0, min(score, 1.0))

    def verify_question(
        self,
        *,
        question: Any,
        target_concepts: Sequence[str],
        requested_bloom_levels: Sequence[str],
        chunk_map: Dict[str, Dict[str, Any]],
    ) -> QuestionVerificationResult:
        metadata = question.metadata if isinstance(getattr(question, "metadata", None), dict) else {}
        concept_score, matched_target_concepts = self._score_concept_alignment(
            question=question,
            target_concepts=target_concepts,
            chunk_map=chunk_map,
        )
        bloom_score, predicted_bloom = self._score_bloom_alignment(
            question_text=str(getattr(question, "question", "") or ""),
            question_type=str(getattr(question, "question_type", "") or ""),
            labeled_bloom_level=str(getattr(question, "bloom_level", "") or ""),
            requested_bloom_levels=requested_bloom_levels,
        )
        distractor_score = self._score_distractor_quality(question=question)
        grounding_score = self._score_grounding_quality(metadata=metadata)
        overall = (
            concept_score * 0.35
            + bloom_score * 0.2
            + distractor_score * 0.2
            + grounding_score * 0.25
        )
        blockers: List[str] = []
        if target_concepts and concept_score < 0.3:
            blockers.append("concept_mismatch")
        if grounding_score < 0.25:
            blockers.append("weak_grounding")
        if getattr(question, "question_type", "") == "multiple_choice" and distractor_score < 0.28:
            blockers.append("weak_distractors")

        hard_fail = overall < QUESTION_VERIFICATION_HARD_FAIL_SCORE or (
            "concept_mismatch" in blockers and overall < 0.5
        )
        passed = overall >= QUESTION_VERIFICATION_MIN_SCORE and not hard_fail
        return QuestionVerificationResult(
            overall_score=round(max(0.0, min(overall, 1.0)), 4),
            concept_score=round(max(0.0, min(concept_score, 1.0)), 4),
            bloom_score=round(max(0.0, min(bloom_score, 1.0)), 4),
            distractor_score=round(max(0.0, min(distractor_score, 1.0)), 4),
            grounding_score=round(max(0.0, min(grounding_score, 1.0)), 4),
            predicted_bloom_level=predicted_bloom,
            matched_target_concepts=matched_target_concepts,
            blockers=blockers,
            passed=passed,
            hard_fail=hard_fail,
        )


question_cross_verification_service = QuestionCrossVerificationService()
