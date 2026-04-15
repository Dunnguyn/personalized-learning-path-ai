"""Build concise explanations for personalized recommendations."""

from __future__ import annotations

from typing import Any, Dict, List


class RecommendationExplanationService:
    """Turn recommendation signals into concise explanations."""

    _MODE_TEMPLATES = {
        "continue_learning": "Keeps you moving through material that matches your current path.",
        "reinforce_weaknesses": "Helps reinforce concepts that are still weak right now.",
        "learn_new": "Opens the next concept area at a suitable difficulty level.",
    }

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
        return max(6, min(30, int(round(0.7 * avg_session + chunk_count * 2.0))))

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

    @staticmethod
    def _resource_text(resource: Dict[str, Any]) -> str:
        metadata = resource.get("metadata") or {}
        concepts = metadata.get("primary_concepts") or metadata.get("covered_concepts") or []
        chunk_profile = metadata.get("chunk_profile") or {}
        return " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str(metadata.get("summary") or ""),
                " ".join(str(item) for item in concepts if item),
                " ".join(str(item) for item in chunk_profile.get("top_keywords", []) if item),
            ]
        ).lower()

    def _resource_matches_terms(self, resource: Dict[str, Any], terms: List[str]) -> bool:
        normalized_terms = [str(item).strip().lower() for item in terms if str(item).strip()]
        if not normalized_terms:
            return False
        text = self._resource_text(resource)
        return any(term in text for term in normalized_terms)

    def build_explanation(
        self,
        *,
        resource: Dict[str, Any],
        mode: str,
        learner_state: Dict[str, Any],
        goal: str,
        level: str,
        quality_score: float,
        expected_learning_gain: float,
        concept_gap_fit: float,
        difficulty_fit: float,
        lesson_context: Dict[str, Any] | None = None,
        chunk_match_score: float = 0.0,
        matched_chunk_terms: List[str] | None = None,
    ) -> Dict[str, Any]:
        estimated_time = self._estimated_time(resource, learner_state)
        primary_concepts = self._primary_concepts(resource, learner_state)
        reasons: List[str] = []
        why_selected: List[str] = []
        lesson_context = lesson_context or {}
        matched_chunk_terms = [str(item).strip() for item in (matched_chunk_terms or []) if str(item).strip()]
        lesson_terms = [
            str(lesson_context.get("topic") or "").lower(),
            *[str(item).lower() for item in lesson_context.get("keywords", []) if item],
            *[
                str(item).lower()
                for item in lesson_context.get("learning_objectives", [])
                if item
            ],
        ]
        lesson_title = str(lesson_context.get("title") or "").strip()
        focus_terms = [
            str(item).strip().lower()
            for item in learner_state.get("current_focus_concepts", [])
            if str(item).strip()
        ]
        lesson_match = self._resource_matches_terms(resource, lesson_terms)
        focus_match = self._resource_matches_terms(resource, focus_terms)
        fit_level = f"Best suited for {level} learners."

        if lesson_match and lesson_title:
            reasons.append(f"Matches your current lesson: {lesson_title}.")
            why_selected.append("lesson_context_match")
        elif mode == "continue_learning" and int(learner_state.get("unfinished_resources") or 0) > 0:
            reasons.append("Helps you continue a resource path that is still unfinished.")
            why_selected.append("unfinished_path_continuation")
        elif mode == "reinforce_weaknesses" and (focus_match or primary_concepts):
            reasons.append(
                f"Helps reinforce {', '.join(primary_concepts[:2])}, which are currently weak areas for you."
            )
            why_selected.append("weak_concept_reinforcement")
        elif mode == "learn_new" and primary_concepts:
            reasons.append(
                f"Prepares you for the next concept step around {', '.join(primary_concepts[:2])}."
            )
            why_selected.append("next_concept_progression")

        if focus_match and primary_concepts and mode != "reinforce_weaknesses":
            reasons.append(f"Stays focused on {', '.join(primary_concepts[:2])}, which you are working on now.")
            why_selected.append("focus_concept_alignment")

        if chunk_match_score >= 0.68 and matched_chunk_terms:
            reasons.append(
                f"Relevant sections inside this material directly cover {', '.join(matched_chunk_terms[:2])}."
            )
            why_selected.append("semantic_chunk_match")
        elif chunk_match_score >= 0.74:
            reasons.append("Relevant sections inside this material closely match what you are studying now.")
            why_selected.append("semantic_chunk_match")

        if difficulty_fit >= 0.72:
            reasons.append(f"Difficulty fits your current {level} level.")
            why_selected.append("level_fit")

        if expected_learning_gain >= 0.68:
            reasons.append("This resource is likely to improve mastery efficiently.")
            why_selected.append("expected_learning_gain")
        elif quality_score >= 0.72:
            reasons.append("Quality signals suggest the content is clear and reliable.")
            why_selected.append("resource_quality")

        if estimated_time <= 15:
            reasons.append("Estimated time fits a short study session.")
            why_selected.append("time_budget_fit")

        if not reasons and goal.strip():
            reasons.append(f"Aligned with your goal: {goal.strip()}.")
            why_selected.append("goal_alignment")

        if not reasons:
            reasons.append(self._MODE_TEMPLATES.get(mode, "Matches your current learning goal."))
            why_selected.append("default_mode_alignment")

        summary = reasons[0]
        if len(reasons) > 1:
            summary = f"{reasons[0]} {reasons[1]}"

        return {
            "reason": summary,
            "estimated_time": estimated_time,
            "primary_concepts": primary_concepts,
            "supports_concepts": primary_concepts[:3],
            "fit_level": fit_level,
            "why_selected": why_selected[:4],
        }


recommendation_explanation_service = RecommendationExplanationService()
