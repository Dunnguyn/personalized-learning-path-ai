"""AI tutor post-response helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_answer_beautifully(raw_text: str, resources: List[Dict]) -> str:
    if not raw_text:
        return "Xin lỗi, không thể tạo câu trả lời."

    text = raw_text.strip()
    lines = text.split("\n")
    formatted_parts = ["## Câu trả lời\n"]
    current_section = []
    for line in lines:
        line = line.strip()
        if line and len(line) > 10:
            current_section.append(line)

    if current_section:
        formatted_parts.append("\n".join(current_section))

    if resources:
        formatted_parts.append("\n\n## Nguồn tham khảo\n")
        sorted_resources = sorted(
            resources, key=lambda item: item.get("score", 0), reverse=True
        )[:3]
        for resource in sorted_resources:
            title = resource.get("title", "Unknown")
            score = resource.get("score", 0)
            formatted_parts.append(f"- **{title}** - Độ liên quan: {score:.0%}")

    return "\n".join(formatted_parts)


def build_fallback_context(service: Any, question: str, goal: Optional[str]) -> str:
    del question

    fallback_resources = service._get_default_resources(goal, None)
    if fallback_resources:
        for resource in fallback_resources:
            resource["is_real_resource"] = False

        context_parts = [
            "[Lưu ý: Hệ thống không tìm thấy tài liệu cụ thể trong cơ sở dữ liệu cho câu hỏi này]\n"
            "[Dưới đây là kiến thức bổ sung từ knowledge base có sẵn]\n\n"
        ]
        for idx, resource in enumerate(fallback_resources, 1):
            snippet = resource.get("snippet", "")
            title = resource.get("title", "Unknown")
            context_parts.append(f"[Nguồn {idx}: {title}]\n{snippet}\n\n")
        return "".join(context_parts)

    return "Không có thông tin cụ thể trong hệ thống."
