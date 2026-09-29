"""Select next adaptive question configuration."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.app.services.retry_strategy_service import retry_strategy_service


class AdaptiveQuestionSelector:
    """Build next adaptive quiz selection config from state and decision."""

    def select_next(
        self,
        *,
        lesson_id: str,
        learning_state: Dict[str, Any],
        attempt_evaluation: Dict[str, Any],
        decision: Dict[str, Any],
        target_count: Optional[int],
        latest_attempt: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        weak_chunks = list(decision.get("target_chunk_ids") or [])
        if not weak_chunks:
            weak_chunks = [
                chunk_id
                for chunk_id, score in sorted(
                    (learning_state.get("chunk_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ]

        weak_concepts = list(decision.get("target_concepts") or [])
        if not weak_concepts:
            weak_concepts = [
                concept_id
                for concept_id, score in sorted(
                    (learning_state.get("concept_mastery") or {}).items(),
                    key=lambda pair: float(pair[1]),
                )[:3]
            ]

        retry_strategy = str(decision.get("retry_strategy") or "paraphrase_question")
        retry_hints = retry_strategy_service.apply_generation_hints(
            retry_strategy,
            difficulty=str(decision.get("recommended_difficulty") or "beginner"),
        )
        previous_question_ids = [
            str(item.get("question_id"))
            for item in (latest_attempt or {}).get("questions", [])
            if str(item.get("question_id") or "").strip()
        ]
        previous_questions = [
            {
                "question_id": str(item.get("question_id") or "").strip(),
                "question": str(item.get("question") or "").strip(),
                "correct_answer": str(item.get("correct_answer") or "").strip(),
            }
            for item in (latest_attempt or {}).get("questions", [])
            if str(item.get("question") or "").strip()
        ]

        return {
            "lesson_id": lesson_id,
            "target_count": max(1, int(target_count or 1)),
            "recommended_difficulty": retry_hints.get(
                "recommended_difficulty",
                decision.get("recommended_difficulty", "beginner"),
            ),
            "recommended_bloom_levels": list(
                decision.get("recommended_bloom_levels")
                or ["remember", "understand"]
            ),
            "target_chunk_ids": weak_chunks,
            "target_concepts": weak_concepts,
            "retry_strategy": retry_strategy,
            "retry_count": int(decision.get("retry_count") or 1),
            "question_types": list(
                decision.get("question_types") or ["multiple_choice", "short_answer"]
            ),
            "policy_version": decision.get("policy_version"),
            "policy_bucket": decision.get("policy_bucket"),
            "why_this_quiz": decision.get("why_this_quiz"),
            "explanation": (
                "Xem lại giai thich ngan gon truoc khi lam cau hoi."
                if bool(retry_hints.get("add_explanation_before_question"))
                else None
            ),
            "previous_question_ids": previous_question_ids,
            "generation_strategy": {
                "template_first": True,
                "allow_llm": bool(decision.get("allow_llm", False)),
                "prefer_template": bool(decision.get("prefer_template", True)),
                "retry_strategy": retry_strategy,
                "paraphrase_question": bool(retry_hints.get("paraphrase_question")),
                "add_explanation_before_question": bool(
                    retry_hints.get("add_explanation_before_question")
                ),
            },
            "metadata": {
                "previous_question_ids": previous_question_ids,
                "previous_questions": previous_questions,
            },
            "attempt_accuracy": float(attempt_evaluation.get("accuracy", 0.0) or 0.0),
        }


adaptive_question_selector = AdaptiveQuestionSelector()
