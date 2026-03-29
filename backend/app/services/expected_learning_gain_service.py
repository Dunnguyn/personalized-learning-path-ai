"""Runtime access to expected learning gain statistics with heuristic fallback."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.app.repositories.expected_learning_gain_repository import (
    ExpectedLearningGainRepository,
)


class ExpectedLearningGainService:
    """Serve expected gain estimates from precomputed stats or heuristics."""

    def __init__(self) -> None:
        self.repository = ExpectedLearningGainRepository()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    def get_expected_gain(
        self,
        *,
        resource_id: str,
        concept_id: Optional[str],
        mastery_gap: float,
        confidence_gap: float,
        quality_score: float,
        concept_relevance: float,
    ) -> Dict[str, Any]:
        stat = self.repository.get_stat(resource_id=resource_id, concept_id=concept_id)
        if stat:
            avg_mastery_gain = self._safe_float(stat.get("avg_mastery_gain"), 0.0)
            avg_confidence_gain = self._safe_float(stat.get("avg_confidence_gain"), 0.0)
            avg_quiz_uplift = self._safe_float(stat.get("avg_quiz_uplift"), 0.0)
            expected_gain = self._clamp(
                0.45 * avg_mastery_gain
                + 0.25 * avg_confidence_gain
                + 0.30 * avg_quiz_uplift
            )
            return {
                "expected_learning_gain": round(expected_gain, 4),
                "avg_mastery_gain": round(avg_mastery_gain, 4),
                "avg_confidence_gain": round(avg_confidence_gain, 4),
                "avg_quiz_uplift": round(avg_quiz_uplift, 4),
                "sample_size": int(stat.get("sample_size") or 0),
                "source": "precomputed",
            }

        heuristic = self._clamp(
            0.35 * mastery_gap
            + 0.20 * confidence_gap
            + 0.25 * quality_score
            + 0.20 * concept_relevance
        )
        return {
            "expected_learning_gain": round(heuristic, 4),
            "avg_mastery_gain": round(0.55 * heuristic, 4),
            "avg_confidence_gain": round(0.35 * heuristic, 4),
            "avg_quiz_uplift": round(0.45 * heuristic, 4),
            "sample_size": 0,
            "source": "heuristic",
        }


expected_learning_gain_service = ExpectedLearningGainService()
