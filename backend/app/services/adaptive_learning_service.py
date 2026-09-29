"""Closed-loop adaptive learning orchestration service."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db
from backend.app.repositories import (
    AdaptiveAttemptRepository,
    AdaptiveEventRepository,
    LessonRepository,
    LessonRecommendedChunkRepository,
    ResourceChunkRepository,
    UserLearningStateRepository,
)
from backend.app.services.adaptive_decision_service import adaptive_decision_service
from backend.app.services.adaptive_question_selector import adaptive_question_selector
from backend.app.services.concept_extraction_service import concept_extraction_service
from backend.app.services.lesson_assessment_sizing_service import (
    lesson_assessment_sizing_service,
)
from backend.app.services.lesson_mastery_service import lesson_mastery_service
from backend.app.services.mastery_update_service import mastery_update_service
from backend.app.services.progress_evaluation_service import progress_evaluation_service
from backend.app.services.retry_strategy_service import retry_strategy_service

logger = logging.getLogger(__name__)
ADAPTIVE_QUIZ_LLM_ENABLED = (
    os.getenv("ADAPTIVE_QUIZ_LLM_ENABLED", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)


class AdaptiveLearningService:
    """Coordinate evaluate -> mastery update -> decision -> persistence."""

    POLICY_VERSION = "adaptive_quiz_policy_v1"

    def __init__(self) -> None:
        db = get_db()
        self.lesson_repository = LessonRepository()
        self.recommendation_repository = LessonRecommendedChunkRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.attempt_repository = AdaptiveAttemptRepository(db)
        self.learning_state_repository = UserLearningStateRepository(db)
        self.adaptive_event_repository = AdaptiveEventRepository(db)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _resolve_attempt_type(self, questions: List[Dict[str, Any]]) -> str:
        for question in questions or []:
            metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
            if bool(metadata.get("adaptive_quiz")) or str(
                metadata.get("generation_reason") or ""
            ).strip().lower() == "adaptive_quiz_next":
                return "adaptive_quiz_attempt"
        return "lesson_completion_attempt"

    def _build_policy_context(
        self,
        *,
        normalized_questions: List[Dict[str, Any]],
        concept_mastery: Dict[str, float],
        weakest_concept: str,
        submitted_confidence: float | None,
        lesson_mastery: float,
    ) -> Dict[str, Any]:
        average_confidence = self._safe_float(submitted_confidence, 0.0)
        if not average_confidence and normalized_questions:
            average_confidence = sum(
                self._safe_float(item.get("confidence_score"), 0.0)
                for item in normalized_questions
            ) / max(len(normalized_questions), 1)

        target_concepts = [
            concept_id
            for concept_id, _score in sorted(
                (concept_mastery or {}).items(),
                key=lambda pair: float(pair[1]),
            )[:3]
        ]
        if weakest_concept and weakest_concept not in target_concepts:
            target_concepts.insert(0, weakest_concept)
        target_concepts = [item for item in target_concepts if str(item).strip()]

        weakest_mastery = self._safe_float(
            (concept_mastery or {}).get(weakest_concept),
            lesson_mastery,
        )
        average_confidence = max(0.0, min(1.0, average_confidence))

        if weakest_mastery < 0.45 and average_confidence < 0.55:
            return {
                "policy_bucket": "review_easy_quiz",
                "next_action": "review_same_chunk",
                "recommended_difficulty": "beginner",
                "recommended_bloom_levels": ["remember", "understand"],
                "allow_llm": False,
                "prefer_template": True,
                "question_types": ["multiple_choice"],
                "target_concepts": target_concepts[:2],
                "why_this_quiz": (
                    "Low mastery combined with low confidence indicates remediation. "
                    "The quiz is simplified and focused on review before advancement."
                ),
            }

        if weakest_mastery < 0.75 and average_confidence < 0.7:
            return {
                "policy_bucket": "practice_similar_concepts",
                "next_action": "practice_similar_concepts",
                "recommended_difficulty": (
                    "intermediate" if lesson_mastery >= 0.6 else "beginner"
                ),
                "recommended_bloom_levels": ["understand", "apply"],
                "allow_llm": False,
                "prefer_template": True,
                "question_types": ["multiple_choice"],
                "target_concepts": target_concepts[:3],
                "why_this_quiz": (
                    "Mastery is improving but confidence is still weak. "
                    "The quiz keeps practice close to the same concepts until the learner stabilizes."
                ),
            }

        return {
            "policy_bucket": "advance_or_challenge",
            "next_action": (
                "advance_to_next_lesson"
                if lesson_mastery >= 0.7
                else "increase_difficulty"
            ),
            "recommended_difficulty": (
                "advanced" if lesson_mastery >= 0.8 and average_confidence >= 0.8 else "intermediate"
            ),
            "recommended_bloom_levels": ["apply", "analyze"],
            "allow_llm": True,
            "prefer_template": False,
            "question_types": ["multiple_choice"],
            "target_concepts": target_concepts[:2],
            "why_this_quiz": (
                "Mastery and confidence are strong enough to move beyond basic recall. "
                "The quiz increases challenge or prepares the learner to advance."
            ),
        }

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
        lesson_concepts = self._resolve_lesson_concepts(lesson, questions)

        normalized_questions = self._normalize_questions(
            questions,
            fallback_concepts=lesson_concepts,
        )

        recent_attempts = self.attempt_repository.get_recent_attempts(
            user_id=user_id,
            lesson_id=lesson_id,
            path_id=path_id,
            k=3,
        )
        evaluation = progress_evaluation_service.evaluate_attempt(
            normalized_questions,
            recent_attempts=recent_attempts,
        )
        lesson_assessment = lesson_mastery_service.evaluate_lesson_attempt(
            questions=normalized_questions,
            lesson_concepts=lesson_concepts,
            critical_concepts=self._resolve_critical_concepts(
                lesson=lesson,
                normalized_questions=normalized_questions,
            ),
            submitted_confidence=submitted_confidence,
        )

        previous_state = self.learning_state_repository.get_state(
            user_id=user_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            path_id=path_id,
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
        attempt_type = self._resolve_attempt_type(normalized_questions)
        policy_context = self._build_policy_context(
            normalized_questions=normalized_questions,
            concept_mastery=mastery_update.concept_mastery,
            weakest_concept=weakest_concept,
            submitted_confidence=submitted_confidence,
            lesson_mastery=mastery_update.new_lesson_mastery,
        )
        recommended_difficulty = str(
            policy_context.get("recommended_difficulty")
            or decision.recommended_difficulty
            or "beginner"
        )
        recommended_bloom_levels = list(
            policy_context.get("recommended_bloom_levels")
            or decision.recommended_bloom_levels
            or ["remember", "understand"]
        )
        target_concepts = list(
            policy_context.get("target_concepts")
            or decision.target_concepts
            or ([weakest_concept] if weakest_concept else [])
        )
        allow_llm = bool(
            policy_context.get("allow_llm")
            if policy_context.get("allow_llm") is not None
            else decision.allow_llm
        )
        prefer_template = bool(
            policy_context.get("prefer_template")
            if policy_context.get("prefer_template") is not None
            else decision.prefer_template
        )
        next_action = str(policy_context.get("next_action") or decision.next_action)
        question_types = list(
            policy_context.get("question_types")
            or ["multiple_choice"]
        )
        why_this_quiz = str(
            policy_context.get("why_this_quiz") or decision.reason
        ).strip()
        policy_bucket = str(policy_context.get("policy_bucket") or "default")
        next_quiz_target_count = max(1, int(target_count))

        if not lesson_assessment.completed:
            weak_targets = list(lesson_assessment.weak_concepts or target_concepts)
            if weakest_concept and weakest_concept not in weak_targets:
                weak_targets.insert(0, weakest_concept)
            target_concepts = [item for item in weak_targets if str(item).strip()][:3]
            recommended_difficulty = lesson_mastery_service.lower_difficulty(
                recommended_difficulty
            )
            recommended_bloom_levels = ["understand", "apply"]
            question_types = ["multiple_choice"]
            allow_llm = False
            prefer_template = True
            next_action = "reinforcement_quiz"
            next_quiz_target_count = min(5, max(3, len(target_concepts) + 1))
            policy_bucket = f"lesson_{lesson_assessment.completion_status}"
            why_this_quiz = (
                "Reinforcement quiz targets weak concepts with easier questions and "
                "prioritizes understand/apply practice."
            )

        if weakest_concept and next_action in {
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
            "attempt_type": attempt_type,
            "policy_version": self.POLICY_VERSION,
            "policy_bucket": policy_bucket,
            "target_concepts": target_concepts,
            "recommended_difficulty": recommended_difficulty,
            "recommended_bloom_levels": recommended_bloom_levels,
            "question_types": question_types,
            "why_this_quiz": why_this_quiz,
            "mastery_score": lesson_assessment.mastery_score,
            "completion_status": lesson_assessment.completion_status,
            "reinforce_required": lesson_assessment.reinforce_required,
            "retry_required": lesson_assessment.retry_required,
            "bloom_score": lesson_assessment.bloom_score,
            "bloom_accuracy_by_level": lesson_assessment.bloom_accuracy_by_level,
            "concept_coverage_score": lesson_assessment.concept_coverage_score,
            "difficulty_weighted_score": lesson_assessment.difficulty_weighted_score,
            "confidence_score": lesson_assessment.confidence_score,
            "weak_concepts": lesson_assessment.weak_concepts,
            "critical_concepts": lesson_assessment.critical_concepts,
            "critical_concept_failure": lesson_assessment.critical_concept_failure,
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
            "path_id": str(path_id),
            "chunk_mastery": mastery_update.chunk_mastery,
            "concept_mastery": mastery_update.concept_mastery,
            "lesson_mastery": mastery_update.new_lesson_mastery,
            "success_rate": mastery_update.success_rate,
            "total_attempts": mastery_update.total_attempts,
            "last_difficulty": recommended_difficulty,
            "recommended_next_action": next_action,
            "last_accuracy": evaluation.accuracy,
            "retry_count_by_concept": retry_count_by_concept,
            "recent_attempt_ids": recent_attempt_ids,
            "last_policy_version": self.POLICY_VERSION,
            "last_policy_bucket": policy_bucket,
            "last_question_types": question_types,
            "last_why_this_quiz": why_this_quiz,
            "last_attempt_type": attempt_type,
            "last_mastery_score": lesson_assessment.mastery_score,
            "last_completion_status": lesson_assessment.completion_status,
            "needs_reinforcement": lesson_assessment.reinforce_required,
            "weak_concepts": lesson_assessment.weak_concepts,
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
            "decision": next_action,
            "reason": decision.reason,
            "recommended_difficulty": recommended_difficulty,
            "recommended_bloom_levels": recommended_bloom_levels,
            "target_chunk_ids": decision.target_chunk_ids,
            "target_concepts": target_concepts,
            "retry_strategy": decision.retry_strategy,
            "fail_streak": decision.fail_streak,
            "success_streak": decision.success_streak,
            "policy_version": self.POLICY_VERSION,
            "policy_bucket": policy_bucket,
            "why_this_quiz": why_this_quiz,
            "attempt_type": attempt_type,
            "mastery_score": lesson_assessment.mastery_score,
            "completion_status": lesson_assessment.completion_status,
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
            next_action,
            decision.reason,
            recommended_difficulty,
            recommended_bloom_levels,
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
                "recommended_difficulty": recommended_difficulty,
                "recommended_bloom_levels": recommended_bloom_levels,
                "target_chunk_ids": decision.target_chunk_ids,
                "target_concepts": target_concepts,
                "allow_llm": allow_llm,
                "prefer_template": prefer_template,
                "retry_strategy": decision.retry_strategy,
                "retry_count": retry_count,
                "question_types": question_types,
                "policy_version": self.POLICY_VERSION,
                "policy_bucket": policy_bucket,
                "why_this_quiz": why_this_quiz,
            },
            target_count=next_quiz_target_count,
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
            "lesson_assessment": {
                "accuracy": lesson_assessment.accuracy,
                "mastery_score": lesson_assessment.mastery_score,
                "completion_status": lesson_assessment.completion_status,
                "completed": lesson_assessment.completed,
                "reinforce_required": lesson_assessment.reinforce_required,
                "retry_required": lesson_assessment.retry_required,
                "bloom_score": lesson_assessment.bloom_score,
                "bloom_accuracy_by_level": lesson_assessment.bloom_accuracy_by_level,
                "concept_coverage_score": lesson_assessment.concept_coverage_score,
                "difficulty_weighted_score": lesson_assessment.difficulty_weighted_score,
                "confidence_score": lesson_assessment.confidence_score,
                "weak_concepts": lesson_assessment.weak_concepts,
                "critical_concepts": lesson_assessment.critical_concepts,
                "critical_concept_failure": lesson_assessment.critical_concept_failure,
            },
            "state": persisted_state,
            "next_action": {
                "type": next_action,
                "recommended_difficulty": recommended_difficulty,
                "recommended_bloom_levels": recommended_bloom_levels,
                "target_chunk_ids": decision.target_chunk_ids,
                "target_concepts": target_concepts,
                "allow_llm": allow_llm,
                "prefer_template": prefer_template,
                "retry_strategy": decision.retry_strategy,
                "retry_count": retry_count,
                "weakest_concept": weakest_concept,
                "fail_streak": decision.fail_streak,
                "success_streak": decision.success_streak,
                "reason": decision.reason,
                "policy_version": self.POLICY_VERSION,
                "policy_bucket": policy_bucket,
                "question_types": question_types,
                "why_this_quiz": why_this_quiz,
                "attempt_type": attempt_type,
            },
            "next_quiz": next_quiz,
            "lesson_completion_ready": bool(
                evaluation.accuracy >= 0.75 and mastery_update.new_lesson_mastery >= 0.7
            ),
        }

    def _resolve_adaptive_quiz_scope(
        self,
        *,
        lesson_id: str,
        lesson: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        lesson = lesson or {}
        recommendation = self.recommendation_repository.get_by_lesson(lesson_id) or {}
        recommended_chunks = list(recommendation.get("recommended_chunks") or [])

        raw_chunk_ids: List[str] = []
        for item in recommended_chunks:
            if isinstance(item, dict):
                chunk_id = item.get("chunk_id") or item.get("_id")
                if chunk_id:
                    raw_chunk_ids.append(str(chunk_id))
        raw_chunk_ids.extend(str(item) for item in recommendation.get("chunk_ids") or [])
        raw_chunk_ids.extend(str(item) for item in lesson.get("recommended_chunk_ids") or [])

        chunk_ids: List[str] = []
        seen_chunk_ids: set[str] = set()
        for chunk_id in raw_chunk_ids:
            normalized = str(chunk_id or "").strip()
            if not normalized or normalized in seen_chunk_ids:
                continue
            seen_chunk_ids.add(normalized)
            chunk_ids.append(normalized)

        chunks = self.chunk_repository.get_by_ids(chunk_ids) if chunk_ids else []

        concept_values: List[str] = []
        lesson_metadata = (
            lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        )
        for value in (
            lesson_metadata.get("main_concept"),
            lesson.get("topic"),
        ):
            if value:
                concept_values.append(str(value))
        for source in (
            lesson_metadata.get("covered_concepts"),
            lesson_metadata.get("keywords"),
            lesson.get("learning_objectives"),
            lesson.get("keywords"),
        ):
            if isinstance(source, list):
                concept_values.extend(str(item) for item in source)
        for item in recommended_chunks:
            if not isinstance(item, dict):
                continue
            concept_values.extend(str(value) for value in item.get("covered_concepts") or [])
        for chunk in chunks:
            chunk_metadata = (
                chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            )
            concept_values.extend(
                str(item)
                for item in (
                    chunk.get("covered_concepts")
                    or chunk_metadata.get("covered_concepts")
                    or []
                )
            )

        concepts = lesson_assessment_sizing_service._normalize_concepts(concept_values)

        estimated_learning_time = 0.0
        for item in recommended_chunks:
            if not isinstance(item, dict):
                continue
            estimated_learning_time += float(item.get("estimated_read_time") or 0.0)
        if estimated_learning_time <= 0:
            for chunk in chunks:
                chunk_metadata = (
                    chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
                )
                estimated_learning_time += float(
                    chunk.get("estimated_read_time")
                    or chunk_metadata.get("estimated_read_time")
                    or 0.0
                )
        if estimated_learning_time <= 0:
            estimated_learning_time = float(
                lesson_metadata.get("estimated_read_time")
                or lesson_metadata.get("estimated_learning_time")
                or 0.0
            )
        estimated_learning_time = (
            max(1, int(round(estimated_learning_time)))
            if estimated_learning_time > 0
            else max(1, len(chunk_ids) * 4)
        )

        total_token_length = sum(
            max(1, int(round(len(str(chunk.get("content") or "").split()) * 1.3)))
            for chunk in chunks
            if str(chunk.get("content") or "").strip()
        )

        plan = lesson_assessment_sizing_service.build_quiz_plan(
            chunk_count=len(chunk_ids),
            total_token_length=total_token_length,
            concept_count=len(concepts),
            estimated_learning_time=estimated_learning_time,
            concepts=concepts,
            mastery=None,
            requested_target_count=None,
        )
        return {
            "plan": plan,
            "chunk_ids": chunk_ids,
            "concepts": concepts,
        }

    def build_next_quiz_request(
        self,
        *,
        user_id: str,
        lesson_id: str,
        path_id: Optional[str] = None,
        target_count: Optional[int],
    ) -> Dict[str, Any]:
        if not path_id:
            logger.debug(
                "[AdaptiveQuiz] build_next_quiz_request called without path_id for user=%s lesson=%s",
                user_id,
                lesson_id,
            )
        lesson = self.lesson_repository.get_by_id(lesson_id)
        subject_id = str(lesson.get("subject_id") or "") if lesson else ""
        quiz_scope = self._resolve_adaptive_quiz_scope(
            lesson_id=lesson_id,
            lesson=lesson,
        )
        lesson_plan = quiz_scope["plan"]
        state = self.learning_state_repository.get_state(
            user_id=user_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            path_id=path_id,
        ) or {
            "chunk_mastery": {},
            "concept_mastery": {},
            "lesson_mastery": 0.0,
            "success_rate": 0.0,
        }
        lesson_mastery = float(state.get("lesson_mastery", 0.0) or 0.0)
        resolved_target_count = (
            max(1, int(target_count))
            if target_count is not None
            else int(lesson_plan.target_count_auto)
        )
        auto_bloom_levels = [
            level
            for level in ("remember", "understand", "apply", "analyze")
            if int(lesson_plan.bloom_distribution.get("counts", {}).get(level, 0) or 0) > 0
        ] or ["remember", "understand", "apply"]
        fallback_chunk_ids = list(quiz_scope.get("chunk_ids") or [])[:6]
        fallback_concepts = list(quiz_scope.get("concepts") or [])[:6]
        default_question_types = (
            ["multiple_choice"]
            if lesson_plan.lesson_size in {"medium", "large"}
            else ["multiple_choice"]
        )
        policy_bucket = str(
            state.get("last_policy_bucket")
            or f"lesson_{lesson_plan.lesson_size}_adaptive"
        )
        why_this_quiz = str(
            state.get("last_why_this_quiz")
            or (
                f"Quiz này bám theo quy mô lesson {lesson_plan.lesson_size}, "
                f"ưu tiên {resolved_target_count} câu để phủ concept chính và cập nhật mastery chính xác hơn."
            )
        )

        decision = {
            "recommended_difficulty": str(
                state.get("last_difficulty")
                or (
                    "intermediate"
                    if lesson_plan.lesson_size in {"medium", "large"}
                    and lesson_mastery >= 0.45
                    else "beginner"
                )
            ),
            "recommended_bloom_levels": list(
                state.get("last_recommended_bloom_levels") or auto_bloom_levels
            ),
            "target_chunk_ids": [
                chunk_id
                for chunk_id, _ in sorted(
                    (state.get("chunk_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ]
            or fallback_chunk_ids,
            "target_concepts": [
                concept_id
                for concept_id, _ in sorted(
                    (state.get("concept_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ]
            or fallback_concepts,
            "allow_llm": bool(
                ADAPTIVE_QUIZ_LLM_ENABLED
                and (
                    lesson_plan.lesson_size in {"medium", "large"}
                    or lesson_mastery >= 0.55
                )
            ),
            "prefer_template": bool(
                lesson_plan.lesson_size == "small" and lesson_mastery < 0.45
            ),
            "retry_strategy": "paraphrase_question",
            "retry_count": 1,
            "question_types": list(state.get("last_question_types") or default_question_types),
            "policy_version": str(state.get("last_policy_version") or self.POLICY_VERSION),
            "policy_bucket": policy_bucket,
            "why_this_quiz": why_this_quiz,
        }

        latest_attempt = self.attempt_repository.latest_attempt(
            user_id=user_id,
            lesson_id=lesson_id,
            path_id=path_id,
        )

        return adaptive_question_selector.select_next(
            lesson_id=lesson_id,
            learning_state=state,
            attempt_evaluation={"accuracy": float(state.get("last_accuracy", 0.0) or 0.0)},
            decision=decision,
            target_count=resolved_target_count,
            latest_attempt=latest_attempt,
        )

    @staticmethod
    def _resolve_lesson_concepts(
        lesson: Optional[Dict[str, Any]],
        questions: List[Dict[str, Any]],
    ) -> List[str]:
        lesson = lesson or {}
        metadata = lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        extracted = concept_extraction_service.extract_from_texts(
            [
                str(lesson.get("title") or ""),
                str(lesson.get("summary") or ""),
                " ".join(str(item.get("concept_id") or "") for item in questions or []),
            ]
        )
        lesson_concepts = [
            str(metadata.get("main_concept") or ""),
            str(lesson.get("topic") or ""),
            *[str(item) for item in metadata.get("covered_concepts") or []],
            *[str(item) for item in lesson.get("learning_objectives") or []],
            *[str(item) for item in lesson.get("keywords") or []],
            *[str(item) for item in extracted or []],
        ]
        return lesson_assessment_sizing_service._normalize_concepts(lesson_concepts)

    @staticmethod
    def _resolve_critical_concepts(
        *,
        lesson: Optional[Dict[str, Any]],
        normalized_questions: List[Dict[str, Any]],
    ) -> List[str]:
        lesson = lesson or {}
        metadata = lesson.get("metadata") if isinstance(lesson.get("metadata"), dict) else {}
        question_concepts = [
            str(item.get("concept_id") or "")
            for item in normalized_questions or []
            if item.get("concept_id")
        ]
        critical = [
            str(metadata.get("main_concept") or ""),
            str(lesson.get("topic") or ""),
            *[str(item) for item in metadata.get("covered_concepts") or []],
            *question_concepts,
        ]
        return lesson_assessment_sizing_service._normalize_concepts(critical)[:5]

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
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            concept_id = str(item.get("concept_id") or "").strip().lower()
            if not concept_id:
                metadata_candidates: List[str] = []
                for key in (
                    "matched_target_concepts",
                    "target_concepts",
                    "covered_concepts",
                ):
                    for value in metadata.get(key) or []:
                        metadata_candidates.append(str(value))
                for key in ("concept_focus", "question_focus"):
                    if metadata.get(key):
                        metadata_candidates.append(str(metadata.get(key)))
                normalized_metadata_candidates = lesson_assessment_sizing_service._normalize_concepts(
                    metadata_candidates
                )
                if normalized_metadata_candidates:
                    concept_id = normalized_metadata_candidates[0]
            if not concept_id:
                concept_id = concept_extraction_service.detect_question_concept(
                    question_text=question_text,
                    chunk_text=" ".join(
                        [
                            *fallback_concepts,
                            *(
                                metadata.get("matched_target_concepts")
                                if isinstance(metadata.get("matched_target_concepts"), list)
                                else []
                            ),
                            *(
                                metadata.get("target_concepts")
                                if isinstance(metadata.get("target_concepts"), list)
                                else []
                            ),
                        ]
                    ),
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
