"""Deterministic template-based question generation from lesson chunks."""

from __future__ import annotations

import re
from typing import Any, Dict, List


class QuestionTemplateService:
    """Create lesson-scoped question candidates without LLM calls."""

    _STOP_WORDS = {
        "about",
        "after",
        "before",
        "between",
        "could",
        "from",
        "have",
        "into",
        "lesson",
        "source",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "using",
        "with",
    }
    _DISTRACTOR_FALLBACK = [
        "tuple",
        "set",
        "dictionary",
        "function",
        "loop",
        "string",
        "module",
        "class",
    ]
    _BLOOM_TEMPLATES = {
        "remember": {
            "multiple_choice": "Theo bai '{lesson_title}', thuat ngu nao xuat hien truc tiep trong doan trich?",
            "short_answer": "Neu lai thuat ngu chinh lien quan den '{focus}' trong bai '{lesson_title}'.",
            "true_false": "Theo bai '{lesson_title}', phat bieu sau dung hay sai: \"{statement}.\"",
        },
        "understand": {
            "multiple_choice": "Trong bai '{lesson_title}', lua chon nao mo ta dung nhat khai niem '{focus}' theo doan trich?",
            "short_answer": "Giai thich ngan gon y nghia cua '{focus}' trong bai '{lesson_title}'.",
            "true_false": "Theo noi dung bai '{lesson_title}', menh de sau dung hay sai: \"{statement}.\"",
        },
        "apply": {
            "multiple_choice": "Neu ap dung kien thuc trong bai '{lesson_title}', lua chon nao phu hop nhat voi '{focus}'?",
            "short_answer": "Dua vao bai '{lesson_title}', hay neu cach ap dung '{focus}' trong mot tinh huong don gian.",
            "true_false": "Trong ngu canh ap dung cua bai '{lesson_title}', phat bieu sau dung hay sai: \"{statement}.\"",
        },
        "analyze": {
            "multiple_choice": "Khi phan tich noi dung bai '{lesson_title}', yeu to nao lien quan nhat den '{focus}'?",
            "short_answer": "Phan tich ngan gon vai tro cua '{focus}' trong doan trich cua bai '{lesson_title}'.",
            "true_false": "Khi phan tich bai '{lesson_title}', menh de sau dung hay sai: \"{statement}.\"",
        },
    }

    @staticmethod
    def resolve_difficulty_from_progress(
        *,
        requested_difficulty: str,
        mastery: float | None,
        success_rate: float | None,
    ) -> str:
        def _bounded(value: float | None) -> float | None:
            if value is None:
                return None
            try:
                return max(0.0, min(1.0, float(value)))
            except Exception:
                return None

        mastery_value = _bounded(mastery)
        success_value = _bounded(success_rate)
        if mastery_value is None and success_value is None:
            return requested_difficulty

        score = 0.0
        weight = 0.0
        if mastery_value is not None:
            score += mastery_value * 0.6
            weight += 0.6
        if success_value is not None:
            score += success_value * 0.4
            weight += 0.4
        blended = score / max(weight, 1e-6)
        if blended >= 0.75:
            return "advanced"
        if blended >= 0.45:
            return "intermediate"
        return "beginner"

    def build_candidates(
        self,
        *,
        lesson_title: str,
        chunks: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        max_per_chunk: int = 1,
    ) -> List[Dict[str, Any]]:
        if target_count <= 0:
            return []

        selected_types = question_types or ["multiple_choice"]
        selected_bloom_levels = [
            level for level in (bloom_levels or ["remember", "understand"]) if level in self._BLOOM_TEMPLATES
        ] or ["remember", "understand"]
        candidates: List[Dict[str, Any]] = []
        signatures: set[str] = set()
        chunk_usage: Dict[str, int] = {}

        for index, chunk in enumerate(chunks):
            if len(candidates) >= target_count:
                break

            chunk_id = str(chunk.get("_id") or "").strip()
            content = str(chunk.get("content") or "").strip()
            if not chunk_id or not content:
                continue
            if chunk_usage.get(chunk_id, 0) >= max(1, max_per_chunk):
                continue

            excerpt = self._select_excerpt(content)
            focus = self._extract_focus_term(excerpt)
            if not excerpt or not focus:
                continue

            question_type = selected_types[index % len(selected_types)]
            bloom_level = selected_bloom_levels[index % len(selected_bloom_levels)]
            candidate = self._build_candidate(
                lesson_title=lesson_title,
                question_type=question_type,
                difficulty=difficulty,
                bloom_level=bloom_level,
                chunk_id=chunk_id,
                excerpt=excerpt,
                content=content,
                focus=focus,
            )
            signature = self._signature(candidate)
            if signature in signatures:
                continue
            signatures.add(signature)
            chunk_usage[chunk_id] = chunk_usage.get(chunk_id, 0) + 1
            candidates.append(candidate)

        return candidates

    @staticmethod
    def _select_excerpt(content: str) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            return ""
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", normalized)
            if item.strip()
        ]
        if sentences:
            return sentences[0][:260]
        return normalized[:260]

    def _extract_focus_term(self, excerpt: str) -> str:
        terms = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", excerpt.lower())
        for term in terms:
            if term in self._STOP_WORDS:
                continue
            return term
        return ""

    def _build_candidate(
        self,
        *,
        lesson_title: str,
        question_type: str,
        difficulty: str,
        bloom_level: str,
        chunk_id: str,
        excerpt: str,
        content: str,
        focus: str,
    ) -> Dict[str, Any]:
        bloom = bloom_level if bloom_level in self._BLOOM_TEMPLATES else "understand"
        template = self._BLOOM_TEMPLATES[bloom]
        if question_type == "short_answer":
            return {
                "question_type": "short_answer",
                "question": template["short_answer"].format(
                    lesson_title=lesson_title, focus=focus
                ),
                "correct_answer": focus,
                "distractors": [],
                "explanation": f"Doan trich neu truc tiep thuat ngu '{focus}'.",
                "difficulty": difficulty,
                "bloom_level": bloom,
                "chunk_ids": [chunk_id],
                "metadata": {
                    "source_excerpt": excerpt,
                    "question_focus": focus,
                    "generation_source": "template",
                    "reasoning_note": "Generated from deterministic template.",
                    "generation_mode": "template",
                },
            }

        if question_type == "true_false":
            statement = excerpt.rstrip(".")
            return {
                "question_type": "true_false",
                "question": template["true_false"].format(
                    lesson_title=lesson_title,
                    statement=statement,
                ),
                "correct_answer": "True",
                "distractors": ["False"],
                "explanation": "Phat bieu duoc lay truc tiep tu doan trich trong bai hoc.",
                "difficulty": difficulty,
                "bloom_level": bloom,
                "chunk_ids": [chunk_id],
                "metadata": {
                    "source_excerpt": excerpt,
                    "question_focus": focus,
                    "generation_source": "template",
                    "reasoning_note": "Generated from deterministic template.",
                    "generation_mode": "template",
                },
            }

        distractors = self._build_distractors(answer=focus, excerpt=excerpt, content=content)
        return {
            "question_type": "multiple_choice",
            "question": template["multiple_choice"].format(
                lesson_title=lesson_title,
                focus=focus,
            ),
            "correct_answer": focus,
            "distractors": distractors,
            "explanation": f"Thuat ngu '{focus}' xuat hien truc tiep trong doan trich nguon.",
            "difficulty": difficulty,
            "bloom_level": bloom,
            "chunk_ids": [chunk_id],
            "metadata": {
                "source_excerpt": excerpt,
                "question_focus": focus,
                "generation_source": "template",
                "reasoning_note": "Generated from deterministic template.",
                "generation_mode": "template",
            },
        }

    def _build_distractors(self, *, answer: str, excerpt: str, content: str) -> List[str]:
        answer_key = answer.strip().lower()
        tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", f"{excerpt} {content}".lower())
        candidates: List[str] = []
        seen: set[str] = {answer_key}
        for token in tokens:
            if token in self._STOP_WORDS or token in seen:
                continue
            seen.add(token)
            candidates.append(token)
            if len(candidates) >= 6:
                break
        for fallback in self._DISTRACTOR_FALLBACK:
            if fallback not in seen:
                candidates.append(fallback)
                seen.add(fallback)
            if len(candidates) >= 3:
                break
        while len(candidates) < 3:
            candidates.append(f"term_{len(candidates) + 1}")
        return candidates[:3]

    @staticmethod
    def _signature(candidate: Dict[str, Any]) -> str:
        question = " ".join(str(candidate.get("question") or "").lower().split())
        answer = " ".join(str(candidate.get("correct_answer") or "").lower().split())
        return f"{question}|{answer}"


question_template_service = QuestionTemplateService()