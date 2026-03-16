from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Sequence

from backend.app.services.question_generation.lesson_content import LessonChunk


@dataclass(frozen=True)
class LessonQuestionPromptInput:
    lesson_id: str
    lesson_title: str
    concepts: List[str]
    target_count: int
    difficulty_hint: str = "mixed"


class LessonQuestionPromptBuilder:
    """
    Build a grounded prompt for LLM question generation.
    """

    def build(self, prompt_input: LessonQuestionPromptInput, chunks: Sequence[LessonChunk]) -> str:
        chunk_payload = [
            {
                "chunk_id": chunk.chunk_id,
                "source_title": chunk.source_title,
                "source_type": chunk.source_type,
                "text": chunk.text,
            }
            for chunk in chunks
        ]

        concepts = ", ".join(prompt_input.concepts) if prompt_input.concepts else prompt_input.lesson_title

        return f"""
You are an educational assessment generator.

Your task:
- Generate exactly {prompt_input.target_count} high-quality quiz questions for one lesson.
- Every question must be grounded in the provided lesson chunks.
- Do not use outside knowledge.
- Do not invent facts that are not explicitly stated or strongly implied by the chunks.
- Avoid generic questions such as broad definitions that are not tied to the lesson text.
- Keep answers concise and correct.
- Add a short explanation to support learning.
- Cover the lesson concepts when possible: {concepts}
- Use a mix of difficulties aligned with the lesson.
- When creating the canonical correct answer for grading:
  - Do not explain at length.
  - Do not write like a lesson or lecture.
  - Do not use information outside the lesson chunks.
  - The answer must directly answer the question.
  - If the chunks do not contain enough evidence, return "INSUFFICIENT_CONTEXT" as the answer.

Required output:
- Return valid JSON only.
- Return one JSON array.
- Each item must follow this schema:
  {{
    "question": "string",
    "options": [
      {{"key": "A", "text": "string"}},
      {{"key": "B", "text": "string"}},
      {{"key": "C", "text": "string"}},
      {{"key": "D", "text": "string"}}
    ],
    "correct_option": "A",
    "answer": "string",
    "explanation": "string",
    "keywords": ["string", "string", "string"],
    "difficulty": 1,
    "concept": "string",
    "source_excerpt": "string",
    "source_chunk_id": "string"
  }}

Validation rules:
- `source_excerpt` must be copied from one provided chunk.
- `source_chunk_id` must match the chunk that supports the question.
- `options` must contain exactly 4 answer choices.
- `correct_option` must be one of A, B, C, D and must match the correct choice.
- `answer` must match the text of the correct option.
- `answer` must be no more than 2 sentences.
- `explanation` must be no more than 3 sentences.
- `keywords` must contain 3 to 5 important keywords.
- `difficulty` must be an integer from 1 to 5.
- `question`, `answer`, `explanation`, `keywords`, `concept`, `source_excerpt`, and `source_chunk_id` are required.
- If a question cannot be supported by the chunks, do not generate it.
- Generate MCQ questions directly with one clearly correct answer and 3 plausible distractors.
- `source_excerpt` must be exactly one short excerpt copied from context.

Lesson metadata:
{json.dumps({
    "lesson_id": prompt_input.lesson_id,
    "lesson_title": prompt_input.lesson_title,
    "concepts": prompt_input.concepts,
    "target_count": prompt_input.target_count,
    "difficulty_hint": prompt_input.difficulty_hint,
}, ensure_ascii=True, indent=2)}

Lesson chunks:
{json.dumps(chunk_payload, ensure_ascii=True, indent=2)}
""".strip()


def build_lesson_question_prompt(prompt_input: LessonQuestionPromptInput, chunks: Sequence[LessonChunk]) -> str:
    return LessonQuestionPromptBuilder().build(prompt_input=prompt_input, chunks=chunks)
