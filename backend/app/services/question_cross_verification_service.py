"""Lightweight cross-verification heuristics for generated lesson questions."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from backend.app.services.question_nlp_service import question_nlp_service


QUESTION_VERIFICATION_MIN_SCORE = float(
    os.getenv("LESSON_QUESTION_VERIFICATION_MIN_SCORE", "0.64")
)
QUESTION_VERIFICATION_HARD_FAIL_SCORE = float(
    os.getenv("LESSON_QUESTION_VERIFICATION_HARD_FAIL_SCORE", "0.44")
)


@dataclass(frozen=True)
class QuestionVerificationResult:
    overall_score: float
    concept_score: float
    bloom_score: float
    distractor_score: float
    grounding_score: float
    stem_score: float
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

    def _has_application_cue(self, *, question_text: str, metadata: Dict[str, Any]) -> bool:
        normalized = self._normalize_text(question_text)
        reasoning_pattern = self._normalize_text(metadata.get("reasoning_pattern"))
        if reasoning_pattern in {"worked_example", "decision_rule", "error_detection"}:
            return True
        cues = (
            "trong vi du",
            "ví dụ",
            "trong truong hop",
            "trường hợp",
            "khi",
            "neu",
            "nếu",
            "quyet dinh",
            "quyết định",
        )
        return any(cue in normalized for cue in cues)

    def _score_stem_quality(
        self,
        *,
        question_text: str,
        correct_answer: str,
        requested_bloom_levels: Sequence[str],
        predicted_bloom_level: str,
    ) -> float:
        normalized_question = self._normalize_text(question_text)
        normalized_answer = self._normalize_text(correct_answer)
        requested = {
            self._normalize_text(value)
            for value in (requested_bloom_levels or [])
            if self._normalize_text(value)
        }
        if not normalized_question:
            return 0.0

        score = 0.82
        if normalized_answer and normalized_answer in normalized_question:
            return 0.0

        if len(normalized_question) < 28:
            score -= 0.28
        elif len(normalized_question) < 40:
            score -= 0.12

        shallow_starts = {
            "khai niem nao",
            "khái niệm nào",
            "dap an nao",
            "đáp án nào",
            "term nao",
            "nêu",
            "nhac lai",
            "nhắc lại",
        }
        if any(normalized_question.startswith(prefix) for prefix in shallow_starts):
            score -= 0.22

        if requested & {"apply", "analyze", "evaluate", "create"} and predicted_bloom_level in {
            "remember",
            "understand",
        }:
            score -= 0.28

        return max(0.0, min(score, 1.0))

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
        evidence_terms = [
            self._normalize_text(value)
            for value in (metadata.get("evidence_terms") or [])
            if self._normalize_text(value)
        ]
        score = 0.0
        if 45 <= len(source_excerpt) <= 280:
            score += 0.4
        elif source_excerpt:
            score += 0.2
        score += min(1.0, evidence_score / 4.0) * 0.35
        score += min(1.0, source_score) * 0.25
        score += min(len(evidence_terms), 3) * 0.05
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
        has_application_cue = self._has_application_cue(
            question_text=str(getattr(question, "question", "") or ""),
            metadata=metadata,
        )
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
        stem_score = self._score_stem_quality(
            question_text=str(getattr(question, "question", "") or ""),
            correct_answer=str(getattr(question, "correct_answer", "") or ""),
            requested_bloom_levels=requested_bloom_levels,
            predicted_bloom_level=predicted_bloom,
        )
        overall = (
            concept_score * 0.33
            + bloom_score * 0.18
            + distractor_score * 0.2
            + grounding_score * 0.23
            + stem_score * 0.06
        )
        if has_application_cue and predicted_bloom in {"remember", "understand"}:
            overall += 0.05
        blockers: List[str] = []
        if target_concepts and concept_score < 0.3:
            blockers.append("concept_mismatch")
        if grounding_score < 0.25:
            blockers.append("weak_grounding")
        if getattr(question, "question_type", "") == "multiple_choice" and distractor_score < 0.28:
            blockers.append("weak_distractors")
        if stem_score < 0.35:
            blockers.append("answer_leak_or_shallow_stem")
        if (
            {
                self._normalize_text(value)
                for value in (requested_bloom_levels or [])
                if self._normalize_text(value)
            }
            & {"apply", "analyze", "evaluate", "create"}
            and predicted_bloom in {"remember", "understand"}
            and not has_application_cue
        ):
            blockers.append("shallow_cognitive_level")

        hard_fail = overall < QUESTION_VERIFICATION_HARD_FAIL_SCORE or (
            "concept_mismatch" in blockers and overall < 0.5
        ) or "answer_leak_or_shallow_stem" in blockers
        passed = overall >= QUESTION_VERIFICATION_MIN_SCORE and not hard_fail
        return QuestionVerificationResult(
            overall_score=round(max(0.0, min(overall, 1.0)), 4),
            concept_score=round(max(0.0, min(concept_score, 1.0)), 4),
            bloom_score=round(max(0.0, min(bloom_score, 1.0)), 4),
            distractor_score=round(max(0.0, min(distractor_score, 1.0)), 4),
            grounding_score=round(max(0.0, min(grounding_score, 1.0)), 4),
            stem_score=round(max(0.0, min(stem_score, 1.0)), 4),
            predicted_bloom_level=predicted_bloom,
            matched_target_concepts=matched_target_concepts,
            blockers=blockers,
            passed=passed,
            hard_fail=hard_fail,
        )


question_cross_verification_service = QuestionCrossVerificationService()
