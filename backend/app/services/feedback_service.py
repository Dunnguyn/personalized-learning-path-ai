"""Feedback loop service to normalize explicit, implicit, and outcome signals."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from backend.app.repositories.learner_signal_repository import LearnerSignalRepository


def _bounded(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


class FeedbackService:
    """Collect and normalize learner feedback into structured signals."""

    def __init__(self) -> None:
        self.repository = LearnerSignalRepository()

    def record_explicit_feedback(
        self,
        *,
        user_id: str,
        feedback_type: str,
        value: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        concept_id: Optional[int] = None,
        resource_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": str(user_id),
            "feedback_type": feedback_type,
            "value": value,
            "path_id": path_id,
            "lesson_id": lesson_id,
            "concept_id": concept_id,
            "resource_id": resource_id,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }
        feedback = self.repository.create_feedback(payload)
        signal = self._normalize_explicit(feedback)
        self.repository.create_signal(signal)
        return feedback

    def process_implicit_feedback(
        self,
        *,
        user_id: str,
        signal_type: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        concept_id: Optional[int] = None,
        resource_id: Optional[int] = None,
        value: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        signal = {
            "user_id": str(user_id),
            "signal_type": signal_type,
            "source": "implicit",
            "path_id": path_id,
            "lesson_id": lesson_id,
            "concept_id": concept_id,
            "resource_id": resource_id,
            "value": _bounded(value),
            "strength": abs(_bounded(value)),
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
        }
        return self.repository.create_signal(signal)

    def process_outcome_feedback(
        self,
        *,
        user_id: str,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
        concept_id: Optional[int] = None,
        quiz_accuracy: Optional[float] = None,
        confidence_gain: Optional[float] = None,
        mastery_gain: Optional[float] = None,
        completion_rate: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        created: List[Dict[str, Any]] = []
        outcome_map = {
            "quiz_accuracy": quiz_accuracy,
            "confidence_gain": confidence_gain,
            "mastery_gain": mastery_gain,
            "completion_rate": completion_rate,
        }
        for key, raw_value in outcome_map.items():
            if raw_value is None:
                continue
            normalized = (
                _bounded(raw_value * 2.0 - 1.0)
                if key in {"quiz_accuracy", "completion_rate"}
                else _bounded(raw_value)
            )
            created.append(
                self.repository.create_signal(
                    {
                        "user_id": str(user_id),
                        "signal_type": key,
                        "source": "outcome",
                        "path_id": path_id,
                        "lesson_id": lesson_id,
                        "concept_id": concept_id,
                        "value": normalized,
                        "strength": abs(normalized),
                        "metadata": metadata or {},
                        "created_at": datetime.utcnow(),
                    }
                )
            )
        return created

    def summarize_user_signals(self, *, user_id: str, days: int = 14) -> Dict[str, Any]:
        signals = self.repository.list_signals(user_id=user_id, limit=500)
        since = datetime.utcnow() - timedelta(days=max(1, days))
        scoped = [
            item
            for item in signals
            if item.get("created_at") and item.get("created_at") >= since
        ]

        if not scoped:
            return {
                "window_days": days,
                "total_signals": 0,
                "implicit_load": 0.0,
                "explicit_difficulty": 0.0,
                "avg_quiz_accuracy": 0.0,
                "confidence_gain": 0.0,
                "completion_rate": 0.0,
            }

        quiz_values = [
            self._to_unit(item.get("value"))
            for item in scoped
            if item.get("signal_type") == "quiz_accuracy"
        ]
        completion_values = [
            self._to_unit(item.get("value"))
            for item in scoped
            if item.get("signal_type") == "completion_rate"
        ]
        conf_gain = [
            float(item.get("value") or 0.0)
            for item in scoped
            if item.get("signal_type") == "confidence_gain"
        ]
        implicit_values = [
            float(item.get("value") or 0.0)
            for item in scoped
            if item.get("source") == "implicit"
        ]

        explicit_difficulty = [
            float(item.get("value") or 0.0)
            for item in scoped
            if item.get("signal_type")
            in {"explicit_too_difficult", "explicit_need_faster"}
        ]

        return {
            "window_days": days,
            "total_signals": len(scoped),
            "implicit_load": round(
                sum(abs(v) for v in implicit_values) / max(len(implicit_values), 1), 4
            ),
            "explicit_difficulty": round(
                sum(explicit_difficulty) / max(len(explicit_difficulty), 1), 4
            ),
            "avg_quiz_accuracy": round(sum(quiz_values) / max(len(quiz_values), 1), 4),
            "confidence_gain": round(sum(conf_gain) / max(len(conf_gain), 1), 4),
            "completion_rate": round(
                sum(completion_values) / max(len(completion_values), 1), 4
            ),
        }

    def list_feedback(self, *, user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.repository.list_feedback(user_id=user_id, limit=limit)

    def _normalize_explicit(self, feedback: Dict[str, Any]) -> Dict[str, Any]:
        feedback_type = str(feedback.get("feedback_type") or "generic").lower()
        value = str(feedback.get("value") or "").strip().lower()

        signal_type = "explicit_generic"
        score = 0.0
        if (
            "kh" in value
            or "difficult" in value
            or feedback_type in {"too_difficult", "hard"}
        ):
            signal_type = "explicit_too_difficult"
            score = -0.8
        elif "hữu ích" in value or "helpful" in value:
            signal_type = "explicit_helpful"
            score = 0.8
        elif "nhanh" in value or "faster" in value:
            signal_type = "explicit_need_faster"
            score = 0.6

        return {
            "user_id": str(feedback.get("user_id")),
            "signal_type": signal_type,
            "source": "explicit",
            "path_id": feedback.get("path_id"),
            "lesson_id": feedback.get("lesson_id"),
            "concept_id": feedback.get("concept_id"),
            "resource_id": feedback.get("resource_id"),
            "value": score,
            "strength": abs(score),
            "metadata": {
                "feedback_type": feedback.get("feedback_type"),
                "raw_value": feedback.get("value"),
                **(feedback.get("metadata") or {}),
            },
            "created_at": datetime.utcnow(),
        }

    @staticmethod
    def _to_unit(value: Any) -> float:
        v = float(value or 0.0)
        return max(0.0, min(1.0, (v + 1.0) / 2.0))


feedback_service = FeedbackService()
