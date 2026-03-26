"""Knowledge tracing service for probabilistic concept state estimation."""

from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db
from backend.app.repositories.kt_repository import KnowledgeTracingRepository


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


class KnowledgeTracingService:
    """Maintain concept mastery states from learner interactions."""

    def __init__(self) -> None:
        self.repository = KnowledgeTracingRepository()
        self.db = get_db()

    def resolve_concepts_for_lesson(
        self, lesson_id: str, max_items: int = 5
    ) -> List[int]:
        lesson = self.db.lessons.find_one({"_id": self._to_object_id(lesson_id)})
        if not lesson:
            return []

        direct = lesson.get("concept_ids") or []
        concept_ids = [int(item) for item in direct if self._is_int(item)]
        if concept_ids:
            return concept_ids[:max_items]

        topic = str(lesson.get("topic") or "").strip()
        title = str(lesson.get("title") or "").strip()
        keywords = [
            str(item).strip()
            for item in (lesson.get("keywords") or [])
            if str(item).strip()
        ]

        clauses: List[Dict[str, Any]] = []
        if topic:
            clauses.append({"topic": {"$regex": topic, "$options": "i"}})

        for token in [title, *keywords[:4]]:
            if token:
                clauses.append({"concept_name": {"$regex": token, "$options": "i"}})

        if not clauses:
            return []

        docs = list(
            self.db.concepts.find({"$or": clauses}, {"concept_id": 1}).limit(max_items)
        )
        return [
            int(item.get("concept_id"))
            for item in docs
            if self._is_int(item.get("concept_id"))
        ]

    def bootstrap_from_generated_path(
        self,
        *,
        user_id: str,
        path_id: str,
        subject_id: Optional[str],
        chapters: List[Dict[str, Any]],
    ) -> int:
        initialized = 0
        for chapter in chapters or []:
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "").strip()
                if not lesson_id:
                    continue
                for concept_id in self.resolve_concepts_for_lesson(lesson_id):
                    state = self.repository.get_state(
                        user_id=user_id, concept_id=concept_id, lesson_id=lesson_id
                    )
                    if state:
                        continue
                    self.repository.upsert_state(
                        {
                            "user_id": str(user_id),
                            "subject_id": subject_id,
                            "path_id": str(path_id),
                            "lesson_id": lesson_id,
                            "concept_id": int(concept_id),
                            "p_mastery": 0.35,
                            "confidence_score": 0.30,
                            "evidence_count": 0,
                            "recent_correct_rate": 0.0,
                            "recent_attempts": [],
                            "avg_time_spent": 0.0,
                            "status": "weak",
                            "last_interaction_at": None,
                            "last_updated_at": datetime.utcnow(),
                            "metadata": {"bootstrap": True},
                        }
                    )
                    initialized += 1
        return initialized

    def update_from_interaction(
        self,
        *,
        user_id: str,
        event_type: str,
        lesson_id: Optional[str] = None,
        concept_id: Optional[int] = None,
        subject_id: Optional[str] = None,
        path_id: Optional[str] = None,
        is_correct: Optional[bool] = None,
        confidence: Optional[float] = None,
        time_spent_seconds: Optional[float] = None,
        repeated_attempt: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        concept_ids: List[int] = []
        if concept_id is not None and self._is_int(concept_id):
            concept_ids = [int(concept_id)]
        elif lesson_id:
            concept_ids = self.resolve_concepts_for_lesson(lesson_id)

        if not concept_ids:
            return []

        updated_states: List[Dict[str, Any]] = []
        for cid in concept_ids:
            state = self.repository.get_state(
                user_id=user_id, concept_id=cid, lesson_id=lesson_id
            )
            if not state:
                state = {
                    "user_id": str(user_id),
                    "subject_id": subject_id,
                    "path_id": path_id,
                    "lesson_id": lesson_id,
                    "concept_id": int(cid),
                    "p_mastery": 0.35,
                    "confidence_score": 0.30,
                    "evidence_count": 0,
                    "recent_correct_rate": 0.0,
                    "recent_attempts": [],
                    "avg_time_spent": 0.0,
                    "status": "weak",
                    "metadata": {},
                }

            updated = self._apply_update(
                state=state,
                event_type=event_type,
                is_correct=is_correct,
                confidence=confidence,
                time_spent_seconds=time_spent_seconds,
                repeated_attempt=repeated_attempt,
                metadata=metadata or {},
            )
            updated["subject_id"] = subject_id or updated.get("subject_id")
            updated["path_id"] = path_id or updated.get("path_id")
            updated["lesson_id"] = (
                lesson_id if lesson_id is not None else updated.get("lesson_id")
            )
            stored = self.repository.upsert_state(updated)
            updated_states.append(stored)

        return updated_states

    def get_user_concept_states(
        self, *, user_id: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        return self.repository.list_user_states(user_id=user_id, limit=limit)

    def get_user_lesson_states(
        self, *, user_id: str, lesson_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self.repository.list_user_lesson_states(
            user_id=user_id, lesson_id=lesson_id, limit=limit
        )

    def _apply_update(
        self,
        *,
        state: Dict[str, Any],
        event_type: str,
        is_correct: Optional[bool],
        confidence: Optional[float],
        time_spent_seconds: Optional[float],
        repeated_attempt: bool,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        now = datetime.utcnow()
        prior = _clamp(float(state.get("p_mastery", 0.35) or 0.35))
        confidence_score = _clamp(float(state.get("confidence_score", 0.30) or 0.30))
        evidence_count = int(state.get("evidence_count", 0) or 0)

        recent_attempts = list(state.get("recent_attempts", []) or [])
        attempts_window = recent_attempts[-19:]

        delta = 0.0
        if is_correct is not None:
            slip = 0.12
            guess = 0.18
            if is_correct:
                numerator = prior * (1.0 - slip)
                denominator = numerator + ((1.0 - prior) * guess)
                posterior = numerator / denominator if denominator > 0 else prior
                learning_rate = 0.10 + min(
                    max((time_spent_seconds or 0.0) / 1200.0, 0.0), 0.12
                )
                posterior = posterior + (1.0 - posterior) * learning_rate
            else:
                numerator = prior * slip
                denominator = numerator + ((1.0 - prior) * (1.0 - guess))
                posterior = numerator / denominator if denominator > 0 else prior
                posterior = posterior * (0.92 if repeated_attempt else 0.95)
            updated_mastery = _clamp(posterior)
        else:
            event_adjustments = {
                "lesson_completed": 0.05,
                "resource_completed": 0.03,
                "resource_skipped": -0.04,
                "ai_tutor_asked": 0.01,
                "repeated_attempt": -0.03,
                "feedback_too_difficult": -0.05,
                "feedback_helpful": 0.02,
            }
            delta = float(event_adjustments.get(event_type, 0.0))
            updated_mastery = _clamp(prior + delta)

        if confidence is not None:
            confidence_score = _clamp(
                0.75 * confidence_score + 0.25 * float(confidence)
            )

        if is_correct is not None:
            attempts_window.append(
                {
                    "at": now,
                    "event_type": event_type,
                    "correct": bool(is_correct),
                    "confidence": confidence,
                    "time_spent_seconds": time_spent_seconds,
                }
            )
            evidence_count += 1
        elif event_type in {"resource_completed", "resource_skipped", "ai_tutor_asked"}:
            attempts_window.append(
                {
                    "at": now,
                    "event_type": event_type,
                    "correct": None,
                    "confidence": confidence,
                    "time_spent_seconds": time_spent_seconds,
                }
            )
            evidence_count += 1

        scored_attempts = [
            item for item in attempts_window if item.get("correct") is not None
        ]
        if scored_attempts:
            recent_correct_rate = sum(
                1 for item in scored_attempts if item.get("correct") is True
            ) / float(len(scored_attempts))
        else:
            recent_correct_rate = float(state.get("recent_correct_rate", 0.0) or 0.0)

        prev_time = float(state.get("avg_time_spent", 0.0) or 0.0)
        if time_spent_seconds is not None and time_spent_seconds >= 0:
            avg_time_spent = (
                (0.8 * prev_time) + (0.2 * float(time_spent_seconds))
                if prev_time > 0
                else float(time_spent_seconds)
            )
        else:
            avg_time_spent = prev_time

        status = "weak"
        if updated_mastery >= 0.70:
            status = "strong"
        elif updated_mastery >= 0.40:
            status = "developing"

        updated = dict(state)
        updated.update(
            {
                "p_mastery": round(updated_mastery, 4),
                "confidence_score": round(confidence_score, 4),
                "evidence_count": int(evidence_count),
                "recent_correct_rate": round(_clamp(recent_correct_rate), 4),
                "recent_attempts": attempts_window[-20:],
                "avg_time_spent": round(max(0.0, avg_time_spent), 3),
                "status": status,
                "last_interaction_at": now,
                "last_updated_at": now,
                "metadata": {
                    **(state.get("metadata") or {}),
                    "last_event_type": event_type,
                    "last_delta": round(delta, 4),
                    "update_source": metadata.get("source", "interaction"),
                },
            }
        )
        return updated

    @staticmethod
    def _to_object_id(value: Optional[str]):
        if not value:
            return None
        try:
            from bson import ObjectId

            return ObjectId(str(value))
        except Exception:
            return None

    @staticmethod
    def _is_int(value: Any) -> bool:
        try:
            int(value)
            return True
        except Exception:
            return False


knowledge_tracing_service = KnowledgeTracingService()
