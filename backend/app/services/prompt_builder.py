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
                "chunk_id": chunk["chunk_id"],
                "resource_id": chunk["resource_id"],
                "chunk_index": chunk["chunk_index"],
                "page_number": chunk.get("page_number"),
                "resource_title": chunk.get("resource_title"),
                "resource_source": chunk.get("resource_source"),
                "score": chunk.get("score"),
                "instruction_role": chunk.get("instruction_role"),
                "covered_concepts": chunk.get("covered_concepts"),
                "questionability_score": chunk.get("questionability_score"),
                "estimated_read_time": chunk.get("estimated_read_time"),
                "content": chunk["content"],
            }
            for chunk in chunks
        ]

        return f"""
You are an expert AI tutor specialized in generating high-quality educational questions.

Your task is to generate lesson-scoped questions that are strictly grounded in the provided learning chunks.

Boundary rules:
- Use ONLY the provided lesson chunks.
- Do NOT retrieve or assume outside knowledge.
- Do NOT use any chunk that is not in the provided list.
- If the provided chunks are insufficient, return status "insufficient_context".
- Question generation is limited to this lesson scope only.
- Write learner-facing questions and explanations in Vietnamese.
- Preserve technical terms from the source material when needed.
- Prefer covering different chunks before reusing the same chunk repeatedly.
- Prefer the most relevant chunks first, using `score` when available.
- Avoid near-duplicate questions, repeated stems, or repeated correct answers unless the lesson scope truly requires it.
- Treat each generated question as ONE grounded question built from ONE primary chunk.
- Prefer chunks with higher `questionability_score` when multiple chunks are suitable.
- Use `covered_concepts` as the target concept when available.
- Use `instruction_role` to shape the question style conservatively:
  - introduction/explanation -> meaning, purpose, interpretation
  - worked_example -> application, behavior, step-by-step reasoning
  - summary -> recap, compare, or direct understanding check
- Never mention facts, syntax, outputs, or examples not supported by the cited chunk.
- If a chunk does not support a complex question, generate a simpler faithful question from the same chunk instead of hallucinating.

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
      "bloom_level": "remember" | "understand" | "apply" | "analyze" | "evaluate" | "create",
      "chunk_ids": ["chunk_id"],
      "metadata": {{
        "source_excerpt": "string",
        "reasoning_note": "short string",
        "question_focus": "string",
        "source_page_number": 1,
        "source_resource_title": "string",
        "source_resource_id": "string",
        "source_chunk_index": 0,
        "source_score": 0.0
      }}
    }}
  ]
}}

Validation requirements:
- Every question must be grounded in exactly one primary chunk. Set `chunk_ids` to a single-item array unless a second chunk is absolutely necessary.
- Every question must cite only chunk_ids from the provided chunk list.
- `source_excerpt` must be copied from the cited chunk text.
- `question_focus` should name the core concept/skill being tested and should align with the chunk's `covered_concepts` when available.
- If page_number/resource_title exists for the cited chunk, copy it into metadata.
- Match the requested lesson difficulty: {context.difficulty}.
- Match the requested Bloom levels as closely as possible: {json.dumps(context.bloom_levels, ensure_ascii=True)}.
- For `multiple_choice`, ask about meaning, behavior, interpretation, or chunk-grounded application.
- For `multiple_choice`, provide exactly 3 plausible distractors and none may equal `correct_answer`.
- For `multiple_choice`, `correct_answer` must be a single exact answer string and must not be duplicated in distractors.
- For `multiple_choice`, explanation must say why the correct answer is right and briefly why the distractors are wrong.
- For `true_false`, set `correct_answer` to exactly "True" or "False".
- For `true_false`, explanation must clearly justify the statement using the cited chunk only.
- For `short_answer`, `distractors` must be an empty array.
- For `short_answer`, keep the answer concise and directly supported by the chunk.
- Use `bloom_level` from the requested list whenever possible.
- Do not copy long sentences from the chunk as the full question.
- Do not generate more than {context.target_count} questions.
- If the chunks are not enough to support faithful questions, return:
  {{"status":"insufficient_context","message":"...","questions":[]}}
""".strip()
