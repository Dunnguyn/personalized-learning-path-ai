"""Fallback question generation helpers."""

from __future__ import annotations

import re
from typing import Any, List, Type

from .noise_filter import assess_question_generation_noise
from .postprocess import (
    build_multiple_choice_prompt,
    build_short_answer_prompt,
    clean_true_false_statement,
    summarize_excerpt,
)


def build_fallback_question(
    *,
    service: Any,
    question_type: str,
    lesson_title: str,
    excerpt: str,
    strict_keywords: List[str],
    broad_keywords: List[str],
    relaxed_mode: bool = False,
) -> dict[str, Any] | None:
    excerpt_lower = service._normalize_text(excerpt)
    focus_term = find_focus_term(
        service_cls=service.__class__,
        excerpt=excerpt_lower,
        strict_keywords=strict_keywords,
        broad_keywords=broad_keywords,
    )
    if focus_term in service._AMBIGUOUS_TERMS:
        focus_term = find_specific_focus_term(
            service=service,
            excerpt=excerpt_lower,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        )
    if not focus_term and relaxed_mode:
        focus_term = find_specific_focus_term(
            service=service,
            excerpt=excerpt_lower,
            strict_keywords=strict_keywords,
            broad_keywords=broad_keywords,
        ) or service._first_meaningful_word(excerpt_lower)
    if not focus_term:
        return None
    if (
        not relaxed_mode
        and focus_term in service._AMBIGUOUS_TERMS
        and not has_context_anchor(
            service_cls=service.__class__,
            excerpt=excerpt_lower,
            focus_term=focus_term,
        )
    ):
        return None
    category = classify_term(service_cls=service.__class__, term=focus_term)
    if question_type == "multiple_choice":
        answer = focus_term or service._first_meaningful_word(excerpt)
        if not answer:
            return None
        distractors = build_distractors(
            service=service,
            answer=answer,
            excerpt=excerpt_lower,
            keywords=strict_keywords or broad_keywords,
            category=category,
            relaxed_mode=relaxed_mode,
        )
        if len(distractors) < 3:
            return None
        return {
            "question": build_multiple_choice_prompt(
                lesson_title=lesson_title,
                category=category,
                focus_term=answer,
            ),
            "correct_answer": answer,
            "distractors": distractors[:3],
            "focus_term": answer,
            "explanation": (
                f"Äoáº¡n trÃ­ch nÃªu trá»±c tiáº¿p khÃ¡i niá»‡m '{answer}', "
                "vÃ¬ váº­y Ä‘Ã¢y lÃ  Ä‘Ã¡p Ã¡n phÃ¹ há»£p nháº¥t."
            ),
        }
    if question_type == "true_false":
        statement = clean_true_false_statement(
            summarize_excerpt(
                service_cls=service.__class__,
                excerpt=excerpt,
                focus_term=focus_term,
            )
        )
        if len(statement) < 20:
            return None
        return {
            "question": (
                f"PhÃ¡t biá»ƒu sau lÃ  Ä‘Ãºng hay sai theo Ä‘oáº¡n trÃ­ch cá»§a "
                f"bÃ i '{lesson_title}'? \"{statement}\""
            ),
            "correct_answer": "True",
            "distractors": ["False"],
            "focus_term": focus_term,
            "explanation": (
                "PhÃ¡t biá»ƒu Ä‘Æ°á»£c giá»¯ nguyÃªn tá»« Ä‘oáº¡n trÃ­ch nÃªn "
                "Ä‘Æ°á»£c xem lÃ  Ä‘Ãºng theo ngá»¯ cáº£nh bÃ i há»c."
            ),
        }
    short_answer = summarize_excerpt(
        service_cls=service.__class__,
        excerpt=excerpt,
        focus_term=focus_term,
    )
    return {
        "question": build_short_answer_prompt(
            lesson_title=lesson_title,
            focus_term=focus_term,
        ),
        "correct_answer": short_answer,
        "distractors": [],
        "focus_term": focus_term,
        "explanation": (
            f"CÃ¢u tráº£ lá»i tÃ³m táº¯t trá»±c tiáº¿p cÃ¢u/Ã½ cÃ³ chá»©a "
            f"'{focus_term}' trong Ä‘oáº¡n trÃ­ch."
        ),
    }


