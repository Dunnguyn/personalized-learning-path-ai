"""Question-generation deduplication helpers."""

from __future__ import annotations

from typing import Any, Dict, Sequence


def question_signature(service: Any, question: Any) -> str:
    return question_signature_from_parts(
        service,
        question_text=getattr(question, "question", ""),
        correct_answer=getattr(question, "correct_answer", ""),
    )


def question_signature_from_parts(
    service: Any,
    *,
    question_text: Any,
    correct_answer: Any,
) -> str:
    stem = service._normalize_text(question_text)
    answer = service._normalize_text(correct_answer)
    if not stem:
        return ""
    return f"{stem}::{answer}"


def collect_excluded_question_signatures(
    service: Any,
    *,
    existing_questions: Sequence[Dict[str, Any]] | None,
    generation_metadata: Dict[str, Any] | None,
) -> set[str]:
    signatures: set[str] = set()
    for item in existing_questions or []:
        signature = question_signature_from_parts(
            service,
            question_text=item.get("question"),
            correct_answer=item.get("correct_answer"),
        )
        if signature:
            signatures.add(signature)

    metadata = generation_metadata if isinstance(generation_metadata, dict) else {}
    previous_questions = metadata.get("previous_questions")
    if not isinstance(previous_questions, list):
        previous_questions = (
            metadata.get("generation_strategy", {}).get("previous_questions")
            if isinstance(metadata.get("generation_strategy"), dict)
            else []
        )

    for item in previous_questions or []:
        if not isinstance(item, dict):
            continue
        signature = question_signature_from_parts(
            service,
            question_text=item.get("question"),
            correct_answer=item.get("correct_answer"),
        )
        if signature:
            signatures.add(signature)

    return signatures
