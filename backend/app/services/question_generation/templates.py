from __future__ import annotations

from typing import Dict, List, Tuple


# =====================================================
# PSEUDOCODE
# =====================================================
# select_template(bloom_level):
# 1. read template list for the bloom level
# 2. return deterministic list of (template_id, template_text)


remember_templates: List[Tuple[str, str]] = [
    ("remember_1", "{concept} là gì?"),
    ("remember_2", "Định nghĩa của {concept} là gì?"),
    ("remember_3", "Khái niệm {concept} được hiểu như thế nào?"),
]

understand_templates: List[Tuple[str, str]] = [
    ("understand_1", "Giải thích khái niệm {concept}."),
    ("understand_2", "Tại sao {concept} lại quan trọng?"),
    ("understand_3", "Mô tả cách hoạt động của {concept}."),
]

apply_templates: List[Tuple[str, str]] = [
    ("apply_1", "Làm thế nào để áp dụng {concept} trong thực tế?"),
    ("apply_2", "{concept} có thể được sử dụng trong trường hợp nào?"),
    ("apply_3", "Cho ví dụ sử dụng {concept}."),
]

analyze_templates: List[Tuple[str, str]] = [
    ("analyze_1", "Phân tích vai trò của {concept} trong hệ thống."),
    ("analyze_2", "Những yếu tố nào ảnh hưởng đến {concept}?"),
    ("analyze_3", "Tại sao {concept} lại quan trọng trong quá trình xử lý?"),
]

evaluate_templates: List[Tuple[str, str]] = [
    ("evaluate_1", "Ưu điểm và hạn chế của {concept} là gì?"),
    ("evaluate_2", "Trong trường hợp nào nên sử dụng {concept}?"),
    ("evaluate_3", "Đánh giá hiệu quả của {concept}."),
]

create_templates: List[Tuple[str, str]] = [
    ("create_1", "Thiết kế một ví dụ minh họa cho {concept}."),
    ("create_2", "Làm thế nào để cải tiến {concept} trong một hệ thống thực tế?"),
    ("create_3", "Đề xuất một cách ứng dụng mới của {concept}."),
]


BLOOM_TEMPLATE_MAP: Dict[str, List[Tuple[str, str]]] = {
    "remember": remember_templates,
    "understand": understand_templates,
    "apply": apply_templates,
    "analyze": analyze_templates,
    "evaluate": evaluate_templates,
    "create": create_templates,
}


def select_template(bloom_level: str) -> List[Tuple[str, str]]:
    return BLOOM_TEMPLATE_MAP.get(bloom_level, remember_templates)
