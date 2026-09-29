"""Deterministic template-based question generation from lesson chunks."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
import re
import unicodedata
from typing import Any, Dict, List

from backend.app.services.question_nlp_service import question_nlp_service


class QuestionTemplateService:
    """Create lesson-scoped question candidates without LLM calls."""

    _CLAIM_CACHE_MAX_ENTRIES = 512
    _claim_cache: OrderedDict[str, Dict[str, Any] | None] = OrderedDict()
    _claim_cache_hits = 0
    _claim_cache_misses = 0
    _claim_cache_stores = 0

    def __init__(self) -> None:
        self.question_nlp_service = question_nlp_service

    _STOP_WORDS = {
        "about",
        "after",
        "again",
        "already",
        "another",
        "any",
        "because",
        "before",
        "between",
        "both",
        "challenge",
        "chapter",
        "could",
        "each",
        "example",
        "examples",
        "from",
        "have",
        "into",
        "just",
        "know",
        "lesson",
        "more",
        "most",
        "necessarily",
        "same",
        "source",
        "that",
        "their",
        "there",
        "these",
        "this",
        "those",
        "through",
        "understand",
        "using",
        "when",
        "where",
        "which",
        "with",
    }
    _NOISY_TERMS = {
        "affiliation",
        "bio",
        "category",
        "conference",
        "github",
        "name",
        "record",
        "records",
        "serial",
        "twitter",
        "venue",
        "venues",
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
        "classes",
    ]
    _BLOOM_TEMPLATES = {
        "remember": {
            "multiple_choice": "Theo bai '{lesson_title}', khai niem nao duoc neu truc tiep trong doan trich?",
            "short_answer": "Neu lai khai niem chinh lien quan den '{focus}' trong bai '{lesson_title}'.",
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
        lesson_summary: str = "",
        lesson_keywords: List[str] | None = None,
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
            level
            for level in (bloom_levels or ["remember", "understand"])
            if level in self._BLOOM_TEMPLATES
        ] or ["remember", "understand"]
        summary_keywords = self._prepare_lesson_keywords(
            lesson_summary=lesson_summary,
            lesson_keywords=lesson_keywords,
        )
        claim_units = self._build_claim_units(
            chunks,
            lesson_keywords=summary_keywords,
        )
        candidates: List[Dict[str, Any]] = []
        signatures: set[str] = set()
        chunk_usage: Dict[str, int] = {}
        focus_usage: Dict[str, int] = {}

        for unique_focus_only in (True, False):
            for claim in claim_units:
                if len(candidates) >= target_count:
                    break

                chunk_id = str(claim["chunk_id"])
                if chunk_usage.get(chunk_id, 0) >= max(1, max_per_chunk):
                    continue

                focus_key = self._normalize_text(str(claim.get("focus") or ""))
                if unique_focus_only and focus_key and focus_usage.get(focus_key, 0) >= 1:
                    continue

                candidate_index = len(candidates)
                question_type = selected_types[candidate_index % len(selected_types)]
                bloom_level = selected_bloom_levels[candidate_index % len(selected_bloom_levels)]
                candidate = self._build_candidate(
                    lesson_title=lesson_title,
                    lesson_summary=lesson_summary,
                    lesson_keywords=summary_keywords,
                    question_type=question_type,
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    chunk_id=chunk_id,
                    claim=claim,
                    all_claims=claim_units,
                    index=candidate_index,
                )
                if not candidate:
                    continue
                signature = self._signature(candidate)
                if signature in signatures:
                    continue
                signatures.add(signature)
                chunk_usage[chunk_id] = chunk_usage.get(chunk_id, 0) + 1
                if focus_key:
                    focus_usage[focus_key] = focus_usage.get(focus_key, 0) + 1
                candidates.append(candidate)
            if len(candidates) >= target_count:
                break

        return candidates

    def _build_claim_units(
        self,
        chunks: List[Dict[str, Any]],
        *,
        lesson_keywords: List[str] | None = None,
    ) -> List[Dict[str, Any]]:
        claim_units: List[Dict[str, Any]] = []
        for chunk in chunks:
            claim = self._get_or_build_claim_unit(chunk)
            if not claim:
                continue
            claim_units.append(claim)
        if lesson_keywords:
            claim_units.sort(
                key=lambda claim: self._claim_keyword_score(
                    claim,
                    lesson_keywords=lesson_keywords,
                ),
                reverse=True,
            )
        return claim_units

    def _prepare_lesson_keywords(
        self,
        *,
        lesson_summary: str,
        lesson_keywords: List[str] | None,
    ) -> List[str]:
        prepared: List[str] = []
        seen: set[str] = set()
        for value in lesson_keywords or []:
            normalized = self._normalize_text(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                prepared.append(str(value).strip())
        if lesson_summary.strip():
            for phrase in self.question_nlp_service.extract_keyphrases(
                lesson_summary,
                top_k=8,
            ):
                normalized = self._normalize_text(phrase)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    prepared.append(phrase)
        return prepared

    def _claim_keyword_score(
        self,
        claim: Dict[str, Any],
        *,
        lesson_keywords: List[str],
    ) -> float:
        if not lesson_keywords:
            return 0.0
        text = " ".join(
            str(item)
            for item in [
                claim.get("focus"),
                claim.get("statement"),
                claim.get("answer_text"),
                claim.get("excerpt"),
                *(claim.get("covered_concepts") or []),
            ]
            if str(item or "").strip()
        )
        semantic = self.question_nlp_service.semantic_similarity(text, lesson_keywords)
        lexical = self.question_nlp_service.lexical_relevance(text, lesson_keywords)
        overlap = self.question_nlp_service.keyword_overlap_terms(
            text,
            lesson_keywords,
            top_k=3,
        )
        return (semantic * 1.6) + (lexical * 1.1) + (0.2 * len(overlap))

    def _get_or_build_claim_unit(
        self, chunk: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        cache_key = self._claim_cache_key(chunk)
        if cache_key in self._claim_cache:
            type(self)._claim_cache_hits += 1
            cached = self._claim_cache.pop(cache_key)
            self._claim_cache[cache_key] = cached
            return self._clone_claim_unit(cached)

        type(self)._claim_cache_misses += 1
        claim = self._compute_claim_unit(chunk)
        self._store_claim_cache_entry(cache_key, claim)
        return self._clone_claim_unit(claim)

    def _compute_claim_unit(
        self, chunk: Dict[str, Any]
    ) -> Dict[str, Any] | None:
        chunk_id = str(chunk.get("_id") or "").strip()
        content = str(chunk.get("content") or "").strip()
        if not chunk_id or not content:
            return None
        instruction_role = self._extract_instruction_role(chunk)
        covered_concepts = self._extract_covered_concepts(chunk)
        excerpt = self._select_excerpt(content, preferred_terms=covered_concepts)
        focus = self._extract_focus_term(
            excerpt,
            content=content,
            preferred_terms=covered_concepts,
        )
        if not excerpt or not focus:
            return None
        statement = self._extract_claim_statement(excerpt, focus=focus)
        predicate = self._extract_claim_predicate(statement, focus=focus)
        raw_answer_text = predicate or self._fallback_claim_answer(
            statement,
            focus=focus,
        )
        answer_text = self._localize_claim_answer(
            statement=statement,
            focus=focus,
            raw_answer=raw_answer_text,
        )
        return {
            "chunk_id": chunk_id,
            "excerpt": excerpt,
            "content": content,
            "focus": focus,
            "statement": statement,
            "predicate": predicate,
            "answer_text": answer_text,
            "raw_answer_text": raw_answer_text,
            "instruction_role": instruction_role,
            "covered_concepts": covered_concepts,
        }

    def _claim_cache_key(self, chunk: Dict[str, Any]) -> str:
        chunk_id = str(chunk.get("_id") or "").strip()
        content = str(chunk.get("content") or "")
        instruction_role = self._extract_instruction_role(chunk)
        covered_concepts = sorted(
            self._normalize_text(item) for item in self._extract_covered_concepts(chunk)
        )
        content_hash = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()
        concept_key = ",".join(item for item in covered_concepts if item)
        return "|".join([chunk_id, instruction_role, concept_key, content_hash])

    def _store_claim_cache_entry(
        self, cache_key: str, claim: Dict[str, Any] | None
    ) -> None:
        type(self)._claim_cache_stores += 1
        self._claim_cache[cache_key] = self._clone_claim_unit(claim)
        while len(self._claim_cache) > self._CLAIM_CACHE_MAX_ENTRIES:
            self._claim_cache.popitem(last=False)

    @staticmethod
    def _clone_claim_unit(claim: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if claim is None:
            return None
        cloned = dict(claim)
        covered_concepts = claim.get("covered_concepts")
        if isinstance(covered_concepts, list):
            cloned["covered_concepts"] = list(covered_concepts)
        return cloned

    @classmethod
    def get_claim_cache_stats(cls) -> Dict[str, int | float]:
        hits = int(cls._claim_cache_hits)
        misses = int(cls._claim_cache_misses)
        total = hits + misses
        return {
            "entries": len(cls._claim_cache),
            "hits": hits,
            "misses": misses,
            "stores": int(cls._claim_cache_stores),
            "requests": total,
            "hit_rate": round(hits / max(total, 1), 4),
        }

    def _select_excerpt(self, content: str, *, preferred_terms: List[str] | None = None) -> str:
        normalized = re.sub(r"\s+", " ", content).strip()
        if not normalized:
            return ""
        preferred = [
            self._normalize_text(item)
            for item in (preferred_terms or [])
            if self._normalize_text(item)
        ]
        candidates = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+|\n+", normalized)
            if item.strip()
        ]
        ranked: List[tuple[float, str]] = []
        for candidate in candidates:
            score = self._score_excerpt(candidate, preferred_terms=preferred)
            if score <= 0:
                continue
            ranked.append((score, candidate[:260]))
        if ranked:
            ranked.sort(key=lambda item: item[0], reverse=True)
            return ranked[0][1]
        if self._looks_like_noisy_excerpt(normalized):
            return ""
        return normalized[:260]

    def _extract_focus_term(
        self,
        excerpt: str,
        *,
        content: str,
        preferred_terms: List[str] | None = None,
    ) -> str:
        for term in preferred_terms or []:
            if self._is_meaningful_focus_term(term):
                return term.strip()

        terms = re.findall(
            r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b",
            f"{excerpt} {content}".lower(),
        )
        scored_terms: List[tuple[float, int, str]] = []
        for index, term in enumerate(terms):
            if not self._is_meaningful_focus_term(term):
                continue
            score = 0.0
            if term in self._DISTRACTOR_FALLBACK:
                score += 1.0
            if term in {"class", "classes"}:
                score += 1.4
            if re.search(rf"\b(set|group|collection)\s+of\s+{re.escape(term)}\b", excerpt.lower()):
                score += 1.0
            if term.endswith("s") and term not in {"this"}:
                score += 0.2
            scored_terms.append((score, -index, term))
        if scored_terms:
            scored_terms.sort(reverse=True)
            return scored_terms[0][2]
        return ""

    def _build_candidate(
        self,
        *,
        lesson_title: str,
        lesson_summary: str,
        lesson_keywords: List[str],
        question_type: str,
        difficulty: str,
        bloom_level: str,
        chunk_id: str,
        claim: Dict[str, Any],
        all_claims: List[Dict[str, Any]],
        index: int = 0,
    ) -> Dict[str, Any] | None:
        bloom = bloom_level if bloom_level in self._BLOOM_TEMPLATES else "understand"
        template = self._BLOOM_TEMPLATES[bloom]
        excerpt = str(claim["excerpt"])
        content = str(claim["content"])
        focus = str(claim["focus"])
        instruction_role = str(claim["instruction_role"])
        covered_concepts = list(claim["covered_concepts"])
        statement = str(claim["statement"])
        predicate = str(claim["predicate"])
        answer_text = str(claim.get("answer_text") or "")
        variant = self._select_variant(
            question_type=question_type,
            difficulty=difficulty,
            bloom_level=bloom,
            instruction_role=instruction_role,
            answer_text=answer_text,
            index=index,
        )
        if question_type == "short_answer":
            question_text, correct_answer, explanation = self._build_short_answer_variant(
                variant=variant,
                lesson_title=lesson_title,
                lesson_summary=lesson_summary,
                instruction_role=instruction_role,
                focus=focus,
                answer_text=answer_text,
                statement=statement,
                difficulty=difficulty,
                base_prompt=template["short_answer"].format(
                    lesson_title=lesson_title,
                    focus=focus,
                ),
            )
            return {
                "question_type": "short_answer",
                "question": question_text,
                "correct_answer": correct_answer,
                "distractors": [],
                "explanation": explanation,
                "difficulty": difficulty,
                "bloom_level": bloom,
                "chunk_ids": [chunk_id],
                "metadata": {
                    "source_excerpt": excerpt,
                    "question_focus": focus,
                    "instruction_role": instruction_role,
                    "covered_concepts": covered_concepts,
                    "generation_source": "template",
                    "reasoning_note": "Generated from deterministic template.",
                    "generation_mode": "template",
                    "fallback_style": variant,
                    "difficulty_transform": difficulty,
                    "lesson_summary_keywords": list(lesson_keywords),
                },
            }

        if question_type == "true_false":
            if not self._is_true_false_safe(statement, focus=focus):
                return None
            return {
                "question_type": "true_false",
                "question": template["true_false"].format(
                    lesson_title=lesson_title,
                    statement=statement,
                ),
                "correct_answer": "True",
                "distractors": ["False"],
                "explanation": "Phat bieu duoc lay tu mot cau goc ro rang trong doan trich.",
                "difficulty": difficulty,
                "bloom_level": bloom,
                "chunk_ids": [chunk_id],
                "metadata": {
                    "source_excerpt": excerpt,
                    "question_focus": focus,
                    "instruction_role": instruction_role,
                    "covered_concepts": covered_concepts,
                    "generation_source": "template",
                    "reasoning_note": "Generated from deterministic template.",
                    "generation_mode": "template",
                    "fallback_style": "true_false_statement",
                    "difficulty_transform": difficulty,
                    "lesson_summary_keywords": list(lesson_keywords),
                },
            }

        question_text, answer, distractors, explanation = self._build_multiple_choice_variant(
            variant=variant,
            lesson_title=lesson_title,
            lesson_summary=lesson_summary,
            lesson_keywords=lesson_keywords,
            bloom_template=template["multiple_choice"],
            difficulty=difficulty,
            instruction_role=instruction_role,
            focus=focus,
            answer_text=answer_text,
            excerpt=excerpt,
            content=content,
            covered_concepts=covered_concepts,
            claim=claim,
            all_claims=all_claims,
        )
        if len(distractors) < 3:
            return None
        return {
            "question_type": "multiple_choice",
            "question": question_text,
            "correct_answer": answer,
            "distractors": distractors,
            "explanation": explanation,
            "difficulty": difficulty,
            "bloom_level": bloom,
            "chunk_ids": [chunk_id],
            "metadata": {
                "source_excerpt": excerpt,
                "question_focus": focus,
                "instruction_role": instruction_role,
                "covered_concepts": covered_concepts,
                "generation_source": "template",
                "reasoning_note": "Generated from deterministic template.",
                "generation_mode": "template",
                "fallback_style": variant,
                "difficulty_transform": difficulty,
                "lesson_summary_keywords": list(lesson_keywords),
            },
        }

    @staticmethod
    def _select_variant(
        *,
        question_type: str,
        difficulty: str,
        bloom_level: str,
        instruction_role: str,
        answer_text: str,
        index: int,
    ) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        if question_type == "short_answer":
            if difficulty_key == "advanced" and answer_text:
                return "complete_statement_short"
            if difficulty_key == "intermediate" and instruction_role == "worked_example":
                return "worked_example_short"
            if answer_text and index % 2 == 1:
                return "complete_statement_short"
            if instruction_role == "worked_example":
                return "worked_example_short"
            return "describe_focus_short"
        if question_type == "true_false":
            return "true_false_statement"
        if question_type != "multiple_choice":
            return "describe_focus_mcq"
        if difficulty_key == "advanced" and answer_text:
            return "focus_from_description_mcq"
        if difficulty_key == "intermediate" and answer_text and instruction_role in {"worked_example", "summary"}:
            return "complete_concept_mcq"
        if difficulty_key == "beginner" and answer_text:
            return "fill_blank_mcq"
        if answer_text and (bloom_level == "apply" or instruction_role == "worked_example"):
            return "focus_from_description_mcq"
        if answer_text and index % 4 == 1:
            return "fill_blank_mcq"
        if answer_text and index % 4 == 2:
            return "complete_concept_mcq"
        return "describe_focus_mcq"

    def _build_short_answer_variant(
        self,
        *,
        variant: str,
        lesson_title: str,
        lesson_summary: str,
        instruction_role: str,
        focus: str,
        answer_text: str,
        statement: str,
        difficulty: str,
        base_prompt: str,
    ) -> tuple[str, str, str]:
        correct_answer = answer_text or statement or focus
        if variant == "complete_statement_short" and answer_text:
            question_text = (
                f"Hoan thanh y sau theo noi dung bai hoc: '{focus}' ____."
            )
            explanation = (
                f"Doan trich mo ta '{focus}' voi y nghia: {correct_answer}."
            )
            return question_text, correct_answer, explanation
        question_text = self._build_short_answer_prompt(
            base_prompt,
            difficulty=difficulty,
            instruction_role=instruction_role,
            focus=focus,
            lesson_summary=lesson_summary,
            has_claim=bool(answer_text),
        )
        explanation = f"Doan trich cho thay '{focus}' {correct_answer}."
        return question_text, correct_answer, explanation

    def _build_multiple_choice_variant(
        self,
        *,
        variant: str,
        lesson_title: str,
        lesson_summary: str,
        lesson_keywords: List[str],
        bloom_template: str,
        difficulty: str,
        instruction_role: str,
        focus: str,
        answer_text: str,
        excerpt: str,
        content: str,
        covered_concepts: List[str],
        claim: Dict[str, Any],
        all_claims: List[Dict[str, Any]],
    ) -> tuple[str, str, List[str], str]:
        if variant == "focus_from_description_mcq" and answer_text:
            answer = focus
            distractors = self._build_focus_distractors(
                focus=focus,
                difficulty=difficulty,
                excerpt=excerpt,
                covered_concepts=list(dict.fromkeys([*covered_concepts, *lesson_keywords])),
                claim=claim,
                all_claims=all_claims,
            )
            question_text = self._build_focus_from_description_prompt(
                difficulty=difficulty,
                instruction_role=instruction_role,
                answer_text=answer_text,
            )
            explanation = (
                f"Doan trich mo ta chuc nang '{answer_text}', va khai niem phu hop nhat la '{focus}'."
            )
            return question_text, answer, distractors, explanation

        if variant == "complete_concept_mcq" and answer_text:
            answer = focus
            distractors = self._build_focus_distractors(
                focus=focus,
                difficulty=difficulty,
                excerpt=excerpt,
                covered_concepts=list(dict.fromkeys([*covered_concepts, *lesson_keywords])),
                claim=claim,
                all_claims=all_claims,
            )
            question_text = self._build_complete_concept_prompt(
                difficulty=difficulty,
                instruction_role=instruction_role,
                answer_text=answer_text,
            )
            explanation = (
                f"Doan trich cho thay khai niem phu hop de hoan thanh menh de nay la '{focus}'."
            )
            return question_text, answer, distractors, explanation

        answer = answer_text or focus
        distractors = self._build_distractors(
            answer=answer,
            difficulty=difficulty,
            excerpt=excerpt,
            content=content,
            preferred_terms=list(dict.fromkeys([*covered_concepts, *lesson_keywords])),
            claim=claim,
            all_claims=all_claims,
        )
        if variant == "fill_blank_mcq" and answer_text:
            question_text = self._build_fill_blank_prompt(
                difficulty=difficulty,
                instruction_role=instruction_role,
                focus=focus,
            )
            explanation = (
                f"Doan trich cho thay '{focus}' {answer}, nen day la cum dien phu hop nhat."
            )
            return question_text, answer, distractors, explanation

        question_text = self._build_multiple_choice_prompt(
            bloom_template.format(
                lesson_title=lesson_title,
                focus=focus,
            ),
            difficulty=difficulty,
            instruction_role=instruction_role,
            focus=focus,
            lesson_summary=lesson_summary,
            has_claim=bool(answer_text),
        )
        explanation = (
            f"Doan trich cho biet '{focus}' {answer}, nen day la lua chon dung nhat."
        )
        return question_text, answer, distractors, explanation

    def _build_focus_distractors(
        self,
        *,
        focus: str,
        difficulty: str,
        excerpt: str,
        covered_concepts: List[str],
        claim: Dict[str, Any],
        all_claims: List[Dict[str, Any]],
    ) -> List[str]:
        focus_key = self._normalize_text(focus)
        distractor_pool: List[tuple[float, str]] = []
        seen: set[str] = {focus_key}
        difficulty_key = str(difficulty or "beginner").strip().lower()

        for item in all_claims:
            if item is claim:
                continue
            candidate_focus = str(item.get("focus") or "").strip()
            normalized = self._normalize_text(candidate_focus)
            if not candidate_focus or not self._is_meaningful_focus_term(candidate_focus):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            distractor_pool.append(
                (
                    self._focus_distractor_score(
                        focus=focus,
                        candidate=candidate_focus,
                        covered_concepts=covered_concepts,
                        difficulty=difficulty_key,
                    ),
                    candidate_focus,
                )
            )

        for concept in covered_concepts:
            normalized = self._normalize_text(concept)
            if not concept or normalized in seen:
                continue
            seen.add(normalized)
            distractor_pool.append(
                (
                    self._focus_distractor_score(
                        focus=focus,
                        candidate=concept,
                        covered_concepts=covered_concepts,
                        difficulty=difficulty_key,
                    ),
                    concept,
                )
            )

        tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b", excerpt.lower())
        for token in tokens:
            normalized = self._normalize_text(token)
            if not self._is_meaningful_focus_term(token) or normalized in seen:
                continue
            seen.add(normalized)
            distractor_pool.append(
                (
                    self._focus_distractor_score(
                        focus=focus,
                        candidate=token,
                        covered_concepts=covered_concepts,
                        difficulty=difficulty_key,
                    ),
                    token,
                )
            )

        for fallback in self._DISTRACTOR_FALLBACK:
            normalized = self._normalize_text(fallback)
            if normalized in seen:
                continue
            seen.add(normalized)
            distractor_pool.append((0.05, fallback))
        distractor_pool.sort(key=lambda item: item[0], reverse=True)
        distractors = [item[1] for item in distractor_pool[:3]]
        return distractors[:3]

    @staticmethod
    def _build_focus_from_description_prompt(
        *,
        difficulty: str,
        instruction_role: str,
        answer_text: str,
    ) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        if instruction_role == "worked_example":
            if difficulty_key == "advanced":
                return (
                    f"Trong vi du cua bai hoc, khai niem nao suy ra hop ly nhat tu mo ta sau: '{answer_text}'?"
                )
            return (
                f"Trong vi du cua bai hoc, khai niem nao phu hop nhat voi mo ta sau: '{answer_text}'?"
            )
        if instruction_role == "summary":
            if difficulty_key == "advanced":
                return (
                    f"Theo phan tom tat, khai niem nao co the suy ra tu mo ta sau: '{answer_text}'?"
                )
            return (
                f"Theo phan tom tat, khai niem nao duoc mo ta la: '{answer_text}'?"
            )
        if difficulty_key == "advanced":
            return f"Theo noi dung bai hoc, khai niem nao giai thich dung nhat mo ta sau: '{answer_text}'?"
        if difficulty_key == "intermediate":
            return f"Theo noi dung bai hoc, khai niem nao phu hop nhat de ap dung cho mo ta sau: '{answer_text}'?"
        return f"Theo noi dung bai hoc, khai niem nao phu hop nhat voi mo ta sau: '{answer_text}'?"

    @staticmethod
    def _build_fill_blank_prompt(*, difficulty: str, instruction_role: str, focus: str) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        if instruction_role == "worked_example":
            if difficulty_key == "advanced":
                return f"Trong vi du cua bai hoc, thanh phan nao can dien vao cho trong de giu dung nghia cua '{focus}': '{focus}' ____?"
            return f"Trong vi du cua bai hoc, hoan thanh mo ta sau ve '{focus}': '{focus}' ____."
        if instruction_role == "summary":
            if difficulty_key == "advanced":
                return f"Theo phan tom tat, thanh phan nao can dien vao cho trong de mo ta chinh xac '{focus}': '{focus}' ____."
            return f"Theo phan tom tat, hoan thanh mo ta sau ve '{focus}': '{focus}' ____."
        if difficulty_key == "intermediate":
            return f"Theo noi dung bai hoc, cum nao dien vao cho trong de mo ta dung cach van hanh cua '{focus}': '{focus}' ____."
        return f"Theo noi dung bai hoc, phan nao dien vao cho trong de mo ta dung '{focus}': '{focus}' ____."

    @staticmethod
    def _build_complete_concept_prompt(
        *, difficulty: str, instruction_role: str, answer_text: str
    ) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        if instruction_role == "worked_example":
            if difficulty_key == "advanced":
                return (
                    f"Trong vi du cua bai hoc, khai niem nao can duoc suy ra de hoan thanh y sau: '____ {answer_text}'?"
                )
            return (
                f"Trong vi du cua bai hoc, khai niem nao dien vao cho trong de hoan thanh y sau: '____ {answer_text}'?"
            )
        if instruction_role == "summary":
            if difficulty_key == "advanced":
                return (
                    f"Theo phan tom tat, khai niem nao co vai tro hop ly nhat de hoan thanh y sau: '____ {answer_text}'?"
                )
            return (
                f"Theo phan tom tat, khai niem nao dien vao cho trong de hoan thanh y sau: '____ {answer_text}'?"
            )
        if difficulty_key == "intermediate":
            return (
                f"Theo noi dung bai hoc, khai niem nao phu hop nhat de hoan thanh y sau: '____ {answer_text}'?"
            )
        return (
            f"Theo noi dung bai hoc, khai niem nao dien vao cho trong de hoan thanh y sau: '____ {answer_text}'?"
        )

    def _build_distractors(
        self,
        *,
        answer: str,
        difficulty: str,
        excerpt: str,
        content: str,
        preferred_terms: List[str] | None = None,
        claim: Dict[str, Any] | None = None,
        all_claims: List[Dict[str, Any]] | None = None,
    ) -> List[str]:
        answer_key = self._normalize_text(answer)
        prefer_phrases = len(answer_key.split()) >= 3
        difficulty_key = str(difficulty or "beginner").strip().lower()
        candidates: List[tuple[float, str]] = []
        seen: set[str] = {answer_key}

        if claim and all_claims:
            for item in all_claims:
                if item is claim:
                    continue
                candidate = str(
                    item.get("answer_text")
                    or item.get("predicate")
                    or item.get("statement")
                    or item.get("focus")
                    or ""
                ).strip()
                normalized = self._normalize_text(candidate)
                if not candidate or not self._is_meaningful_option(candidate):
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(
                    (
                        self._option_distractor_score(
                            answer=answer,
                            candidate=candidate,
                            difficulty=difficulty_key,
                        ),
                        candidate,
                    )
                )

        for token in preferred_terms or []:
            normalized = self._normalize_text(token)
            if not self._is_meaningful_focus_term(normalized) or normalized in seen:
                continue
            if prefer_phrases and len(token.strip().split()) < 3:
                continue
            seen.add(normalized)
            candidates.append(
                (
                    self._option_distractor_score(
                        answer=answer,
                        candidate=token.strip(),
                        difficulty=difficulty_key,
                    ),
                    token.strip(),
                )
            )

        tokens = re.findall(
            r"\b[a-zA-Z][a-zA-Z0-9_]{3,}\b",
            f"{excerpt} {content}".lower(),
        )
        for token in tokens:
            normalized = self._normalize_text(token)
            if not self._is_meaningful_focus_term(normalized) or normalized in seen:
                continue
            if prefer_phrases:
                continue
            seen.add(normalized)
            candidates.append(
                (
                    self._option_distractor_score(
                        answer=answer,
                        candidate=token.strip(),
                        difficulty=difficulty_key,
                    ),
                    token.strip(),
                )
            )

        for fallback in self._DISTRACTOR_FALLBACK:
            normalized = self._normalize_text(fallback)
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append((0.05, self._fallback_option_phrase(fallback)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in candidates[:3]]

    def _extract_claim_statement(self, excerpt: str, *, focus: str) -> str:
        cleaned = excerpt.strip().rstrip(".")
        if not cleaned:
            return ""
        focus_pattern = re.escape(focus.strip())
        patterns = [
            rf"(?i)\b{focus_pattern}\b(?:\s+[a-zA-Z_][a-zA-Z0-9_-]{2,})?\s+(is|are|means|refers to|allows|helps|lets|can|repeats|stores|returns|contains|uses|creates|prints|imports|opens|displays|shows)\s+(.+)",
            rf"(?i)(use|using)\s+\b{focus_pattern}\b\s+to\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if match:
                return cleaned[:220]
        return cleaned[:220]

    def _extract_claim_predicate(self, statement: str, *, focus: str) -> str:
        cleaned = statement.strip().rstrip(".")
        focus_pattern = re.escape(focus.strip())
        patterns = [
            rf"(?i)\b{focus_pattern}\b(?:\s+[a-zA-Z_][a-zA-Z0-9_-]{2,})?\s+(is|are|means|refers to)\s+(.+)",
            rf"(?i)\b{focus_pattern}\b(?:\s+[a-zA-Z_][a-zA-Z0-9_-]{2,})?\s+(allows|helps|lets|can|repeats|stores|returns|contains|uses|creates|prints|imports|opens|displays|shows)\s+(.+)",
            rf"(?i)(use|using)\s+\b{focus_pattern}\b\s+to\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if not match:
                continue
            tail = str(match.group(match.lastindex or 0) or "").strip()
            tail = tail.strip(" .,:;")
            if self._is_meaningful_option(tail):
                return tail[:180]
        return ""

    def _is_meaningful_option(self, value: str) -> bool:
        normalized = self._normalize_text(value)
        if not normalized:
            return False
        if self._looks_like_noisy_excerpt(value):
            return False
        tokens = re.findall(r"[a-z][a-z0-9_]{1,}", normalized)
        if len(tokens) < 2:
            return self._is_meaningful_focus_term(normalized)
        return any(
            len(token) >= 4
            and token not in self._STOP_WORDS
            and token not in self._NOISY_TERMS
            for token in tokens
        )

    @staticmethod
    def _fallback_claim_answer(statement: str, *, focus: str) -> str:
        cleaned = statement.strip().rstrip(".")
        if not cleaned:
            return ""
        return cleaned[:180]

    def _localize_claim_answer(
        self,
        *,
        statement: str,
        focus: str,
        raw_answer: str,
    ) -> str:
        cleaned = statement.strip().rstrip(".")
        if not cleaned:
            return raw_answer
        focus_pattern = re.escape(focus.strip())
        verb_map = {
            "stores": "dung de luu",
            "displays": "dung de hien thi",
            "shows": "dung de hien thi",
            "repeats": "dung de lap",
            "prints": "dung de in",
            "creates": "dung de tao",
            "opens": "dung de mo",
            "imports": "dung de nap",
            "returns": "dung de tra ve",
            "contains": "dung de chua",
            "uses": "dung de su dung",
            "allows": "cho phep",
            "helps": "giup",
            "lets": "cho phep",
            "can": "co the",
            "is": "la",
            "are": "la",
            "means": "co nghia la",
            "refers to": "chi den",
        }
        patterns = [
            rf"(?i)\b{focus_pattern}\b(?:\s+[a-zA-Z_][a-zA-Z0-9_-]{{2,}})?\s+(is|are|means|refers to|allows|helps|lets|can|repeats|stores|returns|contains|uses|creates|prints|imports|opens|displays|shows)\s+(.+)",
            rf"(?i)(use|using)\s+\b{focus_pattern}\b\s+to\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned)
            if not match:
                continue
            if match.lastindex == 2:
                verb = str(match.group(1) or "").lower().strip()
                tail = str(match.group(2) or "").strip()
            else:
                verb = ""
                tail = str(match.group(match.lastindex or 0) or "").strip()
            localized_tail = self._localize_tail_phrase(tail or raw_answer)
            if not localized_tail:
                break
            if verb in {"is", "are", "means", "refers to"}:
                return f"{verb_map.get(verb, 'la')} {localized_tail}".strip()
            if verb in verb_map:
                return f"{verb_map[verb]} {localized_tail}".strip()
            if "use" in pattern.lower():
                return f"dung de {localized_tail}".strip()
        fallback_tail = self._localize_tail_phrase(raw_answer)
        return fallback_tail or raw_answer

    @staticmethod
    def _localize_tail_phrase(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip().rstrip("."))
        if not text:
            return ""
        replacements = [
            ("a block of code", "mot khoi lenh"),
            ("for each item in a sequence", "cho tung phan tu trong sequence"),
            ("a value", "mot gia tri"),
            ("that can be reused later", "de tai su dung sau"),
            ("in the program", "trong chuong trinh"),
            ("output on the screen", "ket qua tren man hinh"),
            ("the screen", "man hinh"),
            ("output", "ket qua"),
        ]
        localized = text
        for source, target in replacements:
            localized = re.sub(
                re.escape(source),
                target,
                localized,
                flags=re.IGNORECASE,
            )
        localized = re.sub(r"^\s*(a|an|the)\s+", "", localized, flags=re.IGNORECASE)
        localized = re.sub(r"\s+", " ", localized).strip(" ,.")
        return localized

    @staticmethod
    def _fallback_option_phrase(token: str) -> str:
        return f"lien quan den {token}"

    @staticmethod
    def _extract_instruction_role(chunk: Dict[str, Any]) -> str:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        return str(
            chunk.get("instruction_role")
            or metadata.get("instruction_role")
            or "explanation"
        ).strip().lower()

    @classmethod
    def _extract_covered_concepts(cls, chunk: Dict[str, Any]) -> List[str]:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        concepts: List[str] = []
        seen: set[str] = set()
        for source in (chunk.get("covered_concepts"), metadata.get("covered_concepts")):
            if isinstance(source, list):
                values = [str(item).strip() for item in source if str(item).strip()]
            elif isinstance(source, str):
                values = [source.strip()] if source.strip() else []
            else:
                values = []
            for value in values:
                normalized = cls._normalize_text(value)
                if not cls._is_meaningful_focus_term(normalized) or normalized in seen:
                    continue
                seen.add(normalized)
                concepts.append(value)
        return concepts

    @classmethod
    def _score_excerpt(cls, excerpt: str, *, preferred_terms: List[str]) -> float:
        normalized = cls._normalize_text(excerpt)
        if not normalized or cls._looks_like_noisy_excerpt(excerpt):
            return -1.0
        score = 1.0
        if any(
            term and re.search(rf"\b{re.escape(term)}\b", normalized)
            for term in preferred_terms
        ):
            score += 2.0
        if any(
            marker in normalized
            for marker in (" la ", " is ", " duoc ", " dung de ", " used to ")
        ):
            score += 0.8
        if len(normalized.split()) >= 8:
            score += 0.4
        return score

    @classmethod
    def _is_meaningful_focus_term(cls, value: str) -> bool:
        normalized = cls._normalize_text(value)
        if not normalized:
            return False
        if normalized in cls._STOP_WORDS or normalized in cls._NOISY_TERMS:
            return False
        if re.fullmatch(r"example\s*\d+([:-]\d+)?", normalized):
            return False
        tokens = re.findall(r"[a-z][a-z0-9_]{1,}", normalized)
        if not tokens:
            return False
        return any(
            len(token) >= 4
            and token not in cls._STOP_WORDS
            and token not in cls._NOISY_TERMS
            for token in tokens
        )

    @classmethod
    def _looks_like_noisy_excerpt(cls, text: str) -> bool:
        normalized = cls._normalize_text(text)
        if not normalized:
            return True
        if re.search(r"\bexample\s+\d+([:-]\d+)?\b", normalized):
            return True
        if normalized.count("{") >= 1 or normalized.count("}") >= 1:
            return True
        if normalized.count("[") >= 2 or normalized.count("]") >= 2:
            return True
        if normalized.count(":") >= 3:
            return True
        if re.search(r'"[a-z0-9_]+"\s*:', text):
            return True
        if re.search(
            r"\b(serial|twitter|affiliation|venue|venues|record|records)\b",
            normalized,
        ):
            return True
        punctuation = sum(1 for char in text if char in "{}[]\":,")
        return punctuation >= max(8, int(len(text) * 0.18))

    @classmethod
    def _is_true_false_safe(cls, statement: str, *, focus: str) -> bool:
        normalized = cls._normalize_text(statement)
        if cls._looks_like_noisy_excerpt(statement):
            return False
        if len(normalized.split()) < 6:
            return False
        focus_key = cls._normalize_text(focus)
        if focus_key and focus_key not in normalized:
            return False
        if normalized.count(":") > 1:
            return False
        return True

    @staticmethod
    def _build_multiple_choice_prompt(
        base_prompt: str,
        *,
        difficulty: str,
        instruction_role: str,
        focus: str,
        lesson_summary: str,
        has_claim: bool,
    ) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        summary_hint = QuestionTemplateService._lesson_summary_hint(lesson_summary)
        if has_claim:
            if instruction_role == "worked_example":
                if difficulty_key == "advanced":
                    return f"Trong vi du cua bai hoc{summary_hint}, lua chon nao suy ra dung nhat vai tro cua '{focus}'?"
                return f"Trong vi du cua bai hoc{summary_hint}, lua chon nao mo ta dung nhat vai tro cua '{focus}'?"
            if instruction_role == "summary":
                if difficulty_key == "advanced":
                    return f"Theo phan tom tat cua bai hoc{summary_hint}, phat bieu nao giai thich hop ly nhat vai tro cua '{focus}'?"
                return f"Theo phan tom tat cua bai hoc{summary_hint}, phat bieu nao dung nhat ve '{focus}'?"
            if instruction_role == "introduction":
                return f"Theo phan gioi thieu cua bai hoc{summary_hint}, lua chon nao mo ta dung nhat '{focus}'?"
            if difficulty_key == "intermediate":
                return f"Theo noi dung bai hoc{summary_hint}, lua chon nao phu hop nhat khi ap dung '{focus}'?"
            if difficulty_key == "advanced":
                return f"Theo noi dung bai hoc{summary_hint}, lua chon nao can duoc suy ra de mo ta chinh xac '{focus}'?"
            return f"Theo noi dung bai hoc{summary_hint}, lua chon nao mo ta dung nhat ve '{focus}'?"
        if instruction_role == "worked_example":
            return f"Trong vi du cua bai hoc{summary_hint}, khai niem nao dang duoc minh hoa ro nhat?"
        if instruction_role == "summary":
            return f"Theo phan tom tat cua bai hoc{summary_hint}, khai niem nao duoc nhan manh nhat?"
        if instruction_role == "introduction":
            return f"Theo phan gioi thieu cua bai hoc{summary_hint}, khai niem nao duoc dua ra lam trong tam?"
        return base_prompt

    @staticmethod
    def _build_short_answer_prompt(
        base_prompt: str,
        *,
        difficulty: str,
        instruction_role: str,
        focus: str,
        lesson_summary: str,
        has_claim: bool,
    ) -> str:
        difficulty_key = str(difficulty or "beginner").strip().lower()
        summary_hint = QuestionTemplateService._lesson_summary_hint(lesson_summary)
        if has_claim:
            if instruction_role == "worked_example":
                if difficulty_key == "advanced":
                    return f"Trong vi du cua bai hoc{summary_hint}, vi sao '{focus}' phu hop voi vai tro duoc mo ta?"
                return f"Trong vi du cua bai hoc{summary_hint}, '{focus}' duoc dung de lam gi?"
            if instruction_role == "summary":
                if difficulty_key == "advanced":
                    return f"Theo phan tom tat cua bai hoc{summary_hint}, hay giai thich vi sao '{focus}' quan trong."
                return f"Theo phan tom tat cua bai hoc{summary_hint}, '{focus}' co vai tro gi?"
            if difficulty_key == "intermediate":
                return f"Theo bai hoc{summary_hint}, '{focus}' duoc ap dung nhu the nao?"
            if difficulty_key == "advanced":
                return f"Theo bai hoc{summary_hint}, hay phan tich vai tro cua '{focus}' dua tren doan trich."
            return f"Theo bai hoc{summary_hint}, '{focus}' duoc mo ta nhu the nao?"
        if instruction_role == "worked_example":
            return f"Trong vi du cua bai hoc{summary_hint}, '{focus}' duoc dung de minh hoa dieu gi?"
        if instruction_role == "summary":
            return f"Theo phan tom tat cua bai hoc{summary_hint}, hay neu gon y chinh cua '{focus}'."
        return base_prompt

    @staticmethod
    def _lesson_summary_hint(lesson_summary: str) -> str:
        cleaned = " ".join(str(lesson_summary or "").strip().split())
        if not cleaned:
            return ""
        truncated = cleaned[:80].rstrip(" ,.;:")
        if not truncated:
            return ""
        return f" ve '{truncated}'"

    def _focus_distractor_score(
        self,
        *,
        focus: str,
        candidate: str,
        covered_concepts: List[str],
        difficulty: str,
    ) -> float:
        focus_key = self._normalize_text(focus)
        candidate_key = self._normalize_text(candidate)
        score = 0.1
        if not candidate_key or candidate_key == focus_key:
            return -1.0
        overlap = self._token_overlap_ratio(focus_key, candidate_key)
        if difficulty == "advanced":
            score += overlap * 1.4
        elif difficulty == "intermediate":
            score += overlap * 0.9
        else:
            score += max(0.0, 0.45 - overlap)
        if any(candidate_key == self._normalize_text(item) for item in covered_concepts):
            score += 0.35
        if len(candidate_key.split()) >= 2:
            score += 0.15
        return score

    def _option_distractor_score(
        self,
        *,
        answer: str,
        candidate: str,
        difficulty: str,
    ) -> float:
        answer_key = self._normalize_text(answer)
        candidate_key = self._normalize_text(candidate)
        if not candidate_key or candidate_key == answer_key:
            return -1.0
        overlap = self._token_overlap_ratio(answer_key, candidate_key)
        score = 0.1
        if difficulty == "advanced":
            score += overlap * 1.5
        elif difficulty == "intermediate":
            score += overlap * 1.0
        else:
            score += max(0.0, 0.4 - overlap)
        if len(candidate_key.split()) >= 2:
            score += 0.1
        if self._is_meaningful_option(candidate):
            score += 0.1
        return score

    @staticmethod
    def _token_overlap_ratio(left: str, right: str) -> float:
        left_tokens = {
            token for token in re.findall(r"[a-z][a-z0-9_]{2,}", left) if token
        }
        right_tokens = {
            token for token in re.findall(r"[a-z][a-z0-9_]{2,}", right) if token
        }
        if not left_tokens or not right_tokens:
            return 0.0
        overlap = len(left_tokens & right_tokens)
        return overlap / max(min(len(left_tokens), len(right_tokens)), 1)

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"\s+", " ", ascii_text.lower()).strip()

    @staticmethod
    def _signature(candidate: Dict[str, Any]) -> str:
        question = " ".join(str(candidate.get("question") or "").lower().split())
        answer = " ".join(str(candidate.get("correct_answer") or "").lower().split())
        return f"{question}|{answer}"


question_template_service = QuestionTemplateService()
