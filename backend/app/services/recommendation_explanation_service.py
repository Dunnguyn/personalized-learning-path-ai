"""Build structured explanations for personalized recommendations."""

from __future__ import annotations

from typing import Any, Dict, List


class RecommendationExplanationService:
    """Turn recommendation signals into structured explanations."""

    _MODE_TEMPLATES = {
        "continue_learning": "Continues a resource stream you already started and can finish in this session.",
        "reinforce_weaknesses": "Helps reinforce concepts that are currently below your target mastery.",
        "learn_new": "Moves you into a new concept area with prerequisite-aligned difficulty.",
        "quick_review": "Fits a short review session with compact content and quick recall value.",
    }

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _estimated_time(resource: Dict[str, Any], learner_state: Dict[str, Any]) -> int:
        metadata = resource.get("metadata") or {}
        explicit = metadata.get("estimated_time") or metadata.get("estimated_minutes")
        if explicit is not None:
            try:
                return max(5, int(float(explicit)))
            except Exception:
                pass

        chunk_count = int(resource.get("chunks_count") or metadata.get("chunk_count") or 1)
        avg_session = float(learner_state.get("avg_session_duration") or 12.0)
        return max(6, min(35, int(round(0.7 * avg_session + chunk_count * 2.0))))

    @staticmethod
    def _primary_concepts(
        resource: Dict[str, Any],
        learner_state: Dict[str, Any],
    ) -> List[str]:
        concepts: List[str] = []
        metadata = resource.get("metadata") or {}
        for value in (
            metadata.get("primary_concepts"),
            metadata.get("covered_concepts"),
            learner_state.get("current_focus_concepts"),
        ):
            if isinstance(value, list):
                for item in value:
                    token = str(item or "").strip()
                    if token and token not in concepts:
                        concepts.append(token)
            elif value:
                token = str(value).strip()
                if token and token not in concepts:
                    concepts.append(token)
        topic = str(resource.get("topic") or "").strip()
        if topic and topic not in concepts:
            concepts.append(topic)
        return concepts[:4]

    def build_explanation(
        self,
        *,
        resource: Dict[str, Any],
        mode: str,
        learner_state: Dict[str, Any],
        score_breakdown: Dict[str, float],
        goal: str,
        level: str,
        quality_score: float,
        expected_learning_gain: float,
    ) -> Dict[str, Any]:
        estimated_time = self._estimated_time(resource, learner_state)
        primary_concepts = self._primary_concepts(resource, learner_state)
        tags: List[str] = []
        reasons: List[str] = []

        if mode == "continue_learning":
            tags.append("continue_learning")
            if int(learner_state.get("unfinished_resources") or 0) > 0:
                tags.append("unfinished_resource")
        elif mode == "reinforce_weaknesses":
            tags.extend(["weak_concept", "reinforce_weaknesses"])
        elif mode == "learn_new":
            tags.extend(["learn_new", "prerequisite_ready"])
        elif mode == "quick_review":
            tags.extend(["quick_review", "short_session"])

        if score_breakdown.get("difficulty_fit", 0.0) >= 0.72:
            tags.append(f"{level}_fit")
            reasons.append(f"Difficulty fits your current {level} level.")

        if expected_learning_gain >= 0.7:
            tags.append("high_learning_gain")
            reasons.append("Expected learning gain is high for your current learner state.")

        if quality_score >= 0.72:
            tags.append("high_quality")
            reasons.append("Quality signals suggest this resource is complete and reliable.")

        if estimated_time <= 15:
            tags.append("short_session")
            reasons.append("Estimated time fits a short 10-15 minute session.")

        if primary_concepts:
            reasons.append(
                f"Primary focus: {', '.join(primary_concepts[:2])}."
            )

        if score_breakdown.get("concept_gap_fit", 0.0) >= 0.68:
            reasons.append(
                "Targets concepts where you still have meaningful mastery and confidence gaps."
            )

        if not reasons:
            reasons.append(self._MODE_TEMPLATES.get(mode, "Matches your current learning goal."))

        summary = reasons[0]
        if len(reasons) > 1:
            summary = f"{reasons[0]} {reasons[1]}"

        return {
            "reason": summary,
            "reason_tags": tags[:5],
            "estimated_time": estimated_time,
            "primary_concepts": primary_concepts,
            "recommendation_mode": mode,
            "explanation_details": reasons,
            "goal_match_note": f"Aligned with goal: {goal}.",
        }


recommendation_explanation_service = RecommendationExplanationService()
