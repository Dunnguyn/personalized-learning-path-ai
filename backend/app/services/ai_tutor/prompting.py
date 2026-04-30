"""AI tutor prompting helpers."""

from __future__ import annotations

from typing import Any, Dict, List


FALLBACK_CONTEXT_MARKER = "[Lưu ý: Hệ thống không tìm thấy tài liệu cụ thể"
EMPTY_CONTEXT_MESSAGE = "Không có thông tin cụ thể trong hệ thống."


def build_context(
    service: Any,
    *,
    resources: List[Dict],
    max_context_chars: int,
    truncate_to_sentence: Any,
    logger: Any,
) -> str:
    del service

    if not resources:
        return "No learning materials found."

    blocks = []
    total_chars = 0

    for idx, resource in enumerate(resources, start=1):
        try:
            title = resource.get("title", "unknown")
            snippet = (resource.get("snippet") or "").strip()
            score = resource.get("score", 0)
            block = f"[Source {idx}: {title} (relevance: {score:.2f})]\n{snippet}"

            remaining = max_context_chars - total_chars
            if remaining <= 0:
                logger.debug("Context limit reached after %s resources", len(blocks))
                break

            if len(block) > remaining:
                truncated = truncate_to_sentence(block, remaining)
                if truncated:
                    blocks.append(truncated)
                    total_chars += len(truncated)
                break

            blocks.append(block)
            total_chars += len(block)
        except Exception as exc:
            logger.debug("Error processing resource %s: %s", idx, exc)
            continue

    context = "\n\n".join(blocks)
    logger.debug("Built context: %s blocks, %s chars", len(blocks), total_chars)
    return context


def build_prompt(
    service: Any,
    *,
    question: str,
    context: str,
    max_prompt_chars: int,
    truncate_to_sentence: Any,
    logger: Any,
) -> str:
    is_fallback = FALLBACK_CONTEXT_MARKER in context

    if is_fallback or not context or context == EMPTY_CONTEXT_MESSAGE:
        prompt = (
            "Bạn là AI Tutor, một trợ lý học tập thông minh.\n\n"
            "ĐỊNH DẠNG CÂU TRẢ LỜI:\n"
            "- Dùng Markdown để trình bày câu trả lời\n"
            "- Dùng ## để tạo tiêu đề khi cần\n"
            "- Dùng **text** để nhấn mạnh ý quan trọng\n"
            "- Dùng danh sách bullet khi cần liệt kê\n"
            "- Ngắt đoạn rõ ràng để dễ đọc\n\n"
            "NHIỆM VỤ CHÍNH:\n"
            "Trả lời trực tiếp và tập trung vào đúng câu hỏi của người học.\n"
            "- Giải thích rõ ràng, dễ hiểu, phù hợp với người mới bắt đầu\n"
            "- Ưu tiên ví dụ ngắn, đúng trọng tâm khi cần\n"
            "- Tránh lan man hoặc thêm thông tin không liên quan\n\n"
            f"CÂU HỎI:\n{question}\n\n"
            "CÂU TRẢ LỜI (dùng Markdown):"
        )
    else:
        prompt = (
            "Bạn là AI Tutor, một trợ lý học tập thông minh.\n\n"
            "ĐỊNH DẠNG CÂU TRẢ LỜI:\n"
            "- Dùng Markdown để trình bày câu trả lời\n"
            "- Dùng ## để tạo tiêu đề khi cần\n"
            "- Dùng **text** để nhấn mạnh ý quan trọng\n"
            "- Dùng danh sách bullet khi cần liệt kê\n"
            "- Ngắt đoạn rõ ràng để dễ đọc\n\n"
            "NHIỆM VỤ CHÍNH:\n"
            "Trả lời trực tiếp vào câu hỏi của người học dựa trên tài liệu được cung cấp.\n"
            "Quy tắc:\n"
            "1. Chỉ trả lời những gì liên quan trực tiếp đến câu hỏi\n"
            "2. Dùng tài liệu làm bằng chứng chính\n"
            "3. Bổ sung kiến thức nền khi tài liệu chưa đủ rõ\n"
            "4. Giải thích theo cách dễ hiểu cho người mới bắt đầu\n"
            "5. Tránh lan man sang nội dung không cần thiết\n\n"
            "TÀI LIỆU HỌC TẬP:\n"
            "====================\n"
            f"{context}\n"
            "====================\n\n"
            f"CÂU HỎI CỦA NGƯỜI HỌC:\n{question}\n\n"
            "CÂU TRẢ LỜI (dùng Markdown):"
        )

    if len(prompt) > max_prompt_chars:
        logger.warning("Prompt exceeds max size: %s > %s", len(prompt), max_prompt_chars)
        excess = len(prompt) - max_prompt_chars
        if excess > 0:
            truncated_context = truncate_to_sentence(context, len(context) - excess - 500)
            return build_prompt(
                service,
                question=question,
                context=truncated_context,
                max_prompt_chars=max_prompt_chars,
                truncate_to_sentence=truncate_to_sentence,
                logger=logger,
            )

    return prompt