def build_distractors(
    *,
    service: Any,
    answer: str,
    excerpt: str,
    keywords: List[str],
    category: str,
    relaxed_mode: bool,
) -> List[str]:
    normalized_answer = answer.strip().lower()
    answer_category = service._classify_term(normalized_answer)
    contextual_terms = extract_contextual_terms(
        service=service,
        excerpt=excerpt,
        keywords=keywords,
        category=answer_category,
        limit=12,
    )
    candidates = list(contextual_terms)
    candidates.extend(service._CATEGORY_POOLS.get(answer_category, []))
    if answer_category != category:
        candidates.extend(service._CATEGORY_POOLS.get(category, []))
    candidates.extend(
        item for item in keywords if item.strip().lower() != normalized_answer
    )
    candidates.extend(service._FALLBACK_DISTRACTORS)
    unique: List[str] = []
    seen = {normalized_answer, service._normalize_term_key(normalized_answer)}
    for item in candidates:
        cleaned = item.strip()
        key = cleaned.lower()
        stem_key = service._normalize_term_key(key)
        if len(cleaned) < 3 or key in service._FALLBACK_STOP_WORDS:
            continue
        if key in seen or stem_key in seen:
            continue
        if not relaxed_mode and key in service._WEAK_DISTRACTOR_TERMS:
            continue
        if service._classify_term(cleaned) == answer_category and cleaned.lower() == normalized_answer:
            continue
        if not relaxed_mode and service._classify_term(cleaned) == "general":
            continue
        seen.add(key)
        seen.add(stem_key)
        unique.append(cleaned)
    return unique


def find_specific_focus_term(
    *,
    service: Any,
    excerpt: str,
    strict_keywords: List[str],
    broad_keywords: List[str],
) -> str:
    candidates = extract_contextual_terms(
        service=service,
        excerpt=excerpt,
        keywords=strict_keywords + broad_keywords,
        category="general",
        limit=10,
    )
    for token in candidates:
        if token in service._AMBIGUOUS_TERMS or token in service._WEAK_DISTRACTOR_TERMS:
            continue
        if not service._is_domain_term(token):
            continue
        return token
    return ""


def extract_contextual_terms(
    *,
    service: Any,
    excerpt: str,
    keywords: List[str],
    category: str,
    limit: int,
) -> List[str]:
    tokens = re.findall(r"\b[a-z][a-z0-9_]{2,}\b", service._normalize_text(excerpt))
    scored: List[tuple[float, str]] = []
    for token in tokens:
        if token in service._FALLBACK_STOP_WORDS or token in service._WEAK_DISTRACTOR_TERMS:
            continue
        token_category = service._classify_term(token)
        if token_category == "general" and token not in keywords:
            continue
        score = 0.0
        if token_category == category:
            score += 1.5
        elif token_category != "general":
            score += 0.5
        if token in keywords:
            score += 0.8
        if len(token) >= 5:
            score += 0.2
        scored.append((score, token))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: List[str] = []
    seen: set[str] = set()
    for _, token in scored:
        key = service._normalize_term_key(token)
        if key in seen:
            continue
        seen.add(key)
        results.append(token)
        if len(results) >= limit:
            break
    return results


