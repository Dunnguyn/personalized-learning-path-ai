"""Prompt builder for lesson-scoped question generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Sequence


@dataclass(frozen=True)
class LessonQuestionPromptContext:
    subject_title: str
    chapter_title: str
    lesson_id: str
    lesson_title: str
    lesson_summary: str
    target_count: int
    question_types: List[str]
    difficulty: str
    bloom_levels: List[str]


class LessonScopedPromptBuilder:
    """Build a strict prompt that only allows generation from recommended chunks."""

    def build(
        self, *, context: LessonQuestionPromptContext, chunks: Sequence[Dict[str, str]]
    ) -> str:
        payload = [
            {
                "rank": index + 1,
                "chunk_id": chunk["chunk_id"],
                "resource_id": chunk["resource_id"],
                "chunk_index": chunk["chunk_index"],
                "page_number": chunk.get("page_number"),
                "resource_title": chunk.get("resource_title"),
                "instruction_role": chunk.get("instruction_role"),
                "covered_concepts": chunk.get("covered_concepts"),
                "content": chunk["content"],
            }
            for index, chunk in enumerate(chunks)
        ]
        lesson_context = {
            "subject_title": context.subject_title,
            "chapter_title": context.chapter_title,
            "lesson_id": context.lesson_id,
            "lesson_title": context.lesson_title,
            "lesson_summary": context.lesson_summary,
            "target_count": context.target_count,
            "question_types": context.question_types,
            "difficulty": context.difficulty,
            "bloom_levels": context.bloom_levels,
        }

        return f"""
Generate lesson-scoped questions grounded ONLY in the provided chunks.

Rules:
- Use only the given chunks. No outside knowledge.
- If chunks are insufficient, return `{{"status":"insufficient_context","message":"...","questions":[]}}`.
- Write learner-facing text in Vietnamese.
- Generate at most {context.target_count} questions.
- Each question must use exactly one primary chunk in `chunk_ids`.
- Prefer earlier chunks because the list is already ranked by relevance.
- Prefer different chunks before reusing one.
- Use `covered_concepts` when available for `metadata.question_focus`.
- Do not copy a full sentence from the chunk and turn it into a trivial recall question.
- Do not ask a question whose answer is explicitly revealed inside the question stem.
- If the chunk contains a worked example or behavior, prefer `apply` or `analyze` over shallow recall.
- If the chunk is mostly definition or explanation, prefer `understand` before `remember`.
- Each question should test one concrete concept or decision, not a vague overview.
- Use `instruction_role` conservatively:
  introduction/explanation -> meaning or interpretation
  worked_example -> application or behavior
  summary -> recap or comparison

Lesson context:
{json.dumps(lesson_context, ensure_ascii=True, separators=(",", ":"))}

Allowed chunk scope:
{json.dumps(payload, ensure_ascii=True, separators=(",", ":"))}

Return valid JSON only with this schema:
{{
  "status": "ok" | "insufficient_context",
  "message": "string",
  "questions": [
    {{
      "question_type": "multiple_choice" | "short_answer" | "true_false",
      "question": "string",
      "correct_answer": "string",
      "distractors": ["string", "string", "string"],
      "explanation": "string",
      "difficulty": "beginner" | "intermediate" | "advanced",
      "bloom_level": "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create",
      "chunk_ids": ["chunk_id"],
      "metadata": {{
        "source_excerpt": "string",
        "question_focus": "string",
        "reasoning_pattern": "string",
        "distractor_rationale": ["string", "string", "string"],
        "evidence_terms": ["string"]
      }}
    }}
  ]
}}

Constraints:
- `chunk_ids` must contain exactly one allowed chunk_id.
- `source_excerpt` must be copied from that chunk.
- `question_focus` must be grounded in that chunk.
- Match difficulty `{context.difficulty}` and prefer bloom levels {json.dumps(context.bloom_levels, ensure_ascii=True, separators=(",", ":"))}.
- For `multiple_choice`, provide exactly 3 distinct distractors.
- For `multiple_choice`, distractors must be plausible, same semantic family as the correct answer, and not obviously absurd.
- Avoid options like "all of the above", "none of the above", or distractors that differ only by formatting.
- For `true_false`, `correct_answer` must be exactly `"True"` or `"False"`.
- For `short_answer`, `distractors` must be `[]`.
- `explanation` must briefly justify the answer using the chunk, not generic theory.
- `reasoning_pattern` should be one of `definition`, `classification`, `cause_effect`, `compare_contrast`, `worked_example`, `decision_rule`, `error_detection`, `workflow_step`.
- `distractor_rationale` should be `[]` for non-multiple_choice questions.
""".strip()
