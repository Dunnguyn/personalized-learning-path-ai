"""MVP adaptive learning loop service with backward-compatible wrappers."""

from __future__ import annotations

from datetime import datetime
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.repositories import (
    AdaptiveActionRepository,
    LearnerStateSnapshotRepository,
    LearningEventRepository,
    LearningPathRepository,
    LessonRepository,
    LessonQuestionRepository,
    ResourceRepository,
)
from backend.app.services.adaptive_decision_service import adaptive_decision_service
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.hybrid_recommendation_service import (
    hybrid_recommendation_service,
)
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.prerequisite_resolver import prerequisite_resolver
from backend.app.services.question_generation_service import (
    lesson_question_generation_service,
)
from backend.app.services.retry_strategy_service import retry_strategy_service

logger = logging.getLogger(__name__)


class AdaptiveLearningLoopService:
    """Persist events, compute learner state, and decide the next adaptive step."""

    _LEGACY_ACTION_MAP = {
        adaptive_decision_service.UNLOCK_NEXT_LESSON: "move_to_next_lesson",
        adaptive_decision_service.ASSIGN_REMEDIAL_RESOURCE: "reinforce_weak_concept",
        adaptive_decision_service.GENERATE_REINFORCEMENT_QUIZ: "reinforce_weak_concept",
        adaptive_decision_service.RECOMMEND_SHORT_RESOURCE: "review_summary",
        adaptive_decision_service.REVIEW_WEAK_CONCEPT: "reinforce_weak_concept",
        adaptive_decision_service.NO_ACTION: "review_summary",
    }
    _LEGACY_MODE_MAP = {
        "move_to_next_lesson": "learn_new",
        "reinforce_weak_concept": "reinforce_weaknesses",
        "review_summary": "continue_learning",
        "resume_unfinished": "continue_learning",
    }

    def __init__(self) -> None:
        self.db = get_db()
        self.learning_event_repository = LearningEventRepository()
        self.snapshot_repository = LearnerStateSnapshotRepository()
        self.action_repository = AdaptiveActionRepository()
        self.learning_path_repository = LearningPathRepository()
        self.lesson_repository = LessonRepository()
        self.resource_repository = ResourceRepository()
        self.question_repository = LessonQuestionRepository()
        self.learner_state_service = learner_state_service
        self.decision_service = adaptive_decision_service
        self.hybrid_recommendation_service = hybrid_recommendation_service
        self.question_generation_service = lesson_question_generation_service

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.utcnow()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _is_object_id(value: Any) -> bool:
        try:
            return ObjectId.is_valid(str(value))
        except Exception:
            return False

    @staticmethod
    def _normalize_string_list(values: Sequence[Any] | None) -> List[str]:
        return [str(item).strip() for item in values or [] if str(item).strip()]

    @staticmethod
    def _normalize_concept(value: Any) -> str:
        return re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")

    @classmethod
    def _normalize_target_concepts(cls, values: Sequence[Any] | None) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for item in values or []:
            token = cls._normalize_concept(item)
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    @classmethod
    def _question_matches_targets(
        cls,
        question: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> bool:
        normalized_targets = cls._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return True

        metadata = question.get("metadata") if isinstance(question.get("metadata"), dict) else {}
        candidates = {
            cls._normalize_concept(question.get("concept_id")),
            cls._normalize_concept(metadata.get("question_focus")),
        }
        for source in (
            metadata.get("covered_concepts"),
            metadata.get("target_concepts"),
        ):
            for item in source or []:
                candidates.add(cls._normalize_concept(item))

        return any(
            target in candidate or candidate in target
            for target in normalized_targets
            for candidate in candidates
            if candidate
        )

    @classmethod
    def _extract_quiz_response_fields(
        cls,
        quiz_payload: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        payload = quiz_payload if isinstance(quiz_payload, dict) else {}
        return {
            "recommended_difficulty": (
                str(payload.get("recommended_difficulty"))
                if payload.get("recommended_difficulty") is not None
                else None
            ),
            "recommended_bloom_levels": [
                str(item)
                for item in (payload.get("recommended_bloom_levels") or [])
                if str(item).strip()
            ],
            "retry_strategy": (
                str(payload.get("retry_strategy"))
                if payload.get("retry_strategy") is not None
                else None
            ),
            "question_types": [
                str(item)
                for item in (payload.get("question_types") or [])
                if str(item).strip()
            ],
            "adaptive_explanation": (
                str(payload.get("adaptive_explanation"))
                if payload.get("adaptive_explanation") is not None
                else None
            ),
            "quiz": cls._make_json_safe(payload) if payload else None,
        }

    def _resolve_target_mastery(
        self,
        *,
        snapshot: Optional[Dict[str, Any]],
        target_concepts: Sequence[str],
    ) -> float:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        mastery_by_concept = {
            self._normalize_concept(key): self._safe_float(value, 0.0)
            for key, value in ((snapshot or {}).get("mastery_by_concept") or {}).items()
            if self._normalize_concept(key)
        }
        matched_values = [
            float(value)
            for concept, value in mastery_by_concept.items()
            if any(target in concept or concept in target for target in normalized_targets)
        ]
        if matched_values:
            return min(matched_values)
        return self._safe_float((snapshot or {}).get("quiz_accuracy"), 0.0)

    def _build_reinforcement_quiz_config(
        self,
        *,
        snapshot: Optional[Dict[str, Any]],
        target_concepts: Sequence[str],
    ) -> Dict[str, Any]:
        quiz_accuracy = self._safe_float((snapshot or {}).get("quiz_accuracy"), 0.0)
        completion_rate = self._safe_float((snapshot or {}).get("completion_rate"), 0.0)
        engagement_score = self._safe_float((snapshot or {}).get("engagement_score"), 0.0)
        fatigue_score = self._safe_float((snapshot or {}).get("fatigue_score"), 0.0)
        fail_streak = int((snapshot or {}).get("fail_streak") or 0)
        retry_count = int((snapshot or {}).get("retry_count") or 0)
        target_mastery = self._resolve_target_mastery(
            snapshot=snapshot,
            target_concepts=target_concepts,
        )

        recommended_difficulty = "beginner"
        recommended_bloom_levels = ["remember", "understand"]
        allow_llm = False
        prefer_template = True
        target_count = 5

        if (
            target_mastery >= 0.82
            and quiz_accuracy >= 0.85
            and completion_rate >= 0.75
            and fail_streak == 0
            and fatigue_score < 0.45
        ):
            recommended_difficulty = "advanced"
            recommended_bloom_levels = ["apply", "analyze"]
            allow_llm = True
            prefer_template = False
            target_count = 6
        elif (
            target_mastery >= 0.6
            and quiz_accuracy >= 0.65
            and fatigue_score < 0.7
        ):
            recommended_difficulty = "intermediate"
            recommended_bloom_levels = ["understand", "apply"]
            allow_llm = engagement_score >= 0.45
            prefer_template = not allow_llm
            target_count = 5

        if fatigue_score > 0.82:
            recommended_difficulty = "beginner"
            recommended_bloom_levels = ["remember", "understand"]
            allow_llm = False
            prefer_template = True
            target_count = 3
        elif fail_streak >= 3 or quiz_accuracy < 0.45:
            recommended_difficulty = "beginner"
            recommended_bloom_levels = ["remember", "understand"]
            allow_llm = False
            prefer_template = True
            target_count = 4

        retry_signal = max(retry_count, fail_streak, 1)
        retry_strategy = retry_strategy_service.select_retry_strategy(retry_signal)
        retry_hints = retry_strategy_service.apply_generation_hints(
            retry_strategy,
            difficulty=recommended_difficulty,
        )
        recommended_difficulty = str(
            retry_hints.get("recommended_difficulty") or recommended_difficulty
        )

        question_types = ["multiple_choice", "true_false"]
        if recommended_difficulty in {"intermediate", "advanced"} and fatigue_score < 0.75:
            question_types = ["multiple_choice", "short_answer", "true_false"]
        elif fail_streak >= 3 or fatigue_score > 0.82:
            question_types = ["multiple_choice"]

        explanation_parts = [
            f"target mastery={target_mastery:.0%}",
            f"accuracy={quiz_accuracy:.0%}",
        ]
        if fail_streak > 0:
            explanation_parts.append(f"fail streak={fail_streak}")
        if retry_count > 0:
            explanation_parts.append(f"retry count={retry_count}")
        if fatigue_score > 0:
            explanation_parts.append(f"fatigue={fatigue_score:.0%}")

        return {
            "recommended_difficulty": recommended_difficulty,
            "recommended_bloom_levels": recommended_bloom_levels,
            "allow_llm": allow_llm,
            "prefer_template": prefer_template,
            "target_count": target_count,
            "question_types": question_types,
            "retry_strategy": str(retry_hints.get("retry_strategy") or retry_strategy),
            "paraphrase_question": bool(retry_hints.get("paraphrase_question")),
            "add_explanation_before_question": bool(
                retry_hints.get("add_explanation_before_question")
            ),
            "adaptive_explanation": (
                "Quiz adapted from learner state: " + ", ".join(explanation_parts) + "."
            ),
        }

    @classmethod
    def _make_json_safe(cls, value: Any) -> Any:
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value
        if isinstance(value, dict):
            return {
                str(key): cls._make_json_safe(item)
                for key, item in value.items()
                if item is not None
            }
        if isinstance(value, (list, tuple, set)):
            return [cls._make_json_safe(item) for item in value if item is not None]
        return value

    @staticmethod
    def _normalize_event_type(event_type: str) -> str:
        mapping = {
            "lesson_started": "lesson_opened",
            "lesson_retried": "retry_requested",
            "resource_opened": "resource_viewed",
            "resource_completed": "resource_finished",
        }
        normalized = str(event_type or "").strip()
        return mapping.get(normalized, normalized)

    @staticmethod
    def _merge_payloads(payload: Any, metadata: Any, concept_ids: Sequence[Any] | None) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        if isinstance(payload, dict):
            merged.update(payload)
        if isinstance(metadata, dict):
            merged.update(metadata)
        normalized_concepts = [str(item).strip() for item in concept_ids or [] if str(item).strip()]
        if normalized_concepts and "concept_ids" not in merged:
            merged["concept_ids"] = normalized_concepts
        return merged

    def _resolve_path_document(self, path_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not path_id:
            return None
        return self.learning_path_repository.get_by_path_id(str(path_id))

    def _resolve_latest_path_id(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        latest_event: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if path_id:
            return str(path_id)
        if latest_event and latest_event.get("path_id"):
            return str(latest_event.get("path_id"))
        if lesson_id:
            path = self.learning_path_repository.collection.find_one(
                {
                    "user_id": str(user_id),
                    "$or": [
                        {"chapters.lessons.lesson_id": str(lesson_id)},
                        {f"lesson_progress.{lesson_id}": {"$exists": True}},
                    ],
                },
                sort=[("updated_at", -1), ("created_at", -1)],
            )
            if path:
                return str(path.get("path_id") or "").strip() or None
        latest_snapshot = self.snapshot_repository.get_latest(str(user_id))
        if latest_snapshot and latest_snapshot.get("path_id"):
            return str(latest_snapshot.get("path_id"))
        latest_event = latest_event or self.learning_event_repository.latest_one(str(user_id))
        if latest_event and latest_event.get("path_id"):
            return str(latest_event.get("path_id"))
        latest_path = self.learning_path_repository.collection.find_one(
            {"user_id": str(user_id)},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        if latest_path:
            return str(latest_path.get("path_id") or "").strip() or None
        return None

    def _resolve_lesson(self, lesson_id: str) -> Optional[Dict[str, Any]]:
        if not lesson_id or not self._is_object_id(lesson_id):
            return None
        try:
            return self.lesson_repository.get(lesson_id)
        except Exception:
            return None

    def _serialize_resource(self, resource: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
        metadata = resource.get("metadata") or {}
        estimated_time = int(
            metadata.get("estimated_time")
            or metadata.get("duration_minutes")
            or metadata.get("estimated_read_time")
            or 10
        )
        resource_identifier = resource.get("resource_id") or resource.get("_id")
        return {
            "resource_id": str(resource_identifier),
            "title": str(resource.get("title") or ""),
            "type": str(
                resource.get("type")
                or metadata.get("pedagogy_type")
                or resource.get("source")
                or ""
            ),
            "topic": str(resource.get("topic") or metadata.get("topic") or ""),
            "level": str(resource.get("level") or metadata.get("level") or "beginner"),
            "url": metadata.get("url") or resource.get("url"),
            "estimated_time": estimated_time,
            "reason": reason,
        }

    def _resolve_goal_level(self, path_document: Optional[Dict[str, Any]]) -> tuple[str, str]:
        if not path_document:
            return "Continue current learning path", "beginner"
        return (
            str(path_document.get("goal") or "Continue current learning path").strip(),
            str(path_document.get("level") or "beginner").strip().lower(),
        )

    def _find_next_lesson(
        self,
        *,
        path_document: Optional[Dict[str, Any]],
        lesson_id: str,
        lesson: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if path_document:
            flat_lessons: List[Dict[str, Any]] = []
            for chapter in path_document.get("chapters", []) or []:
                for item in chapter.get("lessons", []) or []:
                    flat_lessons.append(item)
            for index, item in enumerate(flat_lessons):
                if str(item.get("lesson_id") or "") != str(lesson_id):
                    continue
                if index + 1 >= len(flat_lessons):
                    return None
                next_item = flat_lessons[index + 1]
                next_lesson_doc = self._resolve_lesson(str(next_item.get("lesson_id") or ""))
                if next_lesson_doc:
                    return next_lesson_doc
                return {
                    "lesson_id": str(next_item.get("lesson_id") or ""),
                    "title": str(next_item.get("title") or ""),
                    "summary": str(next_item.get("summary") or ""),
                }

        if lesson and lesson.get("chapter_id"):
            siblings = self.lesson_repository.list_by_chapter(lesson["chapter_id"])
            ordered = sorted(siblings, key=lambda item: int(item.get("order") or 0))
            for index, item in enumerate(ordered):
                if str(item.get("_id")) != str(lesson_id):
                    continue
                if index + 1 < len(ordered):
                    return ordered[index + 1]
        return None

    def _check_prerequisites(
        self,
        *,
        path_document: Optional[Dict[str, Any]],
        user_id: Optional[str],
        lesson_id: str,
    ) -> tuple[bool, Dict[str, Any]]:
        if not path_document:
            return True, {"prerequisites_supported": False}

        if prerequisite_resolver.path_uses_concept_graph(path_document):
            resolved = prerequisite_resolver.evaluate_lesson_access(
                path_document=path_document,
                lesson_id=lesson_id,
                user_id=user_id,
            )
            return not bool(resolved.get("is_locked")), {
                "prerequisites_supported": True,
                "blocking_lesson_id": resolved.get("blocking_lesson_id"),
                "blocking_concepts": list(resolved.get("blocking_concepts") or []),
                "missing_prerequisite_concepts": list(
                    resolved.get("missing_prerequisite_concepts") or []
                ),
                "prerequisite_mastery": dict(
                    resolved.get("prerequisite_mastery") or {}
                ),
                "bridge_recommendations": list(
                    resolved.get("bridge_recommendations") or []
                ),
                "mastery_threshold": resolved.get("mastery_threshold"),
            }

        flat_lessons: List[str] = []
        for chapter in path_document.get("chapters", []) or []:
            for item in chapter.get("lessons", []) or []:
                lesson_key = str(item.get("lesson_id") or "").strip()
                if lesson_key:
                    flat_lessons.append(lesson_key)

        if lesson_id not in flat_lessons:
            return True, {"prerequisites_supported": True, "lesson_in_path": False}

        position = flat_lessons.index(lesson_id)
        if position <= 0:
            return True, {"prerequisites_supported": True, "blocking_lesson_id": None}

        previous_lesson_id = flat_lessons[position - 1]
        lesson_progress = path_document.get("lesson_progress") or {}
        previous_status = str(lesson_progress.get(previous_lesson_id) or "").strip().lower()
        prerequisites_ok = previous_status in {"complete", "completed"}
        return prerequisites_ok, {
            "prerequisites_supported": True,
            "blocking_lesson_id": None if prerequisites_ok else previous_lesson_id,
            "previous_lesson_status": previous_status or "not_started",
        }

    def _select_resources_from_lesson(
        self,
        *,
        lesson: Optional[Dict[str, Any]],
        preferred_resource_type: Optional[str],
        max_items: int,
        reason: str,
        short_only: bool = False,
    ) -> List[Dict[str, Any]]:
        if not lesson:
            return []

        resource_ids = [
            str(item)
            for item in (
                lesson.get("recommended_resource_ids")
                or lesson.get("resource_ids")
                or []
            )
            if item is not None
        ]
        resources: List[Dict[str, Any]] = []
        for resource_id in resource_ids:
            resource = None
            try:
                if self._is_object_id(resource_id):
                    resource = self.resource_repository.get(resource_id)
            except Exception:
                resource = None
            if resource is None:
                resource = self.resource_repository.collection.find_one({"resource_id": resource_id})
            if resource:
                resources.append(resource)

        if not resources:
            return []

        preferred_resource_type = str(preferred_resource_type or "").strip().lower() or None

        def sort_key(resource: Dict[str, Any]) -> tuple[int, int, str]:
            serialized = self._serialize_resource(resource, reason=reason)
            estimated_time = int(serialized.get("estimated_time") or 10)
            resource_type = str(serialized.get("type") or "").lower()
            type_match = 0 if preferred_resource_type and resource_type == preferred_resource_type else 1
            if short_only:
                return (0 if estimated_time <= 10 else 1, estimated_time, resource_type)
            return (type_match, estimated_time, resource_type)

        resources.sort(key=sort_key)
        serialized_resources = [self._serialize_resource(item, reason=reason) for item in resources]
        if short_only:
            short_resources = [item for item in serialized_resources if int(item.get("estimated_time") or 10) <= 10]
            if short_resources:
                return short_resources[:max_items]
        return serialized_resources[:max_items]

    def _select_fallback_resources(
        self,
        *,
        user_id: str,
        path_document: Optional[Dict[str, Any]],
        mode: str,
        max_items: int,
        short_only: bool = False,
    ) -> List[Dict[str, Any]]:
        goal, level = self._resolve_goal_level(path_document)
        recommended = self.hybrid_recommendation_service.recommend_resources(
            user_id=user_id,
            goal=goal,
            level=level,
            limit=max_items * 2,
            enable_reranking=True,
            mode=mode,
        )
        items = list(recommended.get("recommended", []) or [])
        if short_only:
            short_items = [
                item
                for item in items
                if int(item.get("estimated_time") or 10) <= 10
            ]
            if short_items:
                return short_items[:max_items]
        return items[:max_items]

    def _prepare_reinforcement_quiz(
        self,
        *,
        lesson_id: str,
        target_concepts: Sequence[str],
        snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            current_focus_concepts = list(
                (snapshot or {}).get("current_focus_concepts") or []
            )
            prioritized_targets = self._normalize_target_concepts(
                [
                    *list(target_concepts or []),
                    *current_focus_concepts,
                ]
            )
            quiz_config = self._build_reinforcement_quiz_config(
                snapshot=snapshot,
                target_concepts=prioritized_targets,
            )
            target_quiz_count = int(quiz_config.get("target_count") or 5)
            existing = self.question_generation_service.get_questions_for_lesson(lesson_id)
            matching_existing = [
                item
                for item in existing.get("questions", []) or []
                if self._question_matches_targets(item, prioritized_targets)
            ]
            generated = self.question_generation_service.generate_questions_for_lesson(
                lesson_id=lesson_id,
                target_count=target_quiz_count,
                question_types=list(
                    quiz_config.get("question_types")
                    or ["multiple_choice", "true_false"]
                ),
                difficulty=str(
                    quiz_config.get("recommended_difficulty") or "beginner"
                ),
                bloom_levels=list(
                    quiz_config.get("recommended_bloom_levels")
                    or ["remember", "understand"]
                ),
                allow_llm=bool(quiz_config.get("allow_llm", False)),
                mastery=(
                    0.0
                    if snapshot is None
                    else self._resolve_target_mastery(
                        snapshot=snapshot,
                        target_concepts=prioritized_targets,
                    )
                ),
                success_rate=(
                    0.0
                    if snapshot is None
                    else self._safe_float(snapshot.get("completion_rate"), 0.0)
                ),
                overwrite=True,
                metadata={
                    "adaptive_loop": True,
                    "target_concepts": prioritized_targets,
                    "current_focus_concepts": current_focus_concepts,
                    "quiz_accuracy": self._safe_float(
                        (snapshot or {}).get("quiz_accuracy"),
                        0.0,
                    ),
                    "fail_streak": int((snapshot or {}).get("fail_streak") or 0),
                    "retry_strategy": str(
                        quiz_config.get("retry_strategy") or "paraphrase_question"
                    ),
                    "prefer_template": bool(quiz_config.get("prefer_template", True)),
                    "adaptive_explanation": str(
                        quiz_config.get("adaptive_explanation") or ""
                    ),
                    "generation_strategy": {
                        "template_first": True,
                        "allow_llm": bool(quiz_config.get("allow_llm", False)),
                        "prefer_template": bool(
                            quiz_config.get("prefer_template", True)
                        ),
                        "retry_strategy": str(
                            quiz_config.get("retry_strategy") or "paraphrase_question"
                        ),
                        "paraphrase_question": bool(
                            quiz_config.get("paraphrase_question", False)
                        ),
                        "add_explanation_before_question": bool(
                            quiz_config.get("add_explanation_before_question", False)
                        ),
                    },
                    "previous_questions": [
                        {
                            "question_id": str(item.get("question_id") or "").strip(),
                            "question": str(item.get("question") or "").strip(),
                            "correct_answer": str(item.get("correct_answer") or "").strip(),
                        }
                        for item in matching_existing[:target_quiz_count]
                        if str(item.get("question") or "").strip()
                    ],
                    "previous_question_ids": [
                        str(item.get("question_id") or "").strip()
                        for item in matching_existing[:target_quiz_count]
                        if str(item.get("question_id") or "").strip()
                    ],
                    "generation_reason": "reinforcement_quiz",
                },
            )
            refreshed = self.question_generation_service.get_questions_for_lesson(lesson_id)
            refreshed_matching = [
                item
                for item in refreshed.get("questions", []) or []
                if self._question_matches_targets(item, prioritized_targets)
            ]
            return {
                "generated": True,
                "lesson_id": lesson_id,
                "question_ids": [
                    str(item.get("question_id") or "")
                    for item in refreshed_matching[:target_quiz_count]
                    if str(item.get("question_id") or "").strip()
                ] or list(generated.get("question_ids") or []),
                "question_count": len(refreshed_matching) or int(refreshed.get("total") or 0),
                "status": generated.get("status"),
                "target_concepts": prioritized_targets,
                "reused_targeted_questions": False,
                "recommended_difficulty": str(
                    quiz_config.get("recommended_difficulty") or "beginner"
                ),
                "recommended_bloom_levels": list(
                    quiz_config.get("recommended_bloom_levels")
                    or ["remember", "understand"]
                ),
                "retry_strategy": str(
                    quiz_config.get("retry_strategy") or "paraphrase_question"
                ),
                "question_types": list(
                    quiz_config.get("question_types") or ["multiple_choice"]
                ),
                "adaptive_explanation": str(
                    quiz_config.get("adaptive_explanation") or ""
                ),
            }
        except Exception as exc:
            logger.warning("Adaptive quiz preparation failed for lesson %s: %s", lesson_id, exc)
            return {
                "generated": False,
                "lesson_id": lesson_id,
                "question_ids": [],
                "question_count": 0,
                "error": str(exc),
                "todo": "Question generation fallback failed; frontend can trigger quiz generation later.",
            }

    def record_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        user_id = str(data.get("user_id") or "").strip()
        event_type = self._normalize_event_type(str(data.get("event_type") or ""))
        if not user_id:
            raise ValueError("user_id is required")
        if not event_type:
            raise ValueError("event_type is required")

        concept_ids = self._normalize_string_list(data.get("concept_ids"))
        payload = self._merge_payloads(
            data.get("payload"),
            data.get("metadata"),
            concept_ids,
        )
        document = {
            "event_id": str(data.get("event_id") or f"event_{uuid.uuid4().hex}"),
            "user_id": user_id,
            "path_id": str(data.get("path_id") or "").strip() or None,
            "lesson_id": str(data.get("lesson_id") or "").strip() or None,
            "resource_id": str(data.get("resource_id") or "").strip() or None,
            "question_id": str(data.get("question_id") or "").strip() or None,
            "event_type": event_type,
            "concept_ids": concept_ids,
            "payload": payload,
            "metadata": dict(payload),
            "created_at": data.get("created_at") or self._utcnow(),
        }
        created = self.learning_event_repository.create(document)
        try:
            event_logging_service.log_event(
                event_type=event_type,
                user_id=user_id,
                path_id=document.get("path_id"),
                lesson_id=document.get("lesson_id"),
                resource_id=document.get("resource_id"),
                success=True,
                metadata=dict(payload),
            )
        except Exception:
            logger.debug("Event logging failed for adaptive event %s", event_type, exc_info=True)
        return self._make_json_safe(created)

    def recompute_state(
        self,
        user_id: str,
        path_id: Optional[str],
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot = self.learner_state_service.compute_snapshot(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
        )
        latest_action = self.action_repository.latest(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id or snapshot.get("current_lesson_id"),
        )
        if latest_action:
            snapshot["last_recommended_action"] = str(latest_action.get("action_type") or "")
        persisted = self.snapshot_repository.upsert_latest(snapshot)
        return self._make_json_safe(persisted)

    def get_latest_state(
        self,
        *,
        user_id: str,
        path_id: Optional[str],
        lesson_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        snapshot = self.snapshot_repository.get_latest(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
        )
        return self._make_json_safe(snapshot) if snapshot else None

    def _build_next_step(
        self,
        *,
        user_id: str,
        path_id: Optional[str],
        lesson_id: str,
        persist_action: bool,
        snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
        )
        if not resolved_path_id:
            raise ValueError("path_id is required")

        lesson = self._resolve_lesson(lesson_id)
        if not lesson:
            raise ValueError("Lesson not found.")

        computed_snapshot = snapshot or self.recompute_state(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=lesson_id,
        )
        path_document = self._resolve_path_document(resolved_path_id)
        prerequisites_ok, prerequisite_metadata = self._check_prerequisites(
            path_document=path_document,
            user_id=user_id,
            lesson_id=lesson_id,
        )
        decision = self.decision_service.decide_next_action(
            computed_snapshot,
            lesson,
            prerequisites_ok=prerequisites_ok,
        )

        resources: List[Dict[str, Any]] = []
        metadata = dict(decision.get("metadata") or {})
        metadata.update(prerequisite_metadata)

        if decision["action"] == self.decision_service.ASSIGN_REMEDIAL_RESOURCE:
            resources = self._select_resources_from_lesson(
                lesson=lesson,
                preferred_resource_type=computed_snapshot.get("preferred_resource_type"),
                max_items=3,
                reason="Remedial resource selected for the current weak concept.",
            )
            if not resources:
                resources = self._select_fallback_resources(
                    user_id=str(user_id),
                    path_document=path_document,
                    mode="reinforce_weaknesses",
                    max_items=3,
                )
        elif decision["action"] == self.decision_service.RECOMMEND_SHORT_RESOURCE:
            resources = self._select_resources_from_lesson(
                lesson=lesson,
                preferred_resource_type=computed_snapshot.get("preferred_resource_type"),
                max_items=3,
                reason="A short resource is recommended to recover engagement.",
                short_only=True,
            )
            if not resources:
                resources = self._select_fallback_resources(
                    user_id=str(user_id),
                    path_document=path_document,
                    mode="continue_learning",
                    max_items=3,
                    short_only=True,
                )
        elif decision["action"] == self.decision_service.REVIEW_WEAK_CONCEPT:
            resources = self._select_resources_from_lesson(
                lesson=lesson,
                preferred_resource_type=computed_snapshot.get("preferred_resource_type"),
                max_items=2,
                reason="Review material for the weakest concept before continuing.",
            )

        if decision.get("should_generate_quiz"):
            metadata["quiz"] = self._prepare_reinforcement_quiz(
                lesson_id=lesson_id,
                target_concepts=decision.get("target_concepts") or [],
                snapshot=computed_snapshot,
            )

        next_lesson = self._find_next_lesson(
            path_document=path_document,
            lesson_id=lesson_id,
            lesson=lesson,
        )
        if decision.get("should_unlock_next") and next_lesson:
            metadata["next_lesson_id"] = str(next_lesson.get("_id") or next_lesson.get("lesson_id") or "")
            metadata["next_lesson_title"] = str(next_lesson.get("title") or "")
            lesson_progress = path_document.get("lesson_progress") if path_document else {}
            metadata["unlock_supported"] = bool(path_document is not None)
            metadata["current_lesson_status"] = (
                str((lesson_progress or {}).get(lesson_id) or "").strip().lower()
                if isinstance(lesson_progress, dict)
                else ""
            )
            metadata["next_lesson_unlocked"] = bool(
                metadata.get("current_lesson_status") in {"complete", "completed"}
            )
            if not metadata["next_lesson_unlocked"]:
                metadata["todo"] = (
                    "Learning path locking is derived from lesson_progress. "
                    "Current lesson must already be completed for the next lesson to unlock automatically."
                )

        resource_ids = [
            str(item.get("resource_id") or "")
            for item in resources
            if str(item.get("resource_id") or "").strip()
        ]
        action_log = {
            "action_id": f"action_{uuid.uuid4().hex}",
            "user_id": str(user_id),
            "path_id": resolved_path_id,
            "lesson_id": str(lesson_id),
            "action_type": str(decision["action"]),
            "reason": str(decision["reason"]),
            "target_concepts": list(decision.get("target_concepts") or []),
            "resource_ids": resource_ids,
            "metadata": metadata,
            "created_at": self._utcnow(),
        }
        if persist_action:
            self.action_repository.create(action_log)

        quiz_summary = self._extract_quiz_response_fields(metadata.get("quiz"))
        return {
            "action": str(decision["action"]),
            "reason": str(decision["reason"]),
            "target_concepts": list(decision.get("target_concepts") or []),
            "resources": self._make_json_safe(resources),
            "should_generate_quiz": bool(decision.get("should_generate_quiz")),
            "should_unlock_next": bool(decision.get("should_unlock_next")),
            "snapshot": self._make_json_safe(computed_snapshot),
            "metadata": self._make_json_safe(metadata),
            **quiz_summary,
        }

    def run_next_step(self, user_id: str, path_id: str, lesson_id: str) -> Dict[str, Any]:
        return self._build_next_step(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
            persist_action=True,
        )

    def get_adaptive_explanation(
        self,
        user_id: str,
        path_id: Optional[str],
        lesson_id: str,
    ) -> Dict[str, Any]:
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
        )
        if not resolved_path_id:
            raise ValueError("path_id is required")

        latest_snapshot = self.get_latest_state(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=lesson_id,
        ) or self.recompute_state(str(user_id), resolved_path_id, lesson_id)
        latest_action = self.action_repository.latest(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=lesson_id,
        )
        if latest_action:
            action = str(latest_action.get("action_type") or self.decision_service.NO_ACTION)
            reason = str(latest_action.get("reason") or "")
            target_concepts = list(latest_action.get("target_concepts") or [])
            latest_action_metadata = (
                latest_action.get("metadata")
                if isinstance(latest_action.get("metadata"), dict)
                else {}
            )
            quiz_summary = self._extract_quiz_response_fields(
                latest_action_metadata.get("quiz")
            )
        else:
            step = self._build_next_step(
                user_id=str(user_id),
                path_id=resolved_path_id,
                lesson_id=lesson_id,
                persist_action=False,
                snapshot=latest_snapshot,
            )
            action = str(step.get("action") or self.decision_service.NO_ACTION)
            reason = str(step.get("reason") or "")
            target_concepts = list(step.get("target_concepts") or [])
            quiz_summary = self._extract_quiz_response_fields(step.get("quiz"))
            if not quiz_summary.get("quiz"):
                quiz_summary = {
                    "recommended_difficulty": step.get("recommended_difficulty"),
                    "recommended_bloom_levels": list(
                        step.get("recommended_bloom_levels") or []
                    ),
                    "retry_strategy": step.get("retry_strategy"),
                    "question_types": list(step.get("question_types") or []),
                    "adaptive_explanation": step.get("adaptive_explanation"),
                    "quiz": self._make_json_safe(step.get("quiz"))
                    if step.get("quiz") is not None
                    else None,
                }

        explanation = (
            f"The system chose {action} because {reason.lower()} "
            f"Current accuracy is {self._safe_float(latest_snapshot.get('quiz_accuracy'), 0.0):.0%}, "
            f"engagement is {self._safe_float(latest_snapshot.get('engagement_score'), 0.0):.0%}, "
            f"and fatigue is {self._safe_float(latest_snapshot.get('fatigue_score'), 0.0):.0%}."
        )
        if target_concepts:
            explanation += f" Focus concept: {', '.join(target_concepts)}."
        if quiz_summary.get("adaptive_explanation"):
            explanation += f" {str(quiz_summary['adaptive_explanation'])}"

        return {
            "user_id": str(user_id),
            "path_id": resolved_path_id,
            "lesson_id": str(lesson_id),
            "action": action,
            "reason": reason,
            "target_concepts": target_concepts,
            "explanation": explanation,
            "snapshot": self._make_json_safe(latest_snapshot),
            **quiz_summary,
        }

    def ingest_learning_event(
        self,
        *,
        user_id: str,
        event_type: str,
        resource_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        path_id: Optional[str] = None,
        concept_ids: Sequence[str] | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        created = self.record_event(
            {
                "user_id": user_id,
                "event_type": event_type,
                "resource_id": resource_id,
                "lesson_id": lesson_id,
                "path_id": path_id,
                "concept_ids": list(concept_ids or []),
                "payload": dict(metadata or {}),
            }
        )
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=lesson_id,
            latest_event=created,
        )
        if resolved_path_id:
            try:
                self.recompute_state(str(user_id), resolved_path_id, lesson_id)
            except Exception:
                logger.debug("Adaptive snapshot recompute failed after ingest.", exc_info=True)
        return created

    def update_learner_state(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        latest_event: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id or ((latest_event or {}).get("path_id") if latest_event else None),
            lesson_id=(latest_event or {}).get("lesson_id") if latest_event else None,
            latest_event=latest_event,
        )
        lesson_id = str((latest_event or {}).get("lesson_id") or "").strip() or None
        snapshot = self.learner_state_service.compute_snapshot(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=lesson_id,
        )
        latest_action = self.action_repository.latest(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=lesson_id or snapshot.get("current_lesson_id"),
        )
        if latest_action:
            snapshot["last_recommended_action"] = str(latest_action.get("action_type") or "")
        if latest_event:
            snapshot["last_event_type"] = str(latest_event.get("event_type") or "")
        if not persist:
            return self._make_json_safe(snapshot)
        return self._make_json_safe(self.snapshot_repository.upsert_latest(snapshot))

    @staticmethod
    def _build_no_lesson_next_action(
        *,
        user_id: str,
        reason: str,
    ) -> Dict[str, Any]:
        return {
            "user_id": str(user_id),
            "next_best_action": "review_summary",
            "reason": reason,
            "priority": "medium",
            "recommended_mode": "continue_learning",
            "target_concepts": [],
            "lesson_id": None,
            "resource_id": None,
            "estimated_total_time": None,
        }

    @staticmethod
    def _build_no_lesson_recommendation(
        *,
        user_id: str,
        reason: str,
        items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        safe_items = list(items or [])
        estimated_total_time = sum(
            int(item.get("estimated_time") or item.get("estimated_read_time") or 0)
            for item in safe_items
            if isinstance(item, dict)
        )
        return {
            "user_id": str(user_id),
            "action": "review_summary",
            "recommendation_type": "resource",
            "recommendation_mode": "continue_learning",
            "items": safe_items,
            "reason": reason,
            "target_concepts": [],
            "estimated_total_time": estimated_total_time,
            "lesson_id": None,
            "resource_id": str(safe_items[0].get("resource_id")) if safe_items and safe_items[0].get("resource_id") else None,
        }

    def decide_next_best_action(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        learner_snapshot: Optional[Dict[str, Any]] = None,
        latest_event: Optional[Dict[str, Any]] = None,
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id or (learner_snapshot or {}).get("path_id"),
            lesson_id=lesson_id or (learner_snapshot or {}).get("current_lesson_id"),
            latest_event=latest_event,
        )
        resolved_lesson_id = str(
            lesson_id
            or (learner_snapshot or {}).get("current_lesson_id")
            or (latest_event or {}).get("lesson_id")
            or ""
        ).strip()
        if not resolved_lesson_id:
            return self._build_no_lesson_next_action(
                user_id=str(user_id),
                reason=(
                    "No active lesson is available yet. Open a lesson or continue a learning path "
                    "to receive the next adaptive action."
                ),
            )

        snapshot = learner_snapshot or self.get_latest_state(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=resolved_lesson_id,
        ) or self.recompute_state(str(user_id), resolved_path_id, resolved_lesson_id)
        step = self._build_next_step(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=resolved_lesson_id,
            persist_action=False,
            snapshot=snapshot,
        )
        legacy_action = self._LEGACY_ACTION_MAP.get(step["action"], "review_summary")
        priority = "high" if step["action"] in {
            self.decision_service.ASSIGN_REMEDIAL_RESOURCE,
            self.decision_service.REVIEW_WEAK_CONCEPT,
        } else "medium"
        estimated_total_time = sum(
            int(item.get("estimated_time") or item.get("estimated_read_time") or 0)
            for item in step.get("resources", [])
            if isinstance(item, dict)
        )
        if estimated_total_time <= 0 and step.get("should_generate_quiz"):
            estimated_total_time = 10
        return {
            "user_id": str(user_id),
            "next_best_action": legacy_action,
            "reason": str(step["reason"]),
            "priority": priority,
            "recommended_mode": self._LEGACY_MODE_MAP.get(legacy_action, "continue_learning"),
            "target_concepts": list(step.get("target_concepts") or []),
            "lesson_id": resolved_lesson_id,
            "resource_id": (
                str(step.get("resources", [{}])[0].get("resource_id"))
                if step.get("resources")
                else None
            ),
            "estimated_total_time": estimated_total_time or None,
        }

    def generate_adaptive_recommendation(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        goal: Optional[str] = None,
        level: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_lesson_id = str(lesson_id or "").strip()
        resolved_path_id = self._resolve_latest_path_id(
            user_id=str(user_id),
            path_id=path_id,
            lesson_id=resolved_lesson_id or None,
        )
        if not resolved_lesson_id:
            latest_snapshot = self.get_latest_state(
                user_id=str(user_id),
                path_id=resolved_path_id,
            )
            resolved_lesson_id = str((latest_snapshot or {}).get("current_lesson_id") or "").strip()
        if not resolved_lesson_id:
            path_document = self._resolve_path_document(resolved_path_id)
            fallback_items = self._select_fallback_resources(
                user_id=str(user_id),
                path_document=path_document,
                mode="continue_learning",
                max_items=3,
            )
            return self._build_no_lesson_recommendation(
                user_id=str(user_id),
                reason=(
                    "No active lesson is available yet. Here are general resources to help you "
                    "continue learning until a lesson is opened."
                ),
                items=self._make_json_safe(fallback_items),
            )

        step = self._build_next_step(
            user_id=str(user_id),
            path_id=resolved_path_id,
            lesson_id=resolved_lesson_id,
            persist_action=False,
        )
        legacy_action = self._LEGACY_ACTION_MAP.get(step["action"], "review_summary")
        recommendation_type = "resource"
        items = list(step.get("resources") or [])

        if step.get("should_unlock_next"):
            path_document = self._resolve_path_document(resolved_path_id)
            lesson = self._resolve_lesson(resolved_lesson_id)
            next_lesson = self._find_next_lesson(
                path_document=path_document,
                lesson_id=resolved_lesson_id,
                lesson=lesson,
            )
            if next_lesson:
                items = [
                    {
                        "lesson_id": str(next_lesson.get("_id") or next_lesson.get("lesson_id") or ""),
                        "title": str(next_lesson.get("title") or ""),
                        "summary": str(next_lesson.get("summary") or ""),
                        "estimated_time": 15,
                    }
                ]
                recommendation_type = "lesson"

        if not items:
            path_document = self._resolve_path_document(resolved_path_id)
            items = self._select_fallback_resources(
                user_id=str(user_id),
                path_document=path_document,
                mode="continue_learning",
                max_items=3,
            )
            recommendation_type = "resource"

        del goal, level
        estimated_total_time = sum(
            int(item.get("estimated_time") or item.get("estimated_read_time") or 0)
            for item in items
            if isinstance(item, dict)
        )
        return {
            "user_id": str(user_id),
            "action": legacy_action,
            "recommendation_type": recommendation_type,
            "recommendation_mode": self._LEGACY_MODE_MAP.get(legacy_action, "continue_learning"),
            "items": self._make_json_safe(items),
            "reason": str(step.get("reason") or ""),
            "target_concepts": list(step.get("target_concepts") or []),
            "estimated_total_time": estimated_total_time,
            "lesson_id": resolved_lesson_id,
            "resource_id": str(items[0].get("resource_id")) if items and items[0].get("resource_id") else None,
        }


adaptive_learning_loop_service = AdaptiveLearningLoopService()
