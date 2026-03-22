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

    def build(self, *, context: LessonQuestionPromptContext, chunks: Sequence[Dict[str, str]]) -> str:
        payload = [
            {
                "chunk_id": chunk["chunk_id"],
                "resource_id": chunk["resource_id"],
                "chunk_index": chunk["chunk_index"],
                "content": chunk["content"],
            }
            for chunk in chunks
        ]

        return f"""
You are a lesson-scoped assessment generator.

Boundary rules:
- Use ONLY the provided lesson chunks.
- Do NOT retrieve or assume outside knowledge.
- Do NOT use any chunk that is not in the provided list.
- If the provided chunks are insufficient, return status "insufficient_context".
- Question generation is limited to this lesson scope only.

Lesson context:
{json.dumps({
    "subject_title": context.subject_title,
    "chapter_title": context.chapter_title,
    "lesson_id": context.lesson_id,
    "lesson_title": context.lesson_title,
    "lesson_summary": context.lesson_summary,
    "target_count": context.target_count,
    "question_types": context.question_types,
    "difficulty": context.difficulty,
    "bloom_levels": context.bloom_levels,
}, ensure_ascii=True, indent=2)}

Allowed chunk scope:
{json.dumps(payload, ensure_ascii=True, indent=2)}

Output rules:
- Return valid JSON only.
- Return a single object with this schema:
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
      "bloom_level": "remember" | "understand" | "apply" | "analyze",
      "chunk_ids": ["chunk_id"],
      "metadata": {{
        "source_excerpt": "string",
        "reasoning_note": "short string"
      }}
    }}
  ]
}}

Validation requirements:
- Every question must cite only chunk_ids from the provided chunk list.
- `source_excerpt` must be copied from the cited chunk text.
- For `multiple_choice`, provide exactly 3 distractors and none may equal `correct_answer`.
- For `true_false`, set `correct_answer` to exactly "True" or "False".
- For `short_answer`, `distractors` must be an empty array.
- Do not generate more than {context.target_count} questions.
- If the chunks are not enough to support faithful questions, return:
  {{"status":"insufficient_context","message":"...","questions":[]}}
""".strip()
