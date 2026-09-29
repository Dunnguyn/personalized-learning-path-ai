"""AI tutor answer-generation helpers."""

from __future__ import annotations

from typing import Any, Dict, List


QUESTION_MARKERS = (
    "CÂU HỎI CỦA NGƯỜI HỌC:",
    "CÂU HỎI:",
)
ANSWER_MARKERS = (
    "\n\nCÂU TRẢ LỜI",
    "\n\nANSWER",
)
CONTEXT_MARKERS = (
    "TÀI LIỆU HỌC TẬP:",
    "LEARNING MATERIALS:",
)
TRUNCATED_NOTICE = "\n\n*(Nội dung được cắt ngắn)*"


def _extract_between_markers(text: str, starts: tuple[str, ...], ends: tuple[str, ...]) -> str:
    for start_marker in starts:
        start = text.find(start_marker)
        if start < 0:
            continue
        content_start = start + len(start_marker)
        end_positions = [text.find(end_marker, content_start) for end_marker in ends]
        valid_end_positions = [position for position in end_positions if position >= 0]
        content_end = min(valid_end_positions) if valid_end_positions else len(text)
        return text[content_start:content_end].strip()
    return ""


def generate_answer(
    service: Any,
    *,
    prompt: str,
    resources: List[Dict] | None,
    use_llm: bool,
    client: Any,
    llm_cooldown_until: float,
    retry_after_seconds: float,
    logger: Any,
    timings: Dict[str, float] | None = None,
) -> str:
    if not (use_llm and client):
        logger.info("LLM unavailable - using knowledge base fallback")
        service.stats["fallback_uses"] += 1
        service._last_generation_mode = "fallback"
        return service._generate_fallback_answer(prompt, resources)

    if service._time_now() < llm_cooldown_until:
        logger.info("LLM cooldown active - using knowledge base fallback")
        service.stats["fallback_uses"] += 1
        service._last_generation_mode = "fallback"
        return service._generate_fallback_answer(prompt, resources)

    if retry_after_seconds > 0:
        logger.info("Gemini shared scope cooldown active - using knowledge base fallback")
        service.stats["fallback_uses"] += 1
        service._last_generation_mode = "fallback"
        return service._generate_fallback_answer(prompt, resources)

    answer = service._call_llm_with_retry(prompt, timings=timings)
    if answer:
        service.stats["successful_answers"] += 1
        service._last_generation_mode = "llm"
        return answer

    logger.warning("LLM generation failed - using knowledge base fallback")
    service.stats["fallback_uses"] += 1
    service._last_generation_mode = "fallback"
    return service._generate_fallback_answer(prompt, resources)


def generate_fallback_answer(
    service: Any,
    *,
    prompt: str,
    resources: List[Dict] | None,
    logger: Any,
    is_definition_question: Any,
    extract_main_terms: Any,
    keyword_overlap_score: Any,
    find_definition_sentence: Any,
) -> str:
    question_text = _extract_between_markers(prompt, QUESTION_MARKERS, ANSWER_MARKERS)

    if resources:
        logger.info(
            "Using fallback: generating targeted answer from %s resources",
            len(resources),
        )
        definition_intent = is_definition_question(question_text)
        main_terms = extract_main_terms(question_text)
        resource_snippets = []

        for resource in resources[:8]:
            snippet = resource.get("snippet", "").strip()
            title = resource.get("title", "Unknown").strip()
            score = resource.get("score", 0)
            if not snippet:
                continue

            snippet = " ".join(snippet.split())
            overlap = keyword_overlap_score(question_text, snippet)
            def_sentence = ""
            def_hit = 0
            if definition_intent and main_terms:
                def_sentence = find_definition_sentence(main_terms, snippet)
                def_hit = 1 if def_sentence else 0
            resource_snippets.append(
                {
                    "title": title,
                    "content": snippet,
                    "score": score,
                    "overlap": overlap,
                    "def_hit": def_hit,
                    "def_sentence": def_sentence,
                }
            )

        if resource_snippets:
            if definition_intent and max(r.get("def_hit", 0) for r in resource_snippets) == 0:
                fallback_resources = service._get_default_resources(question_text, None)
                if fallback_resources:
                    resource_snippets = []
                    for resource in fallback_resources:
                        snippet = (resource.get("snippet") or "").strip()
                        title = resource.get("title", "Unknown").strip()
                        score = resource.get("score", 0)
                        if not snippet:
                            continue

                        snippet = " ".join(snippet.split())
                        overlap = keyword_overlap_score(question_text, snippet)
                        def_sentence = ""
                        def_hit = 0
                        if definition_intent and main_terms:
                            def_sentence = find_definition_sentence(main_terms, snippet)
                            def_hit = 1 if def_sentence else 0
                        resource_snippets.append(
                            {
                                "title": title,
                                "content": snippet,
                                "score": score,
                                "overlap": overlap,
                                "def_hit": def_hit,
                                "def_sentence": def_sentence,
                            }
                        )

            resource_snippets.sort(
                key=lambda item: (
                    item.get("def_hit", 0),
                    item.get("overlap", 0),
                    item.get("score", 0),
                ),
                reverse=True,
            )

            if resource_snippets[0].get("overlap", 0) == 0:
                return (
                    "Xin lỗi, tài liệu hiện có chưa chứa thông tin khớp với câu hỏi này."
                )

            answer_parts = []
            if question_text:
                answer_parts.append("## Trả lời\n\n")

            best_content = resource_snippets[0]["content"]
            if definition_intent and resource_snippets[0].get("def_sentence"):
                best_content = resource_snippets[0]["def_sentence"]
            if len(best_content) > 900:
                best_content = best_content[:900] + "..."
            answer_parts.append(f"{best_content}\n")

            if len(resource_snippets) > 1:
                answer_parts.append("\n### Thông tin bổ sung\n\n")
                for item in resource_snippets[1:5]:
                    excerpt = item["content"][:250]
                    if len(item["content"]) > 250:
                        excerpt += "..."
                    source_title = item["title"].split(" - ")[0].strip()
                    answer_parts.append(f"- **{source_title}**: {excerpt}\n")

            answer = "".join(answer_parts)
            if len(answer) > 2500:
                answer = answer[:2500] + TRUNCATED_NOTICE
            return answer

    context = _extract_between_markers(prompt, CONTEXT_MARKERS, ("====================",))
    if context and len(context) > 50:
        heading = (
            "## Dựa trên tài liệu"
            if "TÀI LIỆU HỌC TẬP:" in prompt
            else "## Based on Learning Materials"
        )
        answer = f"{heading}\n\n{context}"
        if len(answer) > 2500:
            answer = answer[:2500] + TRUNCATED_NOTICE
        return answer

    return (
        "Tôi gặp khó khăn trong việc trích xuất thông tin. "
        "Vui lòng thử lại hoặc tham khảo phần tài liệu học tập."
    )
