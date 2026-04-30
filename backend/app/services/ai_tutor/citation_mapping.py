"""AI tutor direct-answer and citation helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def can_answer_from_context(
    *,
    resources: List[Dict],
    logger: Any,
    direct_answer_threshold: float,
    min_high_quality_resources: int,
) -> bool:
    if not resources:
        return False

    real_resources = [r for r in resources if r.get("is_real_resource", False)]
    if not real_resources:
        logger.info("No real resources from database - must use AI")
        return False

    high_quality = [
        r for r in real_resources if r.get("score", 0) >= direct_answer_threshold
    ]
    can_answer = len(high_quality) >= min_high_quality_resources

    if can_answer:
        avg_score = sum(r.get("score", 0) for r in high_quality) / len(high_quality)
        logger.info(
            "Can answer from context: %s high-quality resources (avg score: %.2f)",
            len(high_quality),
            avg_score,
        )
    else:
        logger.info(
            "Cannot answer from context: only %s high-quality resources",
            len(high_quality),
        )
    return can_answer


def generate_direct_answer(
    *,
    question: str,
    resources: List[Dict],
    is_definition_question: Any,
    extract_main_terms: Any,
    keyword_overlap_score: Any,
    find_definition_sentence: Any,
) -> str:
    if not resources:
        return "Xin lá»—i, tÃ´i khÃ´ng tÃ¬m tháº¥y thÃ´ng tin liÃªn quan trong tÃ i liá»‡u há»c táº­p."

    definition_intent = is_definition_question(question)
    main_terms = extract_main_terms(question)

    def _rank_key(resource: Dict) -> tuple:
        snippet = (resource.get("snippet") or "").strip()
        overlap = keyword_overlap_score(question, snippet)
        def_hit = 0
        if definition_intent and main_terms:
            def_hit = 1 if find_definition_sentence(main_terms, snippet) else 0
        return (def_hit, overlap, resource.get("score", 0))

    sorted_resources = sorted(resources, key=_rank_key, reverse=True)
    top_resources = sorted_resources[:5]

    if (
        not top_resources
        or keyword_overlap_score(question, top_resources[0].get("snippet", "")) == 0
    ):
        return "Xin lá»—i, tÃ i liá»‡u hiá»‡n cÃ³ chÆ°a chá»©a thÃ´ng tin khá»›p vá»›i cÃ¢u há»i nÃ y."

    answer_parts = []
    best = top_resources[0]
    best_snippet = best.get("snippet", "").strip()
    if best_snippet:
        best_snippet = " ".join(best_snippet.split())
        if definition_intent and main_terms:
            def_sentence = find_definition_sentence(main_terms, best_snippet)
            if not def_sentence:
                return "Xin lá»—i, tÃ i liá»‡u hiá»‡n cÃ³ chÆ°a chá»©a thÃ´ng tin khá»›p vá»›i cÃ¢u há»i nÃ y."
            best_snippet = def_sentence
        if len(best_snippet) > 1000:
            best_snippet = best_snippet[:1000] + "..."
        answer_parts.append(f"## Tráº£ lá»i\n\n{best_snippet}\n")

    if len(top_resources) > 1:
        answer_parts.append("\n### ThÃ´ng tin thÃªm\n\n")
        for resource in top_resources[1:]:
            snippet = resource.get("snippet", "").strip()
            title = resource.get("title", "Unknown").strip()
            if snippet:
                excerpt = " ".join(snippet.split())
                if len(excerpt) > 250:
                    excerpt = excerpt[:250] + "..."
                source_title = title.split(" - ")[0].strip()
                answer_parts.append(f"- **{source_title}**: {excerpt}\n")

    answer_parts.append("\n### ðŸ“š Nguá»“n tham kháº£o\n\n")
    for idx, resource in enumerate(top_resources, 1):
        title = resource.get("title", "Unknown")
        score = resource.get("score", 0)
        answer_parts.append(f"{idx}. {title} (Ä‘á»™ liÃªn quan: {score:.0%})\n")

    return "".join(answer_parts)
