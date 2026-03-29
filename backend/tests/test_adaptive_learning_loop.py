from __future__ import annotations

from backend.app.services.adaptive_decision_service import AdaptiveDecisionService
from backend.app.services.adaptive_question_selector import AdaptiveQuestionSelector
from backend.app.services.progress_evaluation_service import ProgressEvaluationService
from backend.app.services.retry_strategy_service import RetryStrategyService


def _questions(accuracy: float, concept: str = "loops", chunk: str = "chunk_1"):
    total = 10
    correct = int(total * accuracy)
    items = []
    for index in range(total):
        is_correct = index < correct
        items.append(
            {
                "question_id": f"q{index}",
                "chunk_id": chunk if index < 7 else "chunk_2",
                "concept_id": concept if index < 7 else "variables",
                "difficulty": "beginner",
                "bloom_level": "remember",
                "is_correct": is_correct,
                "selected_answer": "A",
                "correct_answer": "A" if is_correct else "B",
                "confidence_score": 0.8 if is_correct else 0.2,
            }
        )
    return items


def test_case_1_user_fails_3_times_force_remedial_mode():
    evaluation = ProgressEvaluationService().evaluate_attempt(
        _questions(0.3, concept="loops"),
        recent_attempts=[
            {"accuracy": 0.4},
            {"accuracy": 0.45},
        ],
    )
    decision = AdaptiveDecisionService().decide(
        evaluation=evaluation,
        lesson_mastery=0.35,
        chunk_mastery={"chunk_1": 0.2},
        concept_mastery={"loops": 0.3},
        retry_strategy="simplify_question",
    )
    assert decision.next_action == "force_remedial_mode"


def test_case_2_user_success_3_times_increase_difficulty_fast():
    evaluation = ProgressEvaluationService().evaluate_attempt(
        _questions(0.9, concept="variables"),
        recent_attempts=[
            {"accuracy": 0.85},
            {"accuracy": 0.82},
        ],
    )
    decision = AdaptiveDecisionService().decide(
        evaluation=evaluation,
        lesson_mastery=0.8,
        chunk_mastery={"chunk_1": 0.8},
        concept_mastery={"variables": 0.85},
        retry_strategy="same_question",
    )
    assert decision.next_action == "increase_difficulty_fast"
    assert decision.recommended_difficulty == "advanced"


def test_case_3_low_concept_mastery_targets_weakest_concept():
    evaluation = ProgressEvaluationService().evaluate_attempt(
        _questions(0.7, concept="loops"),
    )
    decision = AdaptiveDecisionService().decide(
        evaluation=evaluation,
        lesson_mastery=0.62,
        chunk_mastery={"chunk_1": 0.61},
        concept_mastery={"loops": 0.2, "variables": 0.8},
        retry_strategy="paraphrase_question",
    )
    assert decision.next_action == "practice_specific_concept"
    assert decision.target_concepts[0] == "loops"


def test_case_4_retry_count_2_selects_paraphrase_question():
    service = RetryStrategyService()
    strategy = service.select_retry_strategy(2)
    assert strategy == "paraphrase_question"

    selector = AdaptiveQuestionSelector()
    config = selector.select_next(
        lesson_id="lesson_1",
        learning_state={"chunk_mastery": {"chunk_1": 0.4}, "concept_mastery": {"loops": 0.3}},
        attempt_evaluation={"accuracy": 0.4},
        decision={
            "recommended_difficulty": "intermediate",
            "recommended_bloom_levels": ["understand"],
            "target_chunk_ids": ["chunk_1"],
            "target_concepts": ["loops"],
            "allow_llm": False,
            "prefer_template": True,
            "retry_strategy": strategy,
            "retry_count": 2,
        },
        target_count=6,
    )
    assert config["generation_strategy"]["paraphrase_question"] is True


def test_case_5_retry_count_3_selects_simplify_question():
    service = RetryStrategyService()
    strategy = service.select_retry_strategy(3)
    assert strategy == "simplify_question"

    selector = AdaptiveQuestionSelector()
    config = selector.select_next(
        lesson_id="lesson_2",
        learning_state={"chunk_mastery": {"chunk_1": 0.2}, "concept_mastery": {"loops": 0.25}},
        attempt_evaluation={"accuracy": 0.35},
        decision={
            "recommended_difficulty": "advanced",
            "recommended_bloom_levels": ["apply"],
            "target_chunk_ids": ["chunk_1"],
            "target_concepts": ["loops"],
            "allow_llm": False,
            "prefer_template": True,
            "retry_strategy": strategy,
            "retry_count": 3,
        },
        target_count=6,
    )
    assert config["recommended_difficulty"] == "beginner"


def test_case_6_retry_count_gt_3_selects_explain_then_question():
    service = RetryStrategyService()
    strategy = service.select_retry_strategy(4)
    assert strategy == "explain_then_question"

    selector = AdaptiveQuestionSelector()
    config = selector.select_next(
        lesson_id="lesson_3",
        learning_state={
            "chunk_mastery": {"chunk_a": 0.9, "chunk_b": 0.2, "chunk_c": 0.4},
            "concept_mastery": {"loops": 0.3},
        },
        attempt_evaluation={"accuracy": 0.5},
        decision={
            "recommended_difficulty": "beginner",
            "recommended_bloom_levels": ["remember", "understand"],
            "target_chunk_ids": [],
            "target_concepts": ["loops"],
            "allow_llm": False,
            "prefer_template": True,
            "retry_strategy": strategy,
            "retry_count": 4,
        },
        target_count=6,
    )
    assert config["generation_strategy"]["add_explanation_before_question"] is True
    assert isinstance(config.get("explanation"), str)