def find_focus_term(
    *,
    service_cls: Type[object],
    excerpt: str,
    strict_keywords: List[str],
    broad_keywords: List[str],
) -> str:
    for keyword_pool in (strict_keywords, broad_keywords):
        for keyword in sorted(keyword_pool, key=len, reverse=True):
            if keyword in service_cls._FALLBACK_STOP_WORDS:
                continue
            if re.search(rf"\b{re.escape(keyword)}\b", excerpt):
                if keyword in {"classes"}:
                    return "classes"
                if keyword in {"dictionary", "dictionaries"}:
                    return "dict"
                if keyword in {"lists"}:
                    return "list"
                if keyword in {"variables"}:
                    return "variable"
                if keyword in {"operators"}:
                    return "operator"
                return keyword
    return ""


def has_context_anchor(*, service_cls: Type[object], excerpt: str, focus_term: str) -> bool:
    if focus_term in {"value", "values", "item", "items", "key", "keys"}:
        anchors = {
            "dict",
            "dictionary",
            "dictionaries",
            "list",
            "lists",
            "tuple",
            "tuples",
        }
        return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
    if focus_term in {"type", "types"}:
        anchors = {"variable", "variables", "string", "integer", "float", "boolean"}
        return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
    if focus_term == "data":
        anchors = {
            "list",
            "dict",
            "dictionary",
            "variable",
            "operator",
            "string",
            "float",
            "integer",
        }
        return any(re.search(rf"\b{re.escape(anchor)}\b", excerpt) for anchor in anchors)
    return True


def score_excerpt_for_fallback(
    *,
    service_cls: Type[object],
    excerpt: str,
    strict_keywords: List[str],
    broad_keywords: List[str],
) -> float:
    normalized = service_cls._normalize_text(excerpt)
    if not normalized:
        return -1.0
    score = 0.0
    noise_signals = assess_question_generation_noise(
        content=excerpt,
        strict_keywords=strict_keywords,
        broad_keywords=broad_keywords,
        target_concepts=[*strict_keywords, *broad_keywords],
    )
    for pattern in service_cls._IRRELEVANT_EXCERPT_PATTERNS:
        if re.search(pattern, normalized):
            score -= 1.5
    strict_hits = 0
    for keyword in strict_keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            strict_hits += 1
            score += 1.25 if len(keyword) <= 5 else 1.6
    for keyword in broad_keywords:
        if keyword in strict_keywords:
            continue
        if re.search(rf"\b{re.escape(keyword)}\b", normalized):
            score += 0.35 if len(keyword) <= 5 else 0.5
    if strict_hits >= 2:
        score += 0.8
    if ">>>" in excerpt or "def " in excerpt:
        score += 0.4
    if any(
        token in normalized
        for token in (
            "list",
            "dict",
            "dictionary",
            "variable",
            "operator",
            "string",
            "float",
            "integer",
        )
    ):
        score += 0.8
    if len(normalized) < 60:
        score -= 0.5
    score -= float(noise_signals.get("noise_score", 0.0) or 0.0) * 3.4
    if noise_signals.get("resource_noise"):
        score -= 2.6
    return score


def classify_term(*, service_cls: Type[object], term: str) -> str:
    normalized = service_cls._normalize_text(term)
    if normalized in {
        "numpy",
        "ndarray",
        "array",
        "arrays",
        "matrix",
        "vector",
        "shape",
        "dtype",
        "ndim",
        "size",
    }:
        return "data_structure"
    if normalized in {
        "list",
        "dict",
        "dictionary",
        "tuple",
        "set",
        "keys",
        "values",
        "items",
    }:
        return "data_structure"
    if normalized in {
        "append",
        "sort",
        "split",
        "strip",
        "findall",
        "open",
        "read",
        "write",
        "reshape",
        "astype",
        "sum",
        "mean",
        "index",
        "slice",
        "slicing",
        "iterator",
        "iterators",
        "generator",
        "generators",
        "comprehension",
        "comprehensions",
    }:
        return "method"
    if normalized in {"string", "integer", "float", "boolean", "variable", "value"}:
        return "data_type"
    if normalized in {
        "operator",
        "arithmetic",
        "comparison",
        "logical",
        "expression",
        "assignment",
    }:
        return "operator"
    return "general"
