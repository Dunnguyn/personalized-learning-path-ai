"""Prompt and fallback helpers for hybrid curriculum generation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


SUBJECT_CATALOG: Dict[str, str] = {
    "python": "Lập trình Python",
    "cpp": "Lập trình C++",
    "csharp": "Lập trình C#",
    "java": "Lập trình Java",
    "web": "Phát triển Web",
}

_FALLBACK_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "title": "Nền tảng Python",
            "lessons": [
                {"title": "Giới thiệu Python", "summary": "Làm quen với Python, môi trường chạy và tư duy lập trình cơ bản."},
                {"title": "Biến, kiểu dữ liệu và toán tử", "summary": "Nắm được cách lưu trữ dữ liệu, kiểu dữ liệu phổ biến và các phép toán cơ bản."},
                {"title": "Cấu trúc điều khiển", "summary": "Thực hành điều kiện, vòng lặp và kiểm soát luồng chương trình."},
            ],
        },
        {
            "title": "Lập trình Python thực hành",
            "lessons": [
                {"title": "Hàm và module", "summary": "Tổ chức mã nguồn bằng hàm, module và tái sử dụng logic hiệu quả."},
                {"title": "List, dict và xử lý dữ liệu", "summary": "Làm việc với cấu trúc dữ liệu thông dụng để giải quyết bài toán thực tế."},
                {"title": "Làm việc với file và xử lý lỗi", "summary": "Đọc ghi file, bắt lỗi và viết chương trình ổn định hơn."},
            ],
        },
        {
            "title": "Ứng dụng theo mục tiêu",
            "lessons": [
                {"title": "Thiết kế chương trình theo mục tiêu", "summary": "Kết nối các kiến thức Python để phục vụ mục tiêu học tập cụ thể."},
                {"title": "Tổ chức project Python", "summary": "Sắp xếp thư mục, tách module và chuẩn bị cho bài toán lớn hơn."},
                {"title": "Thực hành mini project", "summary": "Áp dụng Python vào một bài toán nhỏ gần với mục tiêu cuối cùng."},
            ],
        },
    ],
    "cpp": [
        {
            "title": "Nền tảng C++",
            "lessons": [
                {"title": "Giới thiệu C++ và cú pháp cơ bản", "summary": "Làm quen với ngôn ngữ C++, quy trình biên dịch và cú pháp nền tảng."},
                {"title": "Biến, kiểu dữ liệu và nhập xuất", "summary": "Nắm chắc kiểu dữ liệu, toán tử và thao tác nhập xuất chuẩn."},
                {"title": "Điều kiện và vòng lặp", "summary": "Thực hành kiểm soát luồng xử lý với if, switch, for và while."},
            ],
        },
        {
            "title": "Lập trình có cấu trúc",
            "lessons": [
                {"title": "Hàm và phạm vi biến", "summary": "Tổ chức chương trình bằng hàm và hiểu phạm vi hoạt động của biến."},
                {"title": "Mảng, chuỗi và con trỏ cơ bản", "summary": "Làm việc với bộ nhớ và cấu trúc dữ liệu nền tảng trong C++."},
                {"title": "Struct và class nhập môn", "summary": "Bắt đầu tiếp cận tư duy mô hình hóa dữ liệu bằng struct và class."},
            ],
        },
        {
            "title": "Ứng dụng và nâng cao",
            "lessons": [
                {"title": "Lập trình hướng đối tượng với C++", "summary": "Áp dụng class, object và tính đóng gói vào bài toán thực tế."},
                {"title": "Thư viện chuẩn STL cơ bản", "summary": "Sử dụng vector, string và algorithm để tăng tốc phát triển."},
                {"title": "Mini project C++", "summary": "Tổng hợp kiến thức để giải quyết một dự án nhỏ gần với mục tiêu học."},
            ],
        },
    ],
    "csharp": [
        {
            "title": "Nền tảng C#",
            "lessons": [
                {"title": "Giới thiệu C# và .NET", "summary": "Hiểu vai trò của C#, hệ sinh thái .NET và luồng phát triển cơ bản."},
                {"title": "Biến, kiểu dữ liệu và toán tử", "summary": "Làm quen với dữ liệu, biểu thức và cú pháp cơ bản của C#."},
                {"title": "Điều kiện, vòng lặp và method", "summary": "Thực hành kiểm soát luồng và tách logic bằng method."},
            ],
        },
        {
            "title": "Lập trình hướng đối tượng",
            "lessons": [
                {"title": "Class, object và property", "summary": "Xây dựng đối tượng và quản lý trạng thái bằng class, object, property."},
                {"title": "Kế thừa và interface", "summary": "Tổ chức hệ thống hướng đối tượng bằng kế thừa và interface."},
                {"title": "Collection và LINQ cơ bản", "summary": "Xử lý dữ liệu linh hoạt với collection và LINQ."},
            ],
        },
        {
            "title": "Ứng dụng theo mục tiêu",
            "lessons": [
                {"title": "Tổ chức project C#", "summary": "Cấu trúc project rõ ràng để phát triển ứng dụng thực tế."},
                {"title": "Xử lý lỗi và bất đồng bộ", "summary": "Viết chương trình ổn định hơn với exception và async cơ bản."},
                {"title": "Mini project C#", "summary": "Áp dụng các khối kiến thức C# vào một bài toán gần với mục tiêu học."},
            ],
        },
    ],
    "java": [
        {
            "title": "Nền tảng Java",
            "lessons": [
                {"title": "Giới thiệu Java và JVM", "summary": "Hiểu cách Java hoạt động, môi trường chạy và quy trình build cơ bản."},
                {"title": "Biến, kiểu dữ liệu và toán tử", "summary": "Làm quen với cú pháp và kiểu dữ liệu cơ bản trong Java."},
                {"title": "Điều kiện, vòng lặp và method", "summary": "Thực hành kiểm soát luồng và tổ chức chương trình bằng method."},
            ],
        },
        {
            "title": "Lập trình hướng đối tượng với Java",
            "lessons": [
                {"title": "Class, object và constructor", "summary": "Mô hình hóa dữ liệu với class, object và constructor."},
                {"title": "Kế thừa, interface và package", "summary": "Xây dựng chương trình có cấu trúc và khả năng mở rộng tốt hơn."},
                {"title": "Collection Framework cơ bản", "summary": "Xử lý danh sách và dữ liệu cấu trúc bằng các collection phổ biến."},
            ],
        },
        {
            "title": "Ứng dụng và thực hành",
            "lessons": [
                {"title": "Xử lý ngoại lệ và file", "summary": "Viết ứng dụng Java an toàn hơn với exception và thao tác file."},
                {"title": "Tổ chức project Java", "summary": "Sắp xếp source code và phụ thuộc để chuẩn bị cho ứng dụng lớn hơn."},
                {"title": "Mini project Java", "summary": "Áp dụng kiến thức Java vào một dự án nhỏ gắn với mục tiêu học tập."},
            ],
        },
    ],
    "web": [
        {
            "title": "Nền tảng Web",
            "lessons": [
                {"title": "Internet, HTTP và trình duyệt", "summary": "Hiểu cách web hoạt động, request/response và vai trò của trình duyệt."},
                {"title": "HTML cơ bản", "summary": "Xây dựng cấu trúc nội dung trang web bằng HTML."},
                {"title": "CSS cơ bản", "summary": "Trang trí giao diện, bố cục và kiểu hiển thị bằng CSS."},
            ],
        },
        {
            "title": "Tương tác trên Web",
            "lessons": [
                {"title": "JavaScript cơ bản", "summary": "Tạo tương tác động cho trang web với JavaScript."},
                {"title": "DOM và xử lý sự kiện", "summary": "Điều khiển giao diện và phản hồi thao tác người dùng."},
                {"title": "Làm việc với API", "summary": "Kết nối frontend với dữ liệu backend qua HTTP API."},
            ],
        },
        {
            "title": "Xây dựng sản phẩm Web",
            "lessons": [
                {"title": "Tổ chức giao diện và component", "summary": "Chia nhỏ giao diện và tái sử dụng thành phần hợp lý."},
                {"title": "Hiệu năng và responsive", "summary": "Tối ưu trải nghiệm web trên nhiều kích thước màn hình."},
                {"title": "Mini project Web", "summary": "Tổng hợp kiến thức để xây dựng một ứng dụng web nhỏ theo mục tiêu học."},
            ],
        },
    ],
}


def get_subject_label(subject_id: str) -> Optional[str]:
    """Resolve the fixed subject label from the supported catalog."""
    return SUBJECT_CATALOG.get((subject_id or "").strip().lower())


def build_learning_path_prompt(subject_label: str, goal: str, level: str) -> str:
    """Build a curriculum-only prompt for the cloud LLM."""
    schema = {
        "chapters": [
            {
                "title": "string",
                "lessons": [
                    {
                        "title": "string",
                        "summary": "string",
                    }
                ],
            }
        ]
    }
    return (
        "Bạn là AI thiết kế lộ trình học tập.\n\n"
        f"Môn học: {subject_label}\n"
        f"Mục tiêu: {goal}\n"
        f"Trình độ: {level}\n\n"
        "Hãy tạo lộ trình học gồm các chương và bài học.\n\n"
        "Yêu cầu:\n"
        "- Các bài học đi từ cơ bản đến nâng cao.\n"
        "- Phù hợp với trình độ người học.\n"
        "- Bám sát môn học đã chọn.\n"
        "- Không lan sang lĩnh vực khác.\n"
        "- Mỗi chương nên có từ 2 đến 4 bài học.\n"
        "- Mỗi bài học phải có title và summary ngắn, rõ ràng.\n\n"
        "Trả về JSON đúng schema sau:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        "Chỉ trả JSON, không giải thích."
    )


def extract_json_object(text: str) -> Optional[str]:
    """Extract a JSON object from raw LLM text."""
    if not text:
        return None
    fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return fenced_match.group(1).strip()
    raw_match = re.search(r"\{.*\}", text, re.DOTALL)
    if raw_match:
        return raw_match.group(0).strip()
    return None


def normalize_curriculum(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize LLM curriculum output into a stable local structure."""
    normalized: List[Dict[str, Any]] = []
    chapters = payload.get("chapters", []) if isinstance(payload, dict) else []
    if not isinstance(chapters, list):
        return normalized

    for chapter in chapters:
        title = str(chapter.get("title") or "").strip()
        if not title:
            continue
        lessons_payload = chapter.get("lessons", [])
        lessons: List[Dict[str, str]] = []
        if isinstance(lessons_payload, list):
            for lesson in lessons_payload:
                lesson_title = str(lesson.get("title") or "").strip()
                summary = str(lesson.get("summary") or "").strip()
                if not lesson_title:
                    continue
                lessons.append(
                    {
                        "title": lesson_title,
                        "summary": summary or f"Học nội dung cốt lõi của bài {lesson_title}.",
                    }
                )
        if lessons:
            normalized.append({"title": title, "lessons": lessons})
    return normalized


