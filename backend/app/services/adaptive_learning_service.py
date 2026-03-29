"""Closed-loop adaptive learning orchestration service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db
from backend.app.repositories import (
    AdaptiveAttemptRepository,
    AdaptiveEventRepository,
    LessonRepository,
    UserLearningStateRepository,
)
from backend.app.services.adaptive_decision_service import adaptive_decision_service
from backend.app.services.adaptive_question_selector import adaptive_question_selector
from backend.app.services.concept_extraction_service import concept_extraction_service
from backend.app.services.mastery_update_service import mastery_update_service
from backend.app.services.progress_evaluation_service import progress_evaluation_service
from backend.app.services.retry_strategy_service import retry_strategy_service

logger = logging.getLogger(__name__)


class AdaptiveLearningService:
    """Coordinate evaluate -> mastery update -> decision -> persistence."""

    def __init__(self) -> None:
        db = get_db()
        self.lesson_repository = LessonRepository()
        self.attempt_repository = AdaptiveAttemptRepository(db)
        self.learning_state_repository = UserLearningStateRepository(db)
        self.adaptive_event_repository = AdaptiveEventRepository(db)

    def process_attempt(
        self,
        *,
        user_id: str,
        lesson_id: str,
        path_id: str,
        questions: List[Dict[str, Any]],
        submitted_confidence: float | None,
        target_count: int = 6,
    ) -> Dict[str, Any]:
        lesson = self.lesson_repository.get_by_id(lesson_id)
        subject_id = str(lesson.get("subject_id") or "") if lesson else ""
        lesson_concepts = concept_extraction_service.extract_from_texts(
            [
                str(lesson.get("title") or "") if lesson else "",
                str(lesson.get("summary") or "") if lesson else "",
                " ".join(str(item.get("concept_id") or "") for item in questions or []),
            ]
        )

        normalized_questions = self._normalize_questions(
            questions,
            fallback_concepts=lesson_concepts,
        )

        recent_attempts = self.attempt_repository.get_recent_attempts(
            user_id=user_id,
            lesson_id=lesson_id,
            k=3,
        )
        evaluation = progress_evaluation_service.evaluate_attempt(
            normalized_questions,
            recent_attempts=recent_attempts,
        )

        previous_state = self.learning_state_repository.get_state(
            user_id=user_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
        )
        default_difficulty = self._resolve_latest_difficulty(
            normalized_questions,
            previous_state,
        )

        mastery_update = mastery_update_service.apply(
            previous_state=previous_state,
            evaluation=evaluation,
            questions=normalized_questions,
            recommended_difficulty=default_difficulty,
            recent_attempts=recent_attempts,
        )

        weakest_concept = self._resolve_weakest_concept(
            evaluation_wrong=evaluation.wrong_by_concept,
            concept_mastery=mastery_update.concept_mastery,
        )
        retry_count_by_concept = dict((previous_state or {}).get("retry_count_by_concept") or {})
        retry_count = int(retry_count_by_concept.get(weakest_concept, 0)) + 1 if weakest_concept else 1
        retry_strategy = retry_strategy_service.select_retry_strategy(retry_count)

        decision = adaptive_decision_service.decide(
            evaluation=evaluation,
            lesson_mastery=mastery_update.new_lesson_mastery,
            chunk_mastery=mastery_update.chunk_mastery,
            concept_mastery=mastery_update.concept_mastery,
            retry_strategy=retry_strategy,
        )

        if weakest_concept and decision.next_action in {
            "increase_difficulty_fast",
            "increase_difficulty",
            "advance_to_next_lesson",
        }:
            retry_count_by_concept[weakest_concept] = 0

        attempt_id = f"att_{uuid.uuid4().hex}"
        attempt_payload = {
            "attempt_id": attempt_id,
            "user_id": str(user_id),
            "path_id": str(path_id),
            "lesson_id": str(lesson_id),
            "questions": normalized_questions,
            "total_questions": evaluation.total_questions,
            "correct_count": evaluation.correct_count,
            "wrong_count": evaluation.wrong_count,
            "accuracy": evaluation.accuracy,
            "average_confidence": evaluation.average_confidence,
            "submitted_confidence": float(submitted_confidence or 0.0),
            "submitted_at": datetime.utcnow(),
        }
        self.attempt_repository.create_attempt(attempt_payload)

        if weakest_concept:
            retry_count_by_concept[weakest_concept] = retry_count

        recent_attempt_ids = [attempt_id]
        recent_attempt_ids.extend(
            str(item.get("attempt_id") or "")
            for item in recent_attempts
            if str(item.get("attempt_id") or "").strip()
        )
        recent_attempt_ids = recent_attempt_ids[:5]

        state_payload = {
            "user_id": str(user_id),
            "subject_id": subject_id,
            "lesson_id": str(lesson_id),
            "chunk_mastery": mastery_update.chunk_mastery,
            "concept_mastery": mastery_update.concept_mastery,
            "lesson_mastery": mastery_update.new_lesson_mastery,
            "success_rate": mastery_update.success_rate,
            "total_attempts": mastery_update.total_attempts,
            "last_difficulty": decision.recommended_difficulty,
            "recommended_next_action": decision.next_action,
            "last_accuracy": evaluation.accuracy,
            "retry_count_by_concept": retry_count_by_concept,
            "recent_attempt_ids": recent_attempt_ids,
            "updated_at": datetime.utcnow(),
        }
        persisted_state = self.learning_state_repository.upsert_state(state_payload)

        event_payload = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "user_id": str(user_id),
            "lesson_id": str(lesson_id),
            "attempt_id": attempt_id,
            "previous_mastery": mastery_update.previous_lesson_mastery,
            "new_mastery": mastery_update.new_lesson_mastery,
            "decision": decision.next_action,
            "reason": decision.reason,
            "recommended_difficulty": decision.recommended_difficulty,
            "recommended_bloom_levels": decision.recommended_bloom_levels,
            "target_chunk_ids": decision.target_chunk_ids,
            "target_concepts": decision.target_concepts,
            "retry_strategy": decision.retry_strategy,
            "fail_streak": decision.fail_streak,
            "success_streak": decision.success_streak,
            "created_at": datetime.utcnow(),
        }
        self.adaptive_event_repository.create_event(event_payload)

        logger.info(
            "[AdaptiveLoop] attempt_id=%s user_id=%s lesson_id=%s accuracy=%.4f mastery=%.4f action=%s reason=%s difficulty=%s bloom=%s chunks=%s",
            attempt_id,
            user_id,
            lesson_id,
            evaluation.accuracy,
            mastery_update.new_lesson_mastery,
            decision.next_action,
            decision.reason,
            decision.recommended_difficulty,
            decision.recommended_bloom_levels,
            decision.target_chunk_ids,
        )

        next_quiz = adaptive_question_selector.select_next(
            lesson_id=lesson_id,
            learning_state=persisted_state,
            attempt_evaluation={
                "accuracy": evaluation.accuracy,
                "wrong_by_chunk": evaluation.wrong_by_chunk,
                "wrong_by_concept": evaluation.wrong_by_concept,
            },
            decision={
                "recommended_difficulty": decision.recommended_difficulty,
                "recommended_bloom_levels": decision.recommended_bloom_levels,
                "target_chunk_ids": decision.target_chunk_ids,
                "target_concepts": decision.target_concepts,
                "allow_llm": decision.allow_llm,
                "prefer_template": decision.prefer_template,
                "retry_strategy": decision.retry_strategy,
                "retry_count": retry_count,
            },
            target_count=target_count,
            latest_attempt=attempt_payload,
        )

        return {
            "attempt_id": attempt_id,
            "evaluation": {
                "accuracy": evaluation.accuracy,
                "total_questions": evaluation.total_questions,
                "correct_count": evaluation.correct_count,
                "wrong_count": evaluation.wrong_count,
                "average_confidence": evaluation.average_confidence,
                "wrong_by_chunk": evaluation.wrong_by_chunk,
                "wrong_by_concept": evaluation.wrong_by_concept,
                "wrong_by_difficulty": evaluation.wrong_by_difficulty,
                "fail_streak": evaluation.fail_streak,
                "success_streak": evaluation.success_streak,
                "trend": evaluation.trend,
            },
            "updated_mastery": mastery_update.new_lesson_mastery,
            "state": persisted_state,
            "next_action": {
                "type": decision.next_action,
                "recommended_difficulty": decision.recommended_difficulty,
                "recommended_bloom_levels": decision.recommended_bloom_levels,
                "target_chunk_ids": decision.target_chunk_ids,
                "target_concepts": decision.target_concepts,
                "allow_llm": decision.allow_llm,
                "prefer_template": decision.prefer_template,
                "retry_strategy": decision.retry_strategy,
                "retry_count": retry_count,
                "weakest_concept": weakest_concept,
                "fail_streak": decision.fail_streak,
                "success_streak": decision.success_streak,
                "reason": decision.reason,
            },
            "next_quiz": next_quiz,
            "lesson_completion_ready": bool(
                evaluation.accuracy >= 0.75 and mastery_update.new_lesson_mastery >= 0.7
            ),
        }

    def build_next_quiz_request(
        self,
        *,
        user_id: str,
        lesson_id: str,
        target_count: int,
    ) -> Dict[str, Any]:
        lesson = self.lesson_repository.get_by_id(lesson_id)
        subject_id = str(lesson.get("subject_id") or "") if lesson else ""
        state = self.learning_state_repository.get_state(
            user_id=user_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
        ) or {
            "chunk_mastery": {},
            "concept_mastery": {},
            "lesson_mastery": 0.0,
            "success_rate": 0.0,
        }

        decision = {
            "recommended_difficulty": str(state.get("last_difficulty") or "beginner"),
            "recommended_bloom_levels": ["remember", "understand"],
            "target_chunk_ids": [
                chunk_id
                for chunk_id, _ in sorted(
                    (state.get("chunk_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ],
            "target_concepts": [
                concept_id
                for concept_id, _ in sorted(
                    (state.get("concept_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ],
            "allow_llm": bool(float(state.get("lesson_mastery", 0.0) or 0.0) >= 0.7),
            "prefer_template": bool(float(state.get("lesson_mastery", 0.0) or 0.0) < 0.7),
            "retry_strategy": "same_question",
            "retry_count": 1,
        }

        latest_attempt = self.attempt_repository.latest_attempt(
            user_id=user_id,
            lesson_id=lesson_id,
        )

        return adaptive_question_selector.select_next(
            lesson_id=lesson_id,
            learning_state=state,
            attempt_evaluation={"accuracy": float(state.get("last_accuracy", 0.0) or 0.0)},
            decision=decision,
            target_count=target_count,
            latest_attempt=latest_attempt,
        )

    @staticmethod
    def _resolve_latest_difficulty(
        questions: List[Dict[str, Any]],
        previous_state: Optional[Dict[str, Any]],
    ) -> str:
        for item in questions or []:
            difficulty = str(item.get("difficulty") or "").strip().lower()
            if difficulty in {"beginner", "intermediate", "advanced"}:
                return difficulty
        if previous_state:
            fallback = str(previous_state.get("last_difficulty") or "").strip().lower()
            if fallback in {"beginner", "intermediate", "advanced"}:
                return fallback
        return "beginner"

    @staticmethod
    def _normalize_questions(
        questions: List[Dict[str, Any]],
        fallback_concepts: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        fallback_concepts = list(fallback_concepts or [])
        for item in questions or []:
            question_id = str(item.get("question_id") or "").strip()
            if not question_id:
                continue
            selected_answer = str(item.get("user_answer") or item.get("selected_answer") or "").strip()
            correct_answer = str(item.get("correct_answer") or "").strip()
            confidence_score = item.get("confidence_score")
            if confidence_score is None:
                confidence_score = item.get("confidence")
            question_text = str(item.get("question") or "").strip()
            concept_id = str(item.get("concept_id") or "").strip().lower()
            if not concept_id:
                concept_id = concept_extraction_service.detect_question_concept(
                    question_text=question_text,
                    chunk_text=" ".join(fallback_concepts),
                )
            normalized.append(
                {
                    "question_id": question_id,
                    "chunk_id": str(item.get("chunk_id") or "").strip(),
                    "concept_id": concept_id or None,
                    "difficulty": str(item.get("difficulty") or "beginner").strip().lower(),
                    "bloom_level": str(item.get("bloom_level") or "remember").strip().lower(),
                    "is_correct": bool(item.get("is_correct")),
                    "selected_answer": selected_answer,
                    "user_answer": selected_answer,
                    "correct_answer": correct_answer,
                    "question": question_text,
                    "confidence_score": float(confidence_score or 0.0),
                }
            )
        return normalized

    @staticmethod
    def _resolve_weakest_concept(
        *,
        evaluation_wrong: List[tuple[str, int]],
        concept_mastery: Dict[str, float],
    ) -> str:
        if evaluation_wrong:
            return str(evaluation_wrong[0][0])
        if concept_mastery:
            return min(
                concept_mastery.items(),
                key=lambda pair: float(pair[1]),
            )[0]
        return ""


adaptive_learning_service = AdaptiveLearningService()
