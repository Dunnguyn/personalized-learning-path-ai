"""Retry strategy selection for concept-level adaptive tutoring."""

from __future__ import annotations

from typing import Dict


class RetryStrategyService:
    """Choose and apply retry strategy based on retry count history."""

    def select_retry_strategy(self, retry_count: int) -> str:
        if retry_count <= 1:
            return "same_question"
        if retry_count == 2:
            return "paraphrase_question"
        if retry_count == 3:
            return "simplify_question"
        return "explain_then_question"

    @staticmethod
    def apply_generation_hints(strategy: str, *, difficulty: str) -> Dict[str, object]:
        strategy = str(strategy or "same_question")
        adjusted_difficulty = difficulty
        if strategy == "simplify_question":
            adjusted_difficulty = "beginner"

        return {
            "retry_strategy": strategy,
            "reuse_previous_question": strategy == "same_question",
            "paraphrase_question": strategy == "paraphrase_question",
            "add_explanation_before_question": strategy == "explain_then_question",
            "recommended_difficulty": adjusted_difficulty,
        }


retry_strategy_service = RetryStrategyService()