def build_fallback_curriculum(subject_id: str, goal: str, level: str) -> List[Dict[str, Any]]:
    """Return a deterministic curriculum when the cloud LLM fails."""
    subject_key = (subject_id or "").strip().lower()
    chapters = _FALLBACK_TEMPLATES.get(subject_key, [])
    if not chapters:
        return [
            {
                "title": "Lộ trình nền tảng",
                "lessons": [
                    {
                        "title": "Tổng quan môn học",
                        "summary": f"Hiểu bức tranh tổng thể để bắt đầu mục tiêu {goal}.",
                    },
                    {
                        "title": "Khái niệm cốt lõi",
                        "summary": f"Nắm vững các khái niệm quan trọng phù hợp với trình độ {level}.",
                    },
                ],
            },
            {
                "title": "Thực hành theo mục tiêu",
                "lessons": [
                    {
                        "title": "Ứng dụng theo mục tiêu",
                        "summary": f"Liên kết kiến thức với mục tiêu học tập: {goal}.",
                    },
                    {
                        "title": "Ôn tập và tổng kết",
                        "summary": "Củng cố kiến thức và chuẩn bị cho bước học tiếp theo.",
                    },
                ],
            },
        ]

    fallback: List[Dict[str, Any]] = []
    for chapter in chapters:
        lessons = []
        for lesson in chapter["lessons"]:
            lessons.append(
                {
                    "title": lesson["title"],
                    "summary": f"{lesson['summary']} Mục tiêu hiện tại: {goal}. Trình độ: {level}.",
                }
            )
        fallback.append({"title": chapter["title"], "lessons": lessons})
    return fallback
