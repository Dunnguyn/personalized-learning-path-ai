"""Hybrid learning path generation service for subject -> chapter -> lesson flows."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from backend.app.ai_module import CurriculumLLMClient
from backend.app.database.mongo import get_db
from backend.app.repositories import (
    ChapterRepository,
    LearningPathRepository,
    LessonRecommendedChunkRepository,
    LessonRepository,
    LessonQuestionRepository,
    ResourceRepository,
    SubjectRepository,
)
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.learning_path_prompt_builder import (
    build_fallback_curriculum,
    build_learning_path_prompt,
    extract_json_object,
    get_subject_label,
    normalize_curriculum,
)
from backend.app.services.embedding_service import cosine_similarity, embed_text
from backend.app.services.lesson_completion_engine import lesson_completion_engine
from backend.app.services.adaptive_learning_service import adaptive_learning_service

from backend.app.services.exercise_logging_service import exercise_logging_service
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.prerequisite_resolver import prerequisite_resolver

logger = logging.getLogger(__name__)


class HybridLearningPathService:
    """Generate subject-scoped curricula and freeze lesson chunk recommendations locally."""

    def __init__(self) -> None:
        self.subject_repository = SubjectRepository()
        self.chapter_repository = ChapterRepository()
        self.lesson_repository = LessonRepository()
        self.learning_path_repository = LearningPathRepository()
        self.lesson_recommended_chunk_repository = LessonRecommendedChunkRepository()
        self.question_repository = LessonQuestionRepository()
        self.resource_repository = ResourceRepository()
        self.lesson_chunk_service = lesson_chunk_service
        self.llm_client = CurriculumLLMClient()
        self.max_chunks_per_lesson = int(
            os.getenv("LEARNING_PATH_MAX_CHUNKS_PER_LESSON", "8")
        )
        self.max_seed_resources_per_lesson = int(
            os.getenv("LEARNING_PATH_MAX_SEED_RESOURCES_PER_LESSON", "8")
        )
        self.precompute_recommendations_on_generate = (
            os.getenv("LEARNING_PATH_PRECOMPUTE_RECOMMENDATIONS_ON_GENERATE", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )

        self.subject_repository.ensure_indexes()
        self.chapter_repository.ensure_indexes()
        self.lesson_repository.ensure_indexes()
        self.learning_path_repository.ensure_indexes()

    def generate_learning_path(
        self,
        *,
        subject_id: str,
        goal: str,
        level: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a learning path and precompute lesson-scoped recommended chunks."""
        normalized_subject_id = (subject_id or "").strip().lower()
        normalized_goal = (goal or "").strip()
        normalized_level = (level or "").strip().lower()

        self._validate_inputs(
            subject_id=normalized_subject_id,
            goal=normalized_goal,
            level=normalized_level,
        )
        subject_label = get_subject_label(normalized_subject_id) or ""
        llm_status = self.llm_client.status()

        logger.info(
            "Generating hybrid learning path: subject_id=%s goal=%s level=%s user_id=%s llm_enabled=%s",
            normalized_subject_id,
            normalized_goal,
            normalized_level,
            user_id,
            llm_status.get("enabled"),
        )

        curriculum_source = "fallback"
        curriculum = self._generate_curriculum(
            subject_id=normalized_subject_id,
            subject_label=subject_label,
            goal=normalized_goal,
            level=normalized_level,
        )
        if curriculum["source"] == "ai":
            curriculum_source = "ai"
        llm_status = curriculum["llm_status"]

        path_id = uuid.uuid4().hex
        subject = self._ensure_subject(
            subject_id=normalized_subject_id,
            subject_label=subject_label,
            level=normalized_level,
        )

        chapter_responses: List[Dict[str, Any]] = []
        lesson_progress: Dict[str, str] = {}
        lesson_confidence_log: Dict[str, Dict[str, Any]] = {}
        used_resource_ids_across_path: set[str] = set()
        total_lessons = 0
        for chapter_index, chapter_payload in enumerate(
            curriculum["chapters"], start=1
        ):
            chapter = self.chapter_repository.create(
                {
                    "subject_id": subject["_id"],
                    "title": chapter_payload["title"],
                    "description": f"Learning path chapter for goal: {normalized_goal}",
                    "order": chapter_index,
                    "topic": normalized_subject_id,
                    "metadata": {
                        "learning_path_id": path_id,
                        "subject_key": normalized_subject_id,
                        "goal": normalized_goal,
                        "level": normalized_level,
                        "generated_by": "hybrid_learning_path_service",
                    },
                }
            )

            lesson_responses: List[Dict[str, Any]] = []
            for lesson_index, lesson_payload in enumerate(
                chapter_payload["lessons"], start=1
            ):
                lesson_keywords = self._build_keywords(
                    subject_label=subject_label,
                    chapter_title=chapter_payload["title"],
                    lesson_title=lesson_payload["title"],
                    lesson_summary=lesson_payload["summary"],
                    goal=normalized_goal,
                )
                seed_resource_ids = self._select_resource_ids_for_lesson(
                    subject_id=normalized_subject_id,
                    subject_label=subject_label,
                    chapter_title=chapter_payload["title"],
                    lesson_title=lesson_payload["title"],
                    lesson_summary=lesson_payload["summary"],
                    goal=normalized_goal,
                    level=normalized_level,
                    limit=self.max_seed_resources_per_lesson,
                    avoid_resource_ids=list(used_resource_ids_across_path),
                )
                lesson = self.lesson_repository.create(
                    {
                        "subject_id": subject["_id"],
                        "chapter_id": chapter["_id"],
                        "title": lesson_payload["title"],
                        "summary": lesson_payload["summary"],
                        "order": lesson_index,
                        "topic": normalized_subject_id,
                        "level": normalized_level,
                        "learning_objectives": [lesson_payload["summary"]],
                        "keywords": lesson_keywords,
                        "resource_ids": seed_resource_ids,
                        "metadata": {
                            "learning_path_id": path_id,
                            "subject_key": normalized_subject_id,
                            "goal": normalized_goal,
                            "level": normalized_level,
                            "generated_by": "hybrid_learning_path_service",
                            "curriculum_source": curriculum_source,
                            "lesson_anchor_phrases": lesson_keywords,
                            "seed_resource_ids": seed_resource_ids,
                            "avoid_resource_ids": list(used_resource_ids_across_path),
                        },
                    }
                )

                recommendation = self._recommend_chunks_for_lesson(
                    lesson=lesson,
                    chapter=chapter,
                    subject=subject,
                    goal=normalized_goal,
                    level=normalized_level,
                    path_id=path_id,
                )
                recommended_chunk_ids = recommendation.get("chunk_ids", [])
                recommended_resource_ids = recommendation.get("resource_ids", [])
                used_resource_ids_across_path.update(
                    str(resource_id)
                    for resource_id in (recommended_resource_ids or seed_resource_ids)
                    if resource_id
                )
                self.lesson_repository.update(
                    lesson["_id"],
                    {
                        "resource_ids": seed_resource_ids,
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "recommended_resource_ids": recommended_resource_ids,
                    },
                )

                total_lessons += 1
                lesson_progress[str(lesson["_id"])] = "not_started"
                lesson_confidence_log[str(lesson["_id"])] = {
                    "confidence": 0.0,
                    "updated_at": None,
                }
                logger.info(
                    "Lesson recommendation ready: lesson_id=%s chunks=%s resources=%s",
                    lesson["_id"],
                    len(recommended_chunk_ids),
                    len(recommended_resource_ids),
                )
                lesson_responses.append(
                    {
                        "lesson_id": str(lesson["_id"]),
                        "title": lesson["title"],
                        "summary": lesson.get("summary"),
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "status": "not_started",
                    }
                )

            chapter_responses.append(
                {
                    "chapter_id": str(chapter["_id"]),
                    "title": chapter["title"],
                    "lessons": lesson_responses,
                }
            )

        self.learning_path_repository.create(
            {
                "path_id": path_id,
                "user_id": user_id,
                "subject_id": normalized_subject_id,
                "subject_ref_id": subject["_id"],
                "subject_label": subject_label,
                "goal": normalized_goal,
                "level": normalized_level,
                "chapters": chapter_responses,
                "curriculum_source": curriculum_source,
                "llm_status": llm_status,
                "lesson_progress": lesson_progress,
                "lesson_confidence_log": lesson_confidence_log,
                "metadata": {
                    "pipeline": "hybrid_subject_lesson_v1",
                    "chapter_count": len(chapter_responses),
                    "lesson_count": total_lessons,
                },
            }
        )

        logger.info(
            "Hybrid learning path generated: path_id=%s chapters=%s lessons=%s subject_id=%s",
            path_id,
            len(chapter_responses),
            total_lessons,
            normalized_subject_id,
        )
        return {
            "path_id": path_id,
            "subject_id": normalized_subject_id,
            "goal": normalized_goal,
            "level": normalized_level,
            "generated_at": datetime.utcnow(),
            "chapters": chapter_responses,
            "curriculum_source": curriculum_source,
            "llm_status": llm_status,
            "message": f"Generated learning path with {len(chapter_responses)} chapters and {total_lessons} lessons.",
        }

    def get_learning_path(
        self, *, path_id: str, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Load a generated learning path with optional ownership validation."""
        normalized_path_id = (path_id or "").strip()
        if not normalized_path_id:
            raise ValueError("path_id is required")

        document = self.learning_path_repository.get_by_path_id(normalized_path_id)
        if not document:
            raise ValueError("Learning path not found.")

        owner_id = document.get("user_id")
        if user_id and owner_id and str(owner_id) != str(user_id):
            raise ValueError("Learning path not found.")

        return self._serialize_learning_path(document)

    def list_learning_paths(
        self, *, user_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """List learning paths for the current user across legacy and hybrid documents."""
        documents = list(
            self.learning_path_repository.collection.find({"user_id": user_id})
        )
        documents.sort(
            key=lambda item: self._resolve_generated_at(item),
            reverse=True,
        )
        serialized = [self._serialize_learning_path(item) for item in documents[:limit]]
        return serialized

    def delete_learning_path(self, *, path_id: str, user_id: str) -> Dict[str, Any]:
        """Delete a stored learning path and generated lesson/chapter artifacts owned by the user."""
        normalized_path_id = (path_id or "").strip()
        if not normalized_path_id:
            raise ValueError("path_id is required")

        document = self.learning_path_repository.get_by_path_id(normalized_path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found.")

        lesson_ids = {
            lesson.get("lesson_id")
            for chapter in document.get("chapters", [])
            for lesson in chapter.get("lessons", [])
            if lesson.get("lesson_id")
        }
        chapter_ids = {
            chapter.get("chapter_id")
            for chapter in document.get("chapters", [])
            if chapter.get("chapter_id")
        }

        generated_lessons = self.lesson_repository.list_by_learning_path(
            normalized_path_id
        )
        lesson_ids.update(
            str(item["_id"]) for item in generated_lessons if item.get("_id")
        )

        generated_chapters = self.chapter_repository.list_by_learning_path(
            normalized_path_id
        )
        chapter_ids.update(
            str(item["_id"]) for item in generated_chapters if item.get("_id")
        )

        lesson_id_list = sorted(lesson_ids)
        chapter_id_list = sorted(chapter_ids)

        removed_recommendations = (
            self.lesson_recommended_chunk_repository.delete_by_lesson_ids(
                lesson_id_list
            )
        )
        removed_questions = self.question_repository.delete_by_lesson_ids(
            lesson_id_list
        )
        removed_lessons = self.lesson_repository.delete_many(lesson_id_list)
        removed_chapters = self.chapter_repository.delete_many(chapter_id_list)
        deleted_paths = self.learning_path_repository.delete_by_path_id(
            normalized_path_id, user_id=user_id
        )

        if deleted_paths == 0:
            raise ValueError("Learning path not found.")

        return {
            "path_id": normalized_path_id,
            "deleted": True,
            "removed_lessons": removed_lessons,
            "removed_chapters": removed_chapters,
            "removed_recommendations": removed_recommendations,
            "removed_questions": removed_questions,
        }

    def update_lesson_progress(
        self,
        *,
        path_id: str,
        user_id: str,
        lesson_id: str,
        status: str,
        confidence: Optional[float] = None,
        questions_answered: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Update lesson progress with auto-completion and prerequisite enforcement.

        Args:
            path_id: Learning path ID
            user_id: User ID
            lesson_id: Lesson ID
            status: Desired status (will be overridden by auto-completion if applicable)
            confidence: Optional confidence score (triggers auto-completion if > 0.7)

        Returns:
            Dict with:
            - path_id: str
            - lesson_id: str
            - status: str (final status)
            - is_locked: bool
            - auto_completed: bool
            - reason_locked: Optional[str]
            - blocking_lesson_id: Optional[str]
            - updated_at: datetime
        """
        document = self.learning_path_repository.get_by_path_id(path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found.")

        normalized = self._serialize_learning_path(document)

        # Build lesson position map
        lesson_positions = {}  # lesson_id -> (chapter_idx, lesson_idx)
        for chapter_idx, chapter in enumerate(normalized.get("chapters", [])):
            for lesson_idx, lesson in enumerate(chapter.get("lessons", [])):
                lid = lesson.get("lesson_id")
                if lid:
                    lesson_positions[lid] = (chapter_idx, lesson_idx)

        if lesson_id not in lesson_positions:
            raise ValueError("Lesson not found in learning path.")

        chapter_idx, lesson_idx = lesson_positions[lesson_id]
        has_submitted_exercise = bool(questions_answered)

        lesson_confidence_log = document.get("lesson_confidence_log", {}) or {}
        stored_record = (
            lesson_confidence_log.get(lesson_id, {})
            if isinstance(lesson_confidence_log, dict)
            else {}
        )
        stored_confidence = 0.0
        if isinstance(stored_record, dict):
            try:
                stored_confidence = float(stored_record.get("confidence", 0.0) or 0.0)
            except Exception:
                stored_confidence = 0.0

        # Safety: always resolve confidence from this exact lesson attempt history only.
        # This prevents any accidental cross-lesson confidence reuse leading to auto-pass.
        lesson_best_confidence = None
        try:
            lesson_stats = exercise_logging_service.repository.get_attempt_statistics(
                user_id,
                lesson_id,
            )
            raw_best = (
                lesson_stats.get("best_confidence")
                if isinstance(lesson_stats, dict)
                else None
            )
            if raw_best is not None:
                lesson_best_confidence = float(raw_best)
                stored_confidence = max(stored_confidence, lesson_best_confidence)
        except Exception as exc:
            logger.warning(
                "Could not load lesson-specific best confidence: path=%s lesson=%s user=%s error=%s",
                path_id,
                lesson_id,
                user_id,
                exc,
            )

        # Confidence is lesson-scoped and can only change after submitting lesson exercises.
        if not has_submitted_exercise:
            confidence = None

        # If confidence not provided, try to fetch from stored confidence log
        if confidence is None and status == "completed":
            if isinstance(stored_record, dict) and "confidence" in stored_record:
                confidence = stored_confidence
                logger.info(
                    f"Using stored confidence for completion check: "
                    f"path={path_id}, lesson={lesson_id}, confidence={confidence:.2%}"
                )

        confidence_updated_at = (
            datetime.utcnow()
            if confidence is not None and has_submitted_exercise
            else None
        )

        def _persist_confidence_if_present() -> None:
            if confidence is None or not has_submitted_exercise:
                return
            self.learning_path_repository.collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        f"lesson_confidence_log.{lesson_id}.confidence": float(
                            confidence
                        ),
                        f"lesson_confidence_log.{lesson_id}.updated_at": confidence_updated_at,
                        "updated_at": confidence_updated_at,
                    }
                },
            )
            logger.info(
                "Saved latest confidence score: path=%s lesson=%s confidence=%.4f",
                path_id,
                lesson_id,
                float(confidence),
            )

        # Check if lesson is locked
        access_result = lesson_completion_engine.can_access_lesson(
            path_id=path_id,
            lesson_id=lesson_id,
            chapter_index=chapter_idx,
            lesson_index=lesson_idx,
            user_id=user_id,
        )

        # If locked, cannot start or complete
        if access_result["is_locked"]:
            _persist_confidence_if_present()
            logger.warning(
                f"Cannot access locked lesson: path={path_id}, lesson={lesson_id}, "
                f"reason={access_result['reason']}, status_attempted={status}"
            )
            return {
                "path_id": path_id,
                "lesson_id": lesson_id,
                "status": "locked",
                "is_locked": True,
                "auto_completed": False,
                "last_confidence": stored_confidence,
                "confidence_updated_at": (
                    stored_record.get("updated_at")
                    if isinstance(stored_record, dict)
                    else None
                ),
                "reason_locked": access_result["reason"],
                "blocking_lesson_id": access_result.get("blocking_lesson_id"),
                "blocking_concepts": list(access_result.get("blocking_concepts") or []),
                "missing_prerequisite_concepts": list(
                    access_result.get("missing_prerequisite_concepts") or []
                ),
                "prerequisite_mastery": dict(
                    access_result.get("prerequisite_mastery") or {}
                ),
                "bridge_recommendations": list(
                    access_result.get("bridge_recommendations") or []
                ),
                "mastery_threshold": access_result.get("mastery_threshold"),
                "updated_at": datetime.utcnow(),
            }

        final_status = status
        auto_completed = False
        adaptive_outcome = None
        lesson_assessment = {}

        if has_submitted_exercise and questions_answered:
            try:
                adaptive_outcome = adaptive_learning_service.process_attempt(
                    user_id=user_id,
                    lesson_id=lesson_id,
                    path_id=path_id,
                    questions=questions_answered,
                    submitted_confidence=confidence,
                    target_count=max(1, len(questions_answered)),
                )
            except Exception as exc:
                logger.error(
                    "Adaptive loop processing failed: path=%s lesson=%s user=%s error=%s",
                    path_id,
                    lesson_id,
                    user_id,
                    exc,
                )
                adaptive_outcome = None

        if adaptive_outcome and isinstance(adaptive_outcome.get("lesson_assessment"), dict):
            lesson_assessment = dict(adaptive_outcome.get("lesson_assessment") or {})

        submission_accuracy = 0.0
        if has_submitted_exercise and questions_answered:
            try:
                total_answered = len(questions_answered)
                correct_answered = sum(
                    1 for item in questions_answered if bool(item.get("is_correct"))
                )
                submission_accuracy = (
                    float(correct_answered) / float(total_answered)
                    if total_answered > 0
                    else 0.0
                )
            except Exception:
                submission_accuracy = 0.0

        completion_ready = bool(lesson_assessment.get("completed"))
        completion_mastery = (
            float(adaptive_outcome.get("updated_mastery") or 0.0)
            if adaptive_outcome
            else 0.0
        )
        completion_accuracy = float(
            lesson_assessment.get("accuracy", submission_accuracy) or submission_accuracy
        )
        mastery_score = (
            float(lesson_assessment.get("mastery_score") or 0.0)
            if lesson_assessment
            else None
        )
        completion_status = (
            str(lesson_assessment.get("completion_status") or "").strip() or None
        )
        reinforce_required = bool(lesson_assessment.get("reinforce_required"))
        retry_required = bool(lesson_assessment.get("retry_required"))

        if completion_ready:
            final_status = "completed"
            auto_completed = True
            logger.info(
                f"Auto-completing lesson due to mastery threshold: "
                f"path={path_id}, lesson={lesson_id}, "
                f"accuracy={completion_accuracy:.2%}, mastery_score={mastery_score}"
            )
        elif status == "completed":
            if has_submitted_exercise and questions_answered:
                _persist_confidence_if_present()
                logger.info(
                    f"Blocking completion with insufficient lesson mastery: "
                    f"path={path_id}, lesson={lesson_id}, "
                    f"accuracy={completion_accuracy:.2%}, mastery_score={mastery_score}"
                )
                return {
                    "path_id": path_id,
                    "lesson_id": lesson_id,
                    "status": "in_progress",
                    "is_locked": False,
                    "auto_completed": False,
                    "last_confidence": confidence,
                    "confidence_updated_at": confidence_updated_at,
                    "attempt_id": (
                        str(adaptive_outcome.get("attempt_id"))
                        if adaptive_outcome
                        else None
                    ),
                    "accuracy": completion_accuracy,
                    "updated_mastery": completion_mastery,
                    "mastery_score": mastery_score,
                    "completion_status": completion_status,
                    "reinforce_required": reinforce_required,
                    "retry_required": retry_required,
                    "bloom_score": lesson_assessment.get("bloom_score"),
                    "bloom_accuracy_by_level": dict(
                        lesson_assessment.get("bloom_accuracy_by_level") or {}
                    ),
                    "concept_coverage_score": lesson_assessment.get(
                        "concept_coverage_score"
                    ),
                    "concept_coverage_rate": lesson_assessment.get(
                        "concept_coverage_score"
                    ),
                    "difficulty_weighted_score": lesson_assessment.get(
                        "difficulty_weighted_score"
                    ),
                    "confidence_score": lesson_assessment.get("confidence_score"),
                    "weak_concepts": list(lesson_assessment.get("weak_concepts") or []),
                    "next_action": (
                        adaptive_outcome.get("next_action") if adaptive_outcome else None
                    ),
                    "adaptive_next_quiz": (
                        adaptive_outcome.get("next_quiz") if adaptive_outcome else None
                    ),
                    "reason_locked": (
                        "Lesson is not completed under mastery evaluation. "
                        f"Current status: {completion_status or 'reinforce_required'}."
                    ),
                    "blocking_lesson_id": None,
                    "updated_at": datetime.utcnow(),
                }
            else:
                _persist_confidence_if_present()
                logger.warning(
                    f"Blocking completion without quiz answers: "
                    f"path={path_id}, lesson={lesson_id}"
                )
                return {
                    "path_id": path_id,
                    "lesson_id": lesson_id,
                    "status": "in_progress",
                    "is_locked": False,
                    "auto_completed": False,
                    "last_confidence": stored_confidence,
                    "confidence_updated_at": (
                        stored_record.get("updated_at")
                        if isinstance(stored_record, dict)
                        else None
                    ),
                    "reason_locked": (
                        "Cannot complete lesson without answering quiz questions. "
                        "Please complete the lesson quiz first."
                    ),
                    "blocking_lesson_id": None,
                    "updated_at": datetime.utcnow(),
                }
        elif confidence is not None and confidence >= 0.75:
            final_status = "in_progress"

        # Update database
        updated_at = datetime.utcnow()
        lesson_progress = dict(document.get("lesson_progress") or {})
        lesson_progress[lesson_id] = final_status

        update_payload = {
            "lesson_progress": lesson_progress,
            "updated_at": updated_at,
        }
        if confidence is not None and has_submitted_exercise:
            update_payload[f"lesson_confidence_log.{lesson_id}.confidence"] = float(
                confidence
            )
            update_payload[f"lesson_confidence_log.{lesson_id}.updated_at"] = (
                confidence_updated_at
            )
        if lesson_assessment:
            update_payload[f"lesson_confidence_log.{lesson_id}.mastery_score"] = (
                lesson_assessment.get("mastery_score")
            )
            update_payload[f"lesson_confidence_log.{lesson_id}.completion_status"] = (
                lesson_assessment.get("completion_status")
            )
            update_payload[f"lesson_confidence_log.{lesson_id}.concept_coverage_rate"] = (
                lesson_assessment.get("concept_coverage_score")
            )

        self.learning_path_repository.collection.update_one(
            {"_id": document["_id"]},
            {"$set": update_payload},
        )
        refreshed_document = self.learning_path_repository.get_by_path_id(path_id) or document
        concept_mastery = prerequisite_resolver.estimate_concept_mastery(
            path_document=refreshed_document,
            user_id=user_id,
        )
        self.learning_path_repository.collection.update_one(
            {"_id": document["_id"]},
            {
                "$set": {
                    "concept_mastery": concept_mastery,
                    "updated_at": updated_at,
                }
            },
        )
        if confidence is not None and has_submitted_exercise:
            logger.info(
                "Saved latest confidence score: path=%s lesson=%s confidence=%.4f",
                path_id,
                lesson_id,
                float(confidence),
            )

        result_confidence = (
            float(confidence) if confidence is not None else stored_confidence
        )
        result_confidence_updated_at = confidence_updated_at
        if result_confidence_updated_at is None and isinstance(stored_record, dict):
            result_confidence_updated_at = stored_record.get("updated_at")

        # Log metrics
        logger.info(
            f"Lesson progress updated: path={path_id}, lesson={lesson_id}, "
            f"status={final_status}, auto_completed={auto_completed}, "
            f"confidence={confidence}"
        )

        # Log exercise attempt if confidence was provided
        if confidence is not None and has_submitted_exercise and questions_answered:
            try:
                exercise_logging_service.log_quiz_attempt(
                    user_id=user_id,
                    path_id=path_id,
                    lesson_id=lesson_id,
                    questions_data=questions_answered,
                    confidence=confidence,
                    auto_completed=auto_completed,
                    lesson_status_after=final_status,
                    attempt_metrics=lesson_assessment,
                )
                logger.info(
                    f"Exercise attempt logged: path={path_id}, lesson={lesson_id}, "
                    f"user={user_id}, confidence={confidence:.4f}, auto_completed={auto_completed}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to log exercise attempt: path={path_id}, lesson={lesson_id}, "
                    f"user={user_id}, error={str(e)}",
                    exc_info=True,
                )
                # Don't fail the entire operation - continue with progress update

        return {
            "path_id": path_id,
            "lesson_id": lesson_id,
            "status": final_status,
            "is_locked": False,
            "auto_completed": auto_completed,
            "last_confidence": result_confidence,
            "confidence_updated_at": result_confidence_updated_at,
            "attempt_id": (
                str(adaptive_outcome.get("attempt_id")) if adaptive_outcome else None
            ),
            "accuracy": completion_accuracy if adaptive_outcome else None,
            "updated_mastery": completion_mastery if adaptive_outcome else None,
            "mastery_score": mastery_score,
            "completion_status": completion_status,
            "reinforce_required": reinforce_required,
            "retry_required": retry_required,
            "bloom_score": lesson_assessment.get("bloom_score"),
            "bloom_accuracy_by_level": dict(
                lesson_assessment.get("bloom_accuracy_by_level") or {}
            ),
            "concept_coverage_score": lesson_assessment.get("concept_coverage_score"),
            "concept_coverage_rate": lesson_assessment.get("concept_coverage_score"),
            "difficulty_weighted_score": lesson_assessment.get(
                "difficulty_weighted_score"
            ),
            "confidence_score": lesson_assessment.get("confidence_score"),
            "weak_concepts": list(lesson_assessment.get("weak_concepts") or []),
            "next_action": adaptive_outcome.get("next_action") if adaptive_outcome else None,
            "adaptive_next_quiz": (
                adaptive_outcome.get("next_quiz") if adaptive_outcome else None
            ),
            "reason_locked": None,
            "blocking_lesson_id": None,
            "blocking_concepts": [],
            "missing_prerequisite_concepts": [],
            "prerequisite_mastery": {},
            "bridge_recommendations": [],
            "mastery_threshold": prerequisite_resolver.mastery_threshold,
            "updated_at": updated_at,
        }

    def get_lesson_lock_statuses(
        self,
        *,
        path_id: str,
        user_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get lock status for all lessons in a learning path.

        Args:
            path_id: Learning path ID
            user_id: User ID

        Returns:
            Dict mapping lesson_id -> lock status info
        """
        document = self.learning_path_repository.get_by_path_id(path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found.")

        normalized = self._serialize_learning_path(document)
        lesson_ids = [
            lesson.get("lesson_id")
            for chapter in normalized.get("chapters", [])
            for lesson in chapter.get("lessons", [])
            if lesson.get("lesson_id")
        ]

        return lesson_completion_engine.get_lesson_lock_status(
            path_id,
            lesson_ids,
            user_id=user_id,
        )

    def record_lesson_study_time(
        self,
        *,
        path_id: str,
        user_id: str,
        lesson_id: str,
        seconds_spent: int,
    ) -> Dict[str, Any]:
        """Persist aggregated lesson study time for the current day."""
        document = self.learning_path_repository.get_by_path_id(path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found.")

        normalized = self._serialize_learning_path(document)
        known_lessons = {
            lesson.get("lesson_id")
            for chapter in normalized.get("chapters", [])
            for lesson in chapter.get("lessons", [])
            if lesson.get("lesson_id")
        }
        if lesson_id not in known_lessons:
            raise ValueError("Lesson not found in learning path.")

        clamped_seconds = max(1, min(int(seconds_spent), 86400))
        now = datetime.utcnow()
        tracked_date = now.date()
        study_collection = self.learning_path_repository.db["lesson_study_time"]
        study_collection.create_index(
            [("user_id", 1), ("tracked_date", 1), ("path_id", 1), ("lesson_id", 1)],
            unique=True,
        )
        study_collection.create_index([("user_id", 1), ("tracked_date", -1)])

        study_collection.update_one(
            {
                "user_id": user_id,
                "tracked_date": tracked_date.isoformat(),
                "path_id": path_id,
                "lesson_id": lesson_id,
            },
            {
                "$inc": {
                    "seconds_spent": clamped_seconds,
                    "session_count": 1,
                },
                "$set": {
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )

        day_total = 0
        for item in study_collection.find(
            {
                "user_id": user_id,
                "tracked_date": tracked_date.isoformat(),
            },
            {"seconds_spent": 1},
        ):
            day_total += int(item.get("seconds_spent", 0) or 0)

        return {
            "path_id": path_id,
            "lesson_id": lesson_id,
            "seconds_spent": clamped_seconds,
            "total_seconds": day_total,
            "tracked_date": tracked_date,
            "updated_at": now,
        }

    def get_study_summary(self, *, user_id: str, days: int = 7) -> Dict[str, Any]:
        """Return total study time and a recent daily calendar for the user."""
        safe_days = max(1, min(int(days), 90))
        study_collection = self.learning_path_repository.db["lesson_study_time"]
        study_collection.create_index([("user_id", 1), ("tracked_date", -1)])

        now = datetime.utcnow()
        today = now.date()
        range_start = today - timedelta(days=safe_days - 1)

        total_seconds = 0
        last_updated: Optional[datetime] = None
        for item in study_collection.find(
            {"user_id": user_id}, {"seconds_spent": 1, "updated_at": 1}
        ):
            total_seconds += int(item.get("seconds_spent", 0) or 0)
            updated_at = item.get("updated_at")
            if isinstance(updated_at, datetime) and (
                last_updated is None or updated_at > last_updated
            ):
                last_updated = updated_at

        seconds_by_day: Dict[str, int] = {}
        for item in study_collection.find(
            {
                "user_id": user_id,
                "tracked_date": {
                    "$gte": range_start.isoformat(),
                    "$lte": today.isoformat(),
                },
            },
            {"tracked_date": 1, "seconds_spent": 1},
        ):
            day_key = str(item.get("tracked_date") or "")
            seconds_by_day[day_key] = seconds_by_day.get(day_key, 0) + int(
                item.get("seconds_spent", 0) or 0
            )

        last_7_days: List[Dict[str, Any]] = []
        for offset in range(safe_days):
            day = range_start + timedelta(days=offset)
            day_key = day.isoformat()
            seconds = seconds_by_day.get(day_key, 0)
            last_7_days.append(
                {
                    "date": day,
                    "seconds": seconds,
                    "hours": round(seconds / 3600, 2),
                }
            )

        return {
            "user_id": user_id,
            "total_seconds": total_seconds,
            "total_hours": round(total_seconds / 3600, 2),
            "last_7_days": last_7_days,
            "updated_at": last_updated,
        }

    @staticmethod
    def _validate_inputs(*, subject_id: str, goal: str, level: str) -> None:
        if not get_subject_label(subject_id):
            raise ValueError(f"Unsupported subject_id: {subject_id}")
        if level not in {"beginner", "intermediate", "advanced"}:
            raise ValueError(f"Unsupported level: {level}")
        if len(goal.strip()) < 3:
            raise ValueError("goal must be at least 3 characters")

    def _ensure_subject(
        self, *, subject_id: str, subject_label: str, level: str
    ) -> Dict[str, Any]:
        subject = self.subject_repository.get_by_slug(subject_id)
        if subject:
            return subject
        try:
            return self.subject_repository.create(
                {
                    "title": subject_label,
                    "slug": subject_id,
                    "description": f"Fixed subject catalog entry for {subject_label}.",
                    "topic": subject_id,
                    "level": level,
                    "metadata": {
                        "is_fixed_subject": True,
                        "subject_key": subject_id,
                    },
                }
            )
        except DuplicateKeyError:
            subject = self.subject_repository.get_by_slug(subject_id)
            if subject:
                return subject
            raise

    def _generate_curriculum(
        self,
        *,
        subject_id: str,
        subject_label: str,
        goal: str,
        level: str,
    ) -> Dict[str, Any]:
        fallback = build_fallback_curriculum(
            subject_id=subject_id, goal=goal, level=level
        )
        llm_status = self.llm_client.status()
        if not self.llm_client.is_available() or bool(llm_status.get("cooldown_active")):
            logger.warning(
                "Curriculum LLM unavailable or cooling down, using fallback curriculum for subject_id=%s",
                subject_id,
            )
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        prompt = build_learning_path_prompt(
            subject_label=subject_label, goal=goal, level=level
        )
        raw_text = self.llm_client.generate(prompt)
        json_text = extract_json_object(raw_text)
        if not json_text and raw_text:
            logger.info(
                "Curriculum LLM returned incomplete JSON, attempting repair for subject_id=%s",
                subject_id,
            )
            repaired_text = self.llm_client.repair_json(raw_text)
            repaired_json = extract_json_object(repaired_text)
            if repaired_json:
                raw_text = repaired_text
                json_text = repaired_json
        if not json_text:
            logger.warning(
                "Curriculum LLM returned no JSON, using fallback curriculum for subject_id=%s",
                subject_id,
            )
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Curriculum JSON parse failed for subject_id=%s: %s", subject_id, exc
            )
            repaired_text = self.llm_client.repair_json(raw_text)
            repaired_json = extract_json_object(repaired_text)
            if repaired_json:
                try:
                    parsed = json.loads(repaired_json)
                except json.JSONDecodeError:
                    return {
                        "chapters": fallback,
                        "source": "fallback",
                        "llm_status": llm_status,
                    }
            else:
                return {
                    "chapters": fallback,
                    "source": "fallback",
                    "llm_status": llm_status,
                }

        normalized = normalize_curriculum(parsed, goal=goal)
        if not normalized:
            logger.warning(
                "Curriculum normalization produced no chapters, using fallback for subject_id=%s",
                subject_id,
            )
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        logger.info(
            "Curriculum LLM succeeded: subject_id=%s chapters=%s lessons=%s",
            subject_id,
            len(normalized),
            sum(len(chapter.get("lessons", [])) for chapter in normalized),
        )
        return {
            "chapters": normalized,
            "source": "ai",
            "llm_status": llm_status,
        }

    def _recommend_chunks_for_lesson(
        self,
        *,
        lesson: Dict[str, Any],
        chapter: Dict[str, Any],
        subject: Dict[str, Any],
        goal: str,
        level: str,
        path_id: str,
    ) -> Dict[str, Any]:
        metadata = {
            "goal": goal,
            "level": level,
            "learning_path_id": path_id,
            "subject_key": subject.get("slug"),
            "pipeline": "hybrid_subject_lesson_v1",
            "avoid_resource_ids": [
                str(item)
                for item in (lesson.get("metadata", {}) or {}).get(
                    "avoid_resource_ids", []
                )
                if item
            ],
        }
        try:
            return self.lesson_chunk_service.recommend_chunks(
                lesson_id=str(lesson["_id"]),
                max_chunks=self.max_chunks_per_lesson,
                selection_strategy="local_semantic_lesson_scope_v1",
                enable_diversity_reranking=True,
                diversity_lambda=None,
                resource_ids=[
                    str(item)
                    for item in (
                        lesson.get("resource_ids")
                        or lesson.get("recommended_resource_ids")
                        or []
                    )
                ],
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Primary lesson chunk recommendation failed for lesson_id=%s: %s. Falling back to top local chunks.",
                lesson["_id"],
                exc,
            )
            return self._fallback_recommendation(
                lesson=lesson,
                chapter=chapter,
                subject=subject,
                metadata=metadata,
            )

    def _fallback_recommendation(
        self,
        *,
        lesson: Dict[str, Any],
        chapter: Dict[str, Any],
        subject: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        topic = lesson.get("topic") or chapter.get("topic") or subject.get("topic")
        level = lesson.get("level")
        lesson_resource_ids = [
            str(item)
            for item in (
                lesson.get("resource_ids")
                or lesson.get("recommended_resource_ids")
                or []
            )
            if item
        ]
        candidate_chunks = []
        if lesson_resource_ids:
            candidate_chunks = self.lesson_chunk_service.chunk_repository.candidate_chunks(
                resource_ids=lesson_resource_ids,
                limit=max(self.max_chunks_per_lesson * 3, self.max_chunks_per_lesson),
            )
        candidate_chunks = self.lesson_chunk_service.chunk_repository.candidate_chunks(
            topic=topic,
            level=level,
            limit=self.max_chunks_per_lesson,
        ) if not candidate_chunks else candidate_chunks
        if not candidate_chunks:
            candidate_chunks = (
                self.lesson_chunk_service.chunk_repository.candidate_chunks(
                    level=level,
                    limit=self.max_chunks_per_lesson,
                )
            )
        if not candidate_chunks:
            candidate_chunks = (
                self.lesson_chunk_service.chunk_repository.candidate_chunks(
                    limit=self.max_chunks_per_lesson,
                )
            )

        selected_chunks = [
            {
                "chunk_id": str(chunk["_id"]),
                "resource_id": str(chunk["resource_id"]),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "page_number": self.lesson_chunk_service._resolve_page_number(chunk),
                "score": 0.0,
                "preview": str(chunk.get("content") or "")[:240],
            }
            for chunk in candidate_chunks[: self.max_chunks_per_lesson]
        ]
        chunk_object_ids = [ObjectId(item["chunk_id"]) for item in selected_chunks]
        resource_object_ids = [
            ObjectId(item["resource_id"]) for item in selected_chunks
        ]

        recommendation = (
            self.lesson_chunk_service.recommendation_repository.upsert_for_lesson(
                lesson["_id"],
                {
                    "subject_id": subject["_id"],
                    "chapter_id": chapter["_id"],
                    "lesson_id": lesson["_id"],
                    "chunk_ids": chunk_object_ids,
                    "resource_ids": resource_object_ids,
                    "selection_strategy": "fallback_top_chunks_v1",
                    "metadata": {
                        **metadata,
                        "fallback": True,
                        "selected_count": len(selected_chunks),
                        "candidate_count": len(candidate_chunks),
                    },
                },
            )
        )
        return self.lesson_chunk_service._serialize_recommendation(
            recommendation, selected_chunks
        )

    @staticmethod
    def _build_keywords(
        *,
        subject_label: str,
        chapter_title: str,
        lesson_title: str,
        lesson_summary: str,
        goal: str,
    ) -> List[str]:
        def add_phrase(target: List[str], seen: set[str], value: str) -> None:
            phrase = re.sub(r"\s+", " ", str(value or "").strip())
            normalized = phrase.lower()
            if not phrase or normalized in seen:
                return
            seen.add(normalized)
            target.append(phrase)

        phrases: List[str] = []
        seen: set[str] = set()
        for value in [subject_label, chapter_title, lesson_title, lesson_summary, goal]:
            add_phrase(phrases, seen, value)

        for source in [chapter_title, lesson_title, lesson_summary, goal]:
            cleaned = re.sub(r"[\\/|]+", " ", str(source or ""))
            for part in re.split(r"[:\-–—,()]+", cleaned):
                add_phrase(phrases, seen, part)

            tokens = [
                token
                for token in re.findall(r"\w+", cleaned.lower())
                if len(token) >= 3 and token not in {"lesson", "bai", "chuong", "chapter"}
            ]
            for index, token in enumerate(tokens):
                add_phrase(phrases, seen, token)
                if index + 1 < len(tokens):
                    add_phrase(phrases, seen, f"{token} {tokens[index + 1]}")
                if index + 2 < len(tokens):
                    add_phrase(phrases, seen, f"{token} {tokens[index + 1]} {tokens[index + 2]}")

        return phrases[:20]

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @classmethod
    def _tokenize_text(cls, value: str) -> List[str]:
        return [
            token
            for token in re.findall(r"\w+", cls._normalize_text(value))
            if len(token) >= 3 and token not in {"lesson", "bai", "chuong", "chapter"}
        ]

    @staticmethod
    def _semantic_similarity(
        query_embedding: Optional[np.ndarray], candidate_embedding: Any
    ) -> float:
        if query_embedding is None or candidate_embedding in (None, []):
            return 0.0
        try:
            candidate_vector = np.array(candidate_embedding, dtype=float)
            if candidate_vector.size == 0:
                return 0.0
            return float(cosine_similarity(query_embedding, candidate_vector))
        except Exception:
            return 0.0

    @classmethod
    def _score_haystack_for_lesson(
        cls,
        *,
        haystack: str,
        primary_phrases: List[str],
        secondary_phrases: List[str],
        keyword_set: set[str],
        token_set: set[str],
    ) -> float:
        normalized_haystack = cls._normalize_text(haystack)
        if not normalized_haystack:
            return 0.0

        score = 0.0
        primary_hits = sum(
            1 for phrase in primary_phrases if phrase and phrase in normalized_haystack
        )
        secondary_hits = sum(
            1 for phrase in secondary_phrases if phrase and phrase in normalized_haystack
        )
        keyword_hits = sum(
            1 for phrase in keyword_set if phrase and phrase in normalized_haystack
        )
        haystack_tokens = set(cls._tokenize_text(normalized_haystack))
        token_hits = sum(1 for token in token_set if token in haystack_tokens)

        if primary_hits:
            score += min(1.25, primary_hits * 0.42)
        if secondary_hits:
            score += min(0.2, secondary_hits * 0.05)
        if keyword_hits:
            score += min(0.38, keyword_hits * 0.06)
        if token_hits:
            score += min(0.28, token_hits * 0.02)

        return score

    def _select_resource_ids_for_lesson(
        self,
        *,
        subject_id: str,
        subject_label: str,
        chapter_title: str,
        lesson_title: str,
        lesson_summary: str,
        goal: str,
        level: str,
        limit: int,
        avoid_resource_ids: Optional[List[str]] = None,
    ) -> List[str]:
        lesson_keywords = self._build_keywords(
            subject_label=subject_label,
            chapter_title=chapter_title,
            lesson_title=lesson_title,
            lesson_summary=lesson_summary,
            goal=goal,
        )
        normalized_avoid_ids = {
            str(resource_id).strip()
            for resource_id in (avoid_resource_ids or [])
            if str(resource_id or "").strip()
        }
        primary_phrases = [
            self._normalize_text(lesson_title),
            self._normalize_text(lesson_summary),
        ]
        secondary_phrases = [
            self._normalize_text(chapter_title),
            self._normalize_text(subject_label),
            self._normalize_text(goal),
        ]
        query_text = " ".join(
            part
            for part in [
                subject_label,
                chapter_title,
                lesson_title,
                lesson_summary,
                goal,
            ]
            if str(part or "").strip()
        )
        try:
            query_embedding = np.array(embed_text(query_text), dtype=float)
            if query_embedding.size == 0:
                query_embedding = None
        except Exception:
            query_embedding = None
        keyword_set = {
            self._normalize_text(item)
            for item in lesson_keywords
            if str(item).strip()
        }
        token_set = {
            token
            for phrase in keyword_set
            for token in re.findall(r"\w+", phrase)
            if len(token) >= 3
        }

        query: Dict[str, Any] = {}
        if level:
            query["$or"] = [
                {"metadata.level": level},
                {"level": level},
            ]

        candidates = list(
            self.resource_repository.collection.find(
                query,
                {
                    "_id": 1,
                    "title": 1,
                    "topic": 1,
                    "source": 1,
                    "content_summary": 1,
                    "metadata": 1,
                    "level": 1,
                },
            ).limit(max(limit * 12, 80))
        )
        if not candidates:
            candidates = []

        metadata_scores: Dict[str, float] = {}

        for resource in candidates:
            metadata = resource.get("metadata") or {}
            haystack = self._normalize_text(
                " ".join(
                    [
                        str(resource.get("title") or ""),
                        str(resource.get("topic") or ""),
                        str(metadata.get("title") or ""),
                        str(metadata.get("source_title") or ""),
                        str(metadata.get("description") or ""),
                        str(metadata.get("summary") or ""),
                        str(metadata.get("topic") or ""),
                        str(metadata.get("keywords") or ""),
                        str(resource.get("content_summary") or ""),
                    ]
                )
            )
            score = self._score_haystack_for_lesson(
                haystack=haystack,
                primary_phrases=primary_phrases,
                secondary_phrases=secondary_phrases,
                keyword_set=keyword_set,
                token_set=token_set,
            )

            resource_topic = self._normalize_text(str(resource.get("topic") or metadata.get("topic") or ""))
            if subject_id and subject_id in resource_topic:
                score += 0.08
            if subject_label and self._normalize_text(subject_label) in haystack:
                score += 0.05
            resource_level = self._normalize_text(
                str(metadata.get("level") or resource.get("level") or "")
            )
            if resource_level == self._normalize_text(level):
                score += 0.08
            resource_id = str(resource.get("_id") or "").strip()
            if resource_id:
                metadata_scores[resource_id] = max(metadata_scores.get(resource_id, 0.0), score)

        chunk_queries = [
            {
                "topic": subject_id or None,
                "level": level or None,
                "limit": max(limit * 40, 220),
            },
            {
                "topic": subject_id or None,
                "level": None,
                "limit": max(limit * 28, 180),
            },
            {
                "topic": None,
                "level": level or None,
                "limit": max(limit * 20, 140),
            },
        ]
        chunk_candidates: List[Dict[str, Any]] = []
        seen_chunk_ids: set[str] = set()
        for query in chunk_queries:
            rows = self.lesson_chunk_service.chunk_repository.candidate_chunks(**query)
            for row in rows:
                chunk_id = str(row.get("_id") or "").strip()
                if not chunk_id or chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                chunk_candidates.append(row)
            if len(chunk_candidates) >= max(limit * 60, 320):
                break

        chunk_scores_by_resource: Dict[str, List[float]] = {}
        for chunk in chunk_candidates:
            metadata = chunk.get("metadata") or {}
            resource_id = str(chunk.get("resource_id") or "").strip()
            if not resource_id:
                continue

            haystack = " ".join(
                [
                    str(chunk.get("content") or ""),
                    str(metadata.get("heading") or ""),
                    str(metadata.get("section_title") or ""),
                    str(metadata.get("chapter_title") or ""),
                    str(metadata.get("source_title") or ""),
                    str(metadata.get("title") or ""),
                    str(metadata.get("topic") or ""),
                    " ".join(str(item) for item in metadata.get("covered_concepts") or []),
                    " ".join(str(item) for item in metadata.get("primary_concepts") or []),
                ]
            )
            lexical_chunk_score = self._score_haystack_for_lesson(
                haystack=haystack,
                primary_phrases=primary_phrases,
                secondary_phrases=secondary_phrases,
                keyword_set=keyword_set,
                token_set=token_set,
            )
            semantic_chunk_score = self._semantic_similarity(
                query_embedding, chunk.get("embedding")
            )
            chunk_score = lexical_chunk_score * 0.55 + semantic_chunk_score * 0.45
            if metadata.get("level") == level:
                chunk_score += 0.06
            if metadata.get("topic") == subject_id:
                chunk_score += 0.04
            if lexical_chunk_score >= 0.6 and semantic_chunk_score >= 0.55:
                chunk_score += 0.1
            elif lexical_chunk_score >= 0.45 or semantic_chunk_score >= 0.62:
                chunk_score += 0.05
            if chunk_score <= 0.0:
                continue
            chunk_scores_by_resource.setdefault(resource_id, []).append(chunk_score)

        scored: List[tuple[float, str, bool]] = []
        for resource_id in set(metadata_scores) | set(chunk_scores_by_resource):
            chunk_scores = sorted(
                chunk_scores_by_resource.get(resource_id, []), reverse=True
            )
            metadata_score = float(metadata_scores.get(resource_id, 0.0))
            top_chunk_score = float(chunk_scores[0]) if chunk_scores else 0.0
            second_chunk_score = float(chunk_scores[1]) if len(chunk_scores) > 1 else 0.0
            third_chunk_score = float(chunk_scores[2]) if len(chunk_scores) > 2 else 0.0
            support_bonus = min(0.24, max(len(chunk_scores) - 1, 0) * 0.045)
            score = (
                metadata_score * 0.1
                + top_chunk_score * 0.58
                + second_chunk_score * 0.2
                + third_chunk_score * 0.12
                + support_bonus
            )

            if top_chunk_score >= 0.9:
                score += 0.12
            elif top_chunk_score >= 0.65:
                score += 0.06

            was_used_in_path = resource_id in normalized_avoid_ids
            if was_used_in_path:
                score -= 0.2

            base_signal = max(metadata_score, top_chunk_score)
            if base_signal >= 0.18:
                scored.append((score, resource_id, was_used_in_path))

        scored.sort(key=lambda item: (item[2], -item[0], item[1]))
        ordered_ids: List[str] = []
        seen_ids: set[str] = set()
        for _score, resource_id, _was_used_in_path in scored:
            if resource_id in seen_ids:
                continue
            seen_ids.add(resource_id)
            ordered_ids.append(resource_id)
            if len(ordered_ids) >= limit:
                break
        return ordered_ids

    def _serialize_learning_path(self, document: Dict[str, Any]) -> Dict[str, Any]:
        subject_id = str(document.get("subject_id") or "python").strip().lower()
        if not get_subject_label(subject_id):
            subject_id = "python"

        chapters = self._normalize_chapters(
            chapters=document.get("chapters") or document.get("curriculum") or [],
            lesson_progress=document.get("lesson_progress") or {},
            lesson_confidence_log=document.get("lesson_confidence_log") or {},
        )
        return {
            "path_id": str(document.get("path_id") or ""),
            "subject_id": subject_id,
            "goal": document.get("goal", ""),
            "level": str(document.get("level") or "beginner").strip().lower(),
            "generated_at": self._resolve_generated_at(document),
            "chapters": chapters,
            "curriculum_source": document.get("curriculum_source", "fallback"),
            "llm_status": document.get("llm_status"),
            "message": document.get("message", ""),
        }

    @staticmethod
    def _normalize_chapters(
        *,
        chapters: List[Dict[str, Any]],
        lesson_progress: Dict[str, str],
        lesson_confidence_log: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for chapter in chapters or []:
            lessons_payload = []
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "")
                confidence_entry = lesson_confidence_log.get(lesson_id) or {}
                lessons_payload.append(
                    {
                        "lesson_id": lesson_id,
                        "title": lesson.get("title", ""),
                        "summary": lesson.get("summary"),
                        "recommended_chunk_ids": [
                            str(item)
                            for item in lesson.get("recommended_chunk_ids", []) or []
                        ],
                        "status": lesson_progress.get(
                            lesson_id, lesson.get("status", "not_started")
                        ),
                        "last_confidence": float(
                            confidence_entry.get("confidence", 0.0) or 0.0
                        ),
                        "confidence_updated_at": confidence_entry.get("updated_at"),
                    }
                )
            normalized.append(
                {
                    "chapter_id": str(chapter.get("chapter_id") or ""),
                    "title": chapter.get("title", ""),
                    "lessons": lessons_payload,
                }
            )
        return normalized

    @staticmethod
    def _resolve_generated_at(document: Dict[str, Any]) -> datetime:
        for key in ("generated_at", "created_at", "updated_at"):
            value = document.get(key)
            if isinstance(value, datetime):
                return value
        return datetime.utcnow()


learning_path_service = HybridLearningPathService()
