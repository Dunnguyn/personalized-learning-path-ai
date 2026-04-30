"""Prompt and fallback helpers for learning-path curriculum generation."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


SUBJECT_CATALOG: Dict[str, str] = {
    "python": "Python Programming",
    "cpp": "C++ Programming",
    "csharp": "C# Programming",
    "java": "Java Programming",
    "web": "Web Development",
}

LEARNING_PATH_GOLDEN_EXAMPLES_ENABLED = (
    os.getenv("LEARNING_PATH_GOLDEN_EXAMPLES_ENABLED", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)

_GOLDEN_CURRICULUM_EXAMPLES: Dict[str, List[Dict[str, Any]]] = {
    "python_backend": [
        {
            "title": "Python Foundations and Syntax",
            "lessons": [
                {"title": "Set up Python and run programs", "summary": "Install Python, run scripts, and understand the basic execution flow."},
                {"title": "Variables, data types, and expressions", "summary": "Work with values, variables, and the most common Python data types."},
                {"title": "Conditions and loops", "summary": "Control program behavior with branching and repetition."},
            ],
        },
        {
            "title": "Functions and Core Data Structures",
            "lessons": [
                {"title": "Define and call functions", "summary": "Organize logic into reusable functions with parameters and return values."},
                {"title": "Lists, dictionaries, and sets", "summary": "Use Python collections to store and process structured data."},
                {"title": "Iteration patterns in Python", "summary": "Traverse and transform data with practical iteration patterns."},
            ],
        },
        {
            "title": "Object-Oriented Programming in Python",
            "lessons": [
                {"title": "Classes and objects", "summary": "Model real-world concepts with classes and instances."},
                {"title": "Methods, attributes, and encapsulation", "summary": "Design cleaner object behavior with attributes and methods."},
                {"title": "Inheritance and composition", "summary": "Reuse and combine behavior across related Python classes."},
            ],
        },
        {
            "title": "Web Backend Foundations",
            "lessons": [
                {"title": "How backend systems fit into web applications", "summary": "Understand the role of backend services in a web product."},
                {"title": "HTTP request-response basics", "summary": "Learn the HTTP flow, methods, headers, and status codes."},
                {"title": "Routing and server-side processing", "summary": "Map incoming requests to backend logic and responses."},
            ],
        },
        {
            "title": "Building APIs with Flask",
            "lessons": [
                {"title": "Create a basic Flask application", "summary": "Start a Flask app and understand the app lifecycle."},
                {"title": "Define routes and view functions", "summary": "Handle URLs and connect them to Python functions."},
                {"title": "Work with JSON requests and responses", "summary": "Build API endpoints that send and receive JSON data."},
                {"title": "Structure a small Flask API project", "summary": "Organize a growing Flask codebase into maintainable modules."},
            ],
        },
        {
            "title": "Database Integration for Backend Apps",
            "lessons": [
                {"title": "Database concepts for backend developers", "summary": "Understand tables, records, and persistence in backend systems."},
                {"title": "Use SQLite with Python", "summary": "Read and write application data with a lightweight relational database."},
                {"title": "Connect API endpoints to stored data", "summary": "Integrate Flask endpoints with database operations in one workflow."},
            ],
        },
    ],
}

_GOLDEN_CURRICULUM_EXAMPLES_VI: Dict[str, List[Dict[str, Any]]] = {
    "python_backend": [
        {
            "title": "Nhập Môn Python và Cú Pháp Cơ Bản",
            "lessons": [
                {"title": "Cài đặt Python và chạy chương trình đầu tiên", "summary": "Làm quen với môi trường Python và cách chạy chương trình cơ bản."},
                {"title": "Biến, kiểu dữ liệu và biểu thức", "summary": "Sử dụng biến, giá trị và các kiểu dữ liệu phổ biến trong Python."},
                {"title": "Điều kiện và vòng lặp", "summary": "Điều khiển luồng chương trình bằng rẽ nhánh và lặp."},
            ],
        },
        {
            "title": "Cấu Trúc Dữ Liệu và Hàm trong Python",
            "lessons": [
                {"title": "Định nghĩa và sử dụng hàm", "summary": "Tổ chức logic bằng hàm với tham số và giá trị trả về."},
                {"title": "Danh sách, từ điển và tập hợp", "summary": "Làm việc với các collection quan trọng trong Python."},
                {"title": "Mẫu lặp và xử lý dữ liệu", "summary": "Duyệt và biến đổi dữ liệu bằng các mẫu lặp thực tế."},
            ],
        },
        {
            "title": "Lập Trình Hướng Đối Tượng (OOP) với Python",
            "lessons": [
                {"title": "Class và object", "summary": "Mô hình hóa dữ liệu và hành vi bằng class và object."},
                {"title": "Thuộc tính, phương thức và đóng gói", "summary": "Thiết kế đối tượng rõ ràng hơn với attribute và method."},
                {"title": "Kế thừa và kết hợp đối tượng", "summary": "Tái sử dụng và mở rộng hành vi giữa các class liên quan."},
            ],
        },
        {
            "title": "Giới Thiệu Phát Triển Web Backend với Python",
            "lessons": [
                {"title": "Vai trò của backend trong ứng dụng web", "summary": "Hiểu backend tham gia như thế nào trong một sản phẩm web."},
                {"title": "HTTP request và response", "summary": "Nắm mô hình request-response, method, header và status code."},
                {"title": "Routing và xử lý phía server", "summary": "Kết nối request web với logic xử lý ở phía backend."},
            ],
        },
        {
            "title": "Xây Dựng API Cơ Bản với Flask",
            "lessons": [
                {"title": "Tạo ứng dụng Flask đầu tiên", "summary": "Khởi tạo dự án Flask và hiểu vòng đời ứng dụng cơ bản."},
                {"title": "Định nghĩa route và view function", "summary": "Xử lý URL và liên kết request với hàm Python."},
                {"title": "Làm việc với JSON trong API", "summary": "Nhận và trả dữ liệu JSON qua các endpoint API."},
                {"title": "Tổ chức cấu trúc dự án Flask nhỏ", "summary": "Sắp xếp mã nguồn Flask thành cấu trúc dễ mở rộng hơn."},
            ],
        },
        {
            "title": "Tương Tác với Cơ Sở Dữ Liệu",
            "lessons": [
                {"title": "Khái niệm cơ sở dữ liệu cho backend", "summary": "Hiểu bảng, bản ghi và cách lưu trữ dữ liệu cho ứng dụng backend."},
                {"title": "Làm việc với SQLite bằng Python", "summary": "Đọc ghi dữ liệu với cơ sở dữ liệu quan hệ nhẹ trong Python."},
                {"title": "Kết nối API với dữ liệu lưu trữ", "summary": "Tích hợp endpoint Flask với thao tác dữ liệu trong một quy trình hoàn chỉnh."},
            ],
        },
    ],
}

_FALLBACK_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "title": "Python Foundations",
            "lessons": [
                {"title": "Python setup and syntax", "summary": "Set up Python, run scripts, and read basic syntax."},
                {"title": "Variables and data types", "summary": "Work with values, expressions, and common built-in types."},
                {"title": "Control flow", "summary": "Use conditions and loops to control program behavior."},
            ],
        },
        {
            "title": "Core Python Practice",
            "lessons": [
                {"title": "Functions and modules", "summary": "Structure code into reusable functions and modules."},
                {"title": "Collections and iteration", "summary": "Use lists, dictionaries, sets, and iteration patterns effectively."},
                {"title": "Files and exceptions", "summary": "Read files and handle errors safely."},
            ],
        },
        {
            "title": "Goal-Oriented Application",
            "lessons": [
                {"title": "Designing a Python solution", "summary": "Translate the learning goal into a concrete Python workflow."},
                {"title": "Project structure", "summary": "Organize code for maintainability and incremental growth."},
                {"title": "Mini project", "summary": "Build a small project that reflects the learner goal."},
            ],
        },
    ],
    "cpp": [
        {
            "title": "C++ Foundations",
            "lessons": [
                {"title": "C++ toolchain and syntax", "summary": "Compile, run, and understand core C++ syntax."},
                {"title": "Variables, types, and IO", "summary": "Use primitive types, operators, and console input/output."},
                {"title": "Conditions and loops", "summary": "Control execution with branching and repetition."},
            ],
        },
        {
            "title": "Structured Programming",
            "lessons": [
                {"title": "Functions and scope", "summary": "Break problems into functions and manage local state."},
                {"title": "Arrays, strings, and pointers", "summary": "Handle common data layouts and memory-oriented basics."},
                {"title": "Structs and classes", "summary": "Model data using structured and object-oriented types."},
            ],
        },
        {
            "title": "Applied C++",
            "lessons": [
                {"title": "Object-oriented design", "summary": "Apply classes and encapsulation to realistic problems."},
                {"title": "STL essentials", "summary": "Use vector, string, and algorithm to solve problems faster."},
                {"title": "Mini project", "summary": "Implement a small C++ project aligned with the learner goal."},
            ],
        },
    ],
    "csharp": [
        {
            "title": "C# Foundations",
            "lessons": [
                {"title": "C# and .NET basics", "summary": "Understand the .NET runtime and core C# syntax."},
                {"title": "Types and expressions", "summary": "Work with data types, variables, and expressions."},
                {"title": "Methods and flow control", "summary": "Build reusable logic with methods and control statements."},
            ],
        },
        {
            "title": "Object-Oriented C#",
            "lessons": [
                {"title": "Classes and properties", "summary": "Model state and behavior with classes and properties."},
                {"title": "Inheritance and interfaces", "summary": "Compose flexible systems with interfaces and inheritance."},
                {"title": "Collections and LINQ", "summary": "Query and transform collections efficiently."},
            ],
        },
        {
            "title": "Applied C#",
            "lessons": [
                {"title": "Project organization", "summary": "Structure a C# project for maintainable delivery."},
                {"title": "Exceptions and async basics", "summary": "Handle failure and asynchronous workflows."},
                {"title": "Mini project", "summary": "Create a small C# project tied to the learner goal."},
            ],
        },
    ],
    "java": [
        {
            "title": "Java Foundations",
            "lessons": [
                {"title": "Java and the JVM", "summary": "Understand Java execution, tooling, and basic syntax."},
                {"title": "Variables and operators", "summary": "Use Java types, expressions, and core operators."},
                {"title": "Methods and control flow", "summary": "Organize logic with methods, conditions, and loops."},
            ],
        },
        {
            "title": "Object-Oriented Java",
            "lessons": [
                {"title": "Classes and constructors", "summary": "Build domain models with classes and constructors."},
                {"title": "Inheritance, interfaces, and packages", "summary": "Create modular and extensible Java programs."},
                {"title": "Collections framework", "summary": "Use common collection types to manage data."},
            ],
        },
        {
            "title": "Applied Java",
            "lessons": [
                {"title": "Exceptions and files", "summary": "Write safer Java applications with error and file handling."},
                {"title": "Project structure", "summary": "Organize Java code and dependencies for larger work."},
                {"title": "Mini project", "summary": "Deliver a small Java project aligned with the learner goal."},
            ],
        },
    ],
    "web": [
        {
            "title": "Web Foundations",
            "lessons": [
                {"title": "How the web works", "summary": "Understand browsers, HTTP, and request-response flow."},
                {"title": "HTML structure", "summary": "Create semantic page structure with HTML."},
                {"title": "CSS styling", "summary": "Style layouts, spacing, and responsive presentation with CSS."},
            ],
        },
        {
            "title": "Interactive Web",
            "lessons": [
                {"title": "JavaScript basics", "summary": "Use JavaScript to add logic and interactivity."},
                {"title": "DOM and events", "summary": "Respond to user actions and update the page dynamically."},
                {"title": "Working with APIs", "summary": "Fetch and render data from backend services."},
            ],
        },
        {
            "title": "Product-Oriented Web Development",
            "lessons": [
                {"title": "UI organization and components", "summary": "Break interfaces into reusable and maintainable pieces."},
                {"title": "Responsiveness and performance", "summary": "Improve usability across devices and optimize delivery."},
                {"title": "Mini project", "summary": "Build a small web project tied to the learner goal."},
            ],
        },
    ],
}

_FALLBACK_TEMPLATES_VI: Dict[str, List[Dict[str, Any]]] = {
    "python": [
        {
            "title": "Nền Tảng Python",
            "lessons": [
                {"title": "Cài đặt Python và cú pháp cơ bản", "summary": "Làm quen với môi trường Python, cách chạy chương trình và cú pháp nền tảng."},
                {"title": "Biến và kiểu dữ liệu", "summary": "Sử dụng biến, biểu thức và các kiểu dữ liệu cơ bản trong Python."},
                {"title": "Cấu trúc điều khiển", "summary": "Dùng điều kiện và vòng lặp để điều khiển luồng chương trình."},
            ],
        },
        {
            "title": "Thực Hành Python Cốt Lõi",
            "lessons": [
                {"title": "Hàm và module", "summary": "Tổ chức mã nguồn bằng hàm và module để tái sử dụng hiệu quả."},
                {"title": "Danh sách, từ điển và lặp", "summary": "Làm việc với collection phổ biến và các mẫu lặp trong Python."},
                {"title": "Tệp và xử lý ngoại lệ", "summary": "Đọc ghi tệp và xử lý lỗi an toàn trong chương trình Python."},
            ],
        },
        {
            "title": "Ứng Dụng Theo Mục Tiêu",
            "lessons": [
                {"title": "Thiết kế lời giải bằng Python", "summary": "Chuyển mục tiêu học tập thành một quy trình giải quyết bằng Python cụ thể."},
                {"title": "Tổ chức dự án Python", "summary": "Sắp xếp mã nguồn để dễ bảo trì và phát triển dần theo mục tiêu."},
                {"title": "Dự án nhỏ", "summary": "Xây dựng một dự án Python nhỏ bám sát mục tiêu học tập hiện tại."},
            ],
        },
    ],
    "cpp": [
        {
            "title": "Nền Tảng C++",
            "lessons": [
                {"title": "Môi trường C++ và cú pháp cơ bản", "summary": "Biên dịch, chạy chương trình và làm quen với cú pháp cốt lõi của C++."},
                {"title": "Biến, kiểu dữ liệu và nhập xuất", "summary": "Sử dụng kiểu dữ liệu, toán tử và nhập xuất cơ bản trong C++."},
                {"title": "Điều kiện và vòng lặp", "summary": "Điều khiển luồng chương trình bằng rẽ nhánh và lặp."},
            ],
        },
        {
            "title": "Lập Trình Có Cấu Trúc",
            "lessons": [
                {"title": "Hàm và phạm vi biến", "summary": "Chia bài toán thành các hàm và quản lý biến trong từng phạm vi."},
                {"title": "Mảng, chuỗi và con trỏ", "summary": "Làm việc với dữ liệu tuyến tính và các khái niệm bộ nhớ cơ bản."},
                {"title": "Struct và class", "summary": "Mô hình hóa dữ liệu bằng kiểu có cấu trúc và hướng đối tượng."},
            ],
        },
        {
            "title": "Ứng Dụng C++",
            "lessons": [
                {"title": "Thiết kế hướng đối tượng", "summary": "Áp dụng class và đóng gói vào các bài toán thực tế."},
                {"title": "STL thiết yếu", "summary": "Sử dụng vector, string và algorithm để giải quyết bài toán nhanh hơn."},
                {"title": "Dự án nhỏ", "summary": "Hoàn thành một dự án C++ nhỏ bám theo mục tiêu học tập."},
            ],
        },
    ],
    "csharp": [
        {
            "title": "Nền Tảng C#",
            "lessons": [
                {"title": "C# và .NET cơ bản", "summary": "Làm quen với runtime .NET và cú pháp cốt lõi của C#."},
                {"title": "Kiểu dữ liệu và biểu thức", "summary": "Sử dụng biến, kiểu dữ liệu và biểu thức trong C#."},
                {"title": "Phương thức và điều khiển luồng", "summary": "Tổ chức logic bằng method, điều kiện và vòng lặp."},
            ],
        },
        {
            "title": "C# Hướng Đối Tượng",
            "lessons": [
                {"title": "Class và property", "summary": "Mô hình hóa trạng thái và hành vi bằng class và property."},
                {"title": "Kế thừa và interface", "summary": "Thiết kế hệ thống linh hoạt bằng kế thừa và interface."},
                {"title": "Collection và LINQ", "summary": "Truy vấn và biến đổi dữ liệu với collection và LINQ."},
            ],
        },
        {
            "title": "Ứng Dụng C#",
            "lessons": [
                {"title": "Tổ chức dự án", "summary": "Sắp xếp cấu trúc dự án C# để dễ bảo trì và mở rộng."},
                {"title": "Ngoại lệ và async cơ bản", "summary": "Xử lý lỗi và làm quen với tác vụ bất đồng bộ."},
                {"title": "Dự án nhỏ", "summary": "Xây dựng một dự án C# nhỏ gắn với mục tiêu học tập."},
            ],
        },
    ],
    "java": [
        {
            "title": "Nền Tảng Java",
            "lessons": [
                {"title": "Java và JVM", "summary": "Hiểu cách Java chạy, công cụ cơ bản và cú pháp nền tảng."},
                {"title": "Biến và toán tử", "summary": "Sử dụng kiểu dữ liệu, biểu thức và toán tử trong Java."},
                {"title": "Phương thức và điều khiển luồng", "summary": "Tổ chức logic bằng method, điều kiện và vòng lặp."},
            ],
        },
        {
            "title": "Java Hướng Đối Tượng",
            "lessons": [
                {"title": "Class và constructor", "summary": "Xây dựng mô hình đối tượng với class và constructor."},
                {"title": "Kế thừa, interface và package", "summary": "Tạo chương trình Java có cấu trúc và dễ mở rộng."},
                {"title": "Collections framework", "summary": "Sử dụng các collection phổ biến để quản lý dữ liệu."},
            ],
        },
        {
            "title": "Ứng Dụng Java",
            "lessons": [
                {"title": "Ngoại lệ và làm việc với tệp", "summary": "Viết chương trình Java an toàn hơn với xử lý lỗi và tệp."},
                {"title": "Tổ chức dự án", "summary": "Sắp xếp mã nguồn và dependency cho dự án Java rõ ràng hơn."},
                {"title": "Dự án nhỏ", "summary": "Thực hiện một dự án Java nhỏ theo mục tiêu học tập."},
            ],
        },
    ],
    "web": [
        {
            "title": "Nền Tảng Web",
            "lessons": [
                {"title": "Web hoạt động như thế nào", "summary": "Hiểu trình duyệt, HTTP và mô hình request-response."},
                {"title": "Cấu trúc HTML", "summary": "Tạo cấu trúc trang có ngữ nghĩa bằng HTML."},
                {"title": "Trình bày với CSS", "summary": "Tạo giao diện, bố cục và hiển thị responsive bằng CSS."},
            ],
        },
        {
            "title": "Web Tương Tác",
            "lessons": [
                {"title": "JavaScript cơ bản", "summary": "Dùng JavaScript để thêm logic và tương tác cho trang web."},
                {"title": "DOM và sự kiện", "summary": "Phản hồi thao tác người dùng và cập nhật giao diện động."},
                {"title": "Làm việc với API", "summary": "Lấy dữ liệu từ backend và hiển thị lên giao diện."},
            ],
        },
        {
            "title": "Phát Triển Web Theo Sản Phẩm",
            "lessons": [
                {"title": "Tổ chức UI và component", "summary": "Chia giao diện thành các phần tái sử dụng và dễ bảo trì."},
                {"title": "Responsive và hiệu năng", "summary": "Cải thiện trải nghiệm đa thiết bị và tối ưu hiệu năng."},
                {"title": "Dự án nhỏ", "summary": "Xây dựng một dự án web nhỏ bám sát mục tiêu học tập."},
            ],
        },
    ],
}


def get_subject_label(subject_id: str) -> Optional[str]:
    """Resolve subject label from fixed catalog, DB catalog, or a humanized fallback."""
    normalized = (subject_id or "").strip().lower()
    if not normalized:
        return None

    fixed = SUBJECT_CATALOG.get(normalized)
    if fixed:
        return fixed

    try:
        db = get_db()
        subject = db.subjects.find_one(
            {
                "$or": [
                    {"slug": normalized},
                    {"subject_id": normalized},
                    {"topic": normalized},
                    {"title": {"$regex": f"^{re.escape(normalized)}$", "$options": "i"}},
                ]
            },
            {"title": 1},
        )
        title = str((subject or {}).get("title") or "").strip()
        if title:
            return title
    except Exception:
        pass

    return re.sub(r"[_\s]+", " ", normalized).strip().title() or None


def _normalize_string_list(value: Any, *, limit: int = 4) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _coerce_difficulty(value: Any, *, default: int = 1) -> int:
    try:
        return max(1, min(int(value), 10))
    except Exception:
        return default


def _coerce_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _canonical_curriculum_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _title_tokens(value: Any) -> List[str]:
    canonical = _canonical_curriculum_text(value)
    return [token for token in canonical.split() if token]


def _is_generic_curriculum_title(value: Any, *, kind: str) -> bool:
    canonical = _canonical_curriculum_text(value)
    tokens = _title_tokens(value)
    if not canonical:
        return True
    if kind == "chapter" and re.fullmatch(r"(chapter|part|module|section)\s+\d+", canonical):
        return True
    banned_exact = {
        "introduction",
        "overview",
        "basics",
        "basic",
        "practice",
        "review",
        "mini project",
        "project",
        "foundation",
        "foundations",
        "advanced",
        "goal application",
        "goal oriented practice",
        "foundational path",
        "core workflows",
    }
    if canonical in banned_exact:
        return True
    generic_tokens = {
        "introduction",
        "overview",
        "basics",
        "basic",
        "practice",
        "review",
        "project",
        "mini",
        "core",
        "advanced",
        "foundation",
        "foundations",
        "goal",
        "application",
        "path",
        "chapter",
        "part",
        "module",
        "section",
    }
    non_generic_tokens = [token for token in tokens if token not in generic_tokens]
    return len(non_generic_tokens) < 1


def _qualify_chapter_title(title: Any, lessons: List[Dict[str, Any]]) -> str:
    normalized_title = str(title or "").strip()
    anchor_title = next(
        (
            str(lesson.get("title") or "").strip()
            for lesson in lessons or []
            if str(lesson.get("title") or "").strip()
        ),
        "",
    )
    if normalized_title and not _is_generic_curriculum_title(normalized_title, kind="chapter"):
        return normalized_title
    if normalized_title and anchor_title:
        canonical_title = _canonical_curriculum_text(normalized_title)
        if re.fullmatch(r"(chapter|part|module|section)\s+\d+", canonical_title):
            return anchor_title
        return f"{normalized_title}: {anchor_title}"
    return anchor_title or normalized_title


def _band_mastery(value: Any) -> str:
    mastery = max(0.0, min(_coerce_float(value, default=0.0), 1.0))
    if mastery < 0.2:
        return "starting_from_scratch"
    if mastery < 0.45:
        return "needs_foundation"
    if mastery < 0.7:
        return "can_build_core_workflows"
    return "ready_for_application"


def _prefers_vietnamese(*texts: Any) -> bool:
    joined = " ".join(str(text or "") for text in texts).strip().lower()
    if not joined:
        return False
    if re.search(r"[ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", joined):
        return True
    vietnamese_markers = {
        "hoc",
        "học",
        "lap",
        "lập",
        "trinh",
        "trình",
        "co",
        "cơ",
        "ban",
        "bản",
        "ung",
        "ứng",
        "dung",
        "dụng",
        "du_an",
        "dự án",
        "muc tieu",
        "mục tiêu",
    }
    return any(marker in joined for marker in vietnamese_markers)


def _band_time_budget(value: Any) -> str:
    minutes = max(0, int(_coerce_float(value, default=0.0)))
    if minutes <= 0:
        return "unknown"
    if minutes < 180:
        return "tight"
    if minutes < 420:
        return "moderate"
    return "ample"


def _subject_key_from_prompt_context(
    subject_label: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    explicit = str((planner_input or {}).get("subject_id") or "").strip().lower()
    if explicit:
        return explicit
    canonical_label = _canonical_curriculum_text(subject_label)
    for key, label in SUBJECT_CATALOG.items():
        if canonical_label == _canonical_curriculum_text(label):
            return key
    for key in SUBJECT_CATALOG:
        if key and key in canonical_label:
            return key
    return canonical_label.split(" ", 1)[0] if canonical_label else ""


def _infer_curriculum_track_key(
    subject_key: str,
    goal: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    normalized_subject = str(subject_key or "").strip().lower()
    goal_text = _canonical_curriculum_text(
        " ".join(
            str(item or "")
            for item in (
                goal,
                (planner_input or {}).get("learning_goal"),
                (planner_input or {}).get("target_outcome"),
                (planner_input or {}).get("target_role"),
            )
        )
    )
    if normalized_subject == "python" and any(
        keyword in goal_text
        for keyword in (
            "backend",
            "api",
            "flask",
            "django",
            "fastapi",
            "http",
            "database",
            "sql",
            "server",
        )
    ):
        return "python_backend"
    return normalized_subject


def _clone_curriculum_seed(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cloned: List[Dict[str, Any]] = []
    for chapter in chapters or []:
        lessons = []
        for lesson in chapter.get("lessons", []) or []:
            lessons.append(
                {
                    "title": str(lesson.get("title") or "").strip(),
                    "summary": str(lesson.get("summary") or "").strip(),
                }
            )
        cloned.append(
            {
                "title": str(chapter.get("title") or "").strip(),
                "lessons": lessons,
            }
        )
    return cloned


def _resolve_curriculum_seed_chapters(
    *,
    subject_key: str,
    goal: str,
    planner_input: Optional[Dict[str, Any]] = None,
    use_vietnamese: bool,
) -> List[Dict[str, Any]]:
    track_key = _infer_curriculum_track_key(subject_key, goal, planner_input)
    golden_catalog = (
        _GOLDEN_CURRICULUM_EXAMPLES_VI if use_vietnamese else _GOLDEN_CURRICULUM_EXAMPLES
    )
    fallback_catalog = _FALLBACK_TEMPLATES_VI if use_vietnamese else _FALLBACK_TEMPLATES
    chapters = (
        golden_catalog.get(track_key)
        or fallback_catalog.get(track_key)
        or fallback_catalog.get(subject_key)
        or []
    )
    return _clone_curriculum_seed(chapters)


def _golden_examples_enabled(planner_input: Optional[Dict[str, Any]] = None) -> bool:
    planner_input = planner_input or {}
    override = planner_input.get("use_golden_examples")
    if isinstance(override, bool):
        return override
    if override is not None:
        return str(override).strip().lower() in {"1", "true", "yes", "on"}
    return LEARNING_PATH_GOLDEN_EXAMPLES_ENABLED


def _build_prompt_reference_example(
    *,
    subject_label: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]],
    shape: str,
    target_chapter_count: Optional[int] = None,
    chapter_index: Optional[int] = None,
) -> str:
    if not _golden_examples_enabled(planner_input):
        return ""
    subject_key = _subject_key_from_prompt_context(subject_label, planner_input)
    if not subject_key:
        return ""
    use_vietnamese = _prefers_vietnamese(
        goal,
        (planner_input or {}).get("learning_goal"),
        (planner_input or {}).get("target_outcome"),
    )
    chapters = build_fallback_curriculum(
        subject_key,
        goal,
        level,
        planner_input=planner_input,
    )
    if not chapters:
        return ""
    if shape == "outline":
        example_payload = {
            "chapters": [
                {
                    "title": str(chapter.get("title") or "").strip(),
                    "focus": str(
                        ((chapter.get("lessons") or [{}])[0].get("summary") or "")
                    ).strip()
                    or str(chapter.get("title") or "").strip(),
                    "lesson_count": len(chapter.get("lessons") or []) or 3,
                }
                for chapter in chapters[: max(1, target_chapter_count or len(chapters))]
            ]
        }
    elif shape == "chapter":
        selected_chapter = chapters[
            min(max(int(chapter_index or 1) - 1, 0), len(chapters) - 1)
        ]
        example_payload = {
            "title": str(selected_chapter.get("title") or "").strip(),
            "lessons": list(selected_chapter.get("lessons") or []),
        }
    else:
        example_payload = {
            "chapters": chapters[: max(1, target_chapter_count or len(chapters))]
        }
    example_json = json.dumps(
        example_payload,
        ensure_ascii=not use_vietnamese,
        separators=(",", ":"),
    )
    return (
        "Reference example quality bar:\n"
        f"{example_json}\n"
        "Use the same level of specificity, pacing, and chapter distinctness, but adapt the content to the learner goal.\n\n"
    )


def _top_diagnostic_gaps(
    diagnostic_scores: Any,
    *,
    limit: int = 4,
) -> List[str]:
    if not isinstance(diagnostic_scores, dict):
        return []
    ranked: List[tuple[float, str]] = []
    for key, value in diagnostic_scores.items():
        label = str(key or "").strip()
        if not label:
            continue
        ranked.append((_coerce_float(value, default=1.0), label))
    ranked.sort(key=lambda item: item[0])
    return [label for _, label in ranked[:limit]]


def _summarize_progress_history(progress_history: Any, *, limit: int = 3) -> List[str]:
    if not isinstance(progress_history, list):
        return []
    summarized: List[str] = []
    for item in progress_history[-limit:]:
        if not isinstance(item, dict):
            continue
        lesson_title = str(item.get("lesson_title") or item.get("title") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        confidence = item.get("confidence")
        if not lesson_title and not status:
            continue
        entry = lesson_title or "recent_lesson"
        if status:
            entry = f"{entry}:{status}"
        if confidence is not None:
            entry = f"{entry}:confidence_{round(_coerce_float(confidence, default=0.0), 2)}"
        summarized.append(entry)
    return summarized


def _build_path_shape_guidance(
    *,
    level: str,
    mastery_band: str,
    goal: str,
) -> Dict[str, Any]:
    normalized_level = str(level or "beginner").strip().lower()
    if normalized_level == "advanced":
        chapter_roles = [
            "advanced_refresh_and_gaps",
            "system_design_or_optimization",
            "goal_specific_delivery",
        ]
    elif normalized_level == "intermediate":
        chapter_roles = [
            "gap_closure",
            "core_problem_solving",
            "goal_specific_application",
        ]
    else:
        chapter_roles = [
            "foundations",
            "core_workflows",
            "goal_application",
        ]
    if mastery_band == "starting_from_scratch":
        chapter_roles[0] = "absolute_foundations"
    return {
        "chapter_roles": chapter_roles,
        "lesson_flow": [
            "bridge_or_core",
            "core_skill",
            "guided_practice_or_workflow",
            "capstone_only_when_earned",
        ],
        "goal_anchor": str(goal or "").strip(),
    }


def _apply_curriculum_defaults(
    chapters: List[Dict[str, Any]],
    *,
    goal: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    weak_concepts = _normalize_string_list(
        (planner_input or {}).get("weak_concepts"),
        limit=3,
    )
    previous_lesson_title = ""
    normalized: List[Dict[str, Any]] = []

    for chapter in chapters or []:
        chapter_title = str(chapter.get("title") or "").strip()
        lessons_out: List[Dict[str, Any]] = []
        for lesson in chapter.get("lessons", []) or []:
            title = str(lesson.get("title") or "").strip()
            summary = str(lesson.get("summary") or "").strip()
            if not title:
                continue

            objectives = _normalize_string_list(lesson.get("objectives"))
            if not objectives:
                objectives = [summary or f"Complete the key outcomes for {title}."]
                if weak_concepts:
                    objectives.append(
                        f"Reinforce {weak_concepts[0]} while progressing toward {goal}."
                    )

            prerequisites = _normalize_string_list(lesson.get("prerequisites"))
            if not prerequisites and previous_lesson_title:
                prerequisites = [previous_lesson_title]

            target_concepts = _normalize_string_list(
                lesson.get("target_concepts"),
                limit=5,
            )
            if not target_concepts:
                target_concepts = [
                    re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "core_concept"
                ]

            prerequisite_concepts = _normalize_string_list(
                lesson.get("prerequisite_concepts"),
                limit=5,
            )

            difficulty = _coerce_difficulty(
                lesson.get("difficulty"),
                default=1 + min(len(normalized) + len(lessons_out), 9),
            )
            lesson_kind = str(lesson.get("lesson_kind") or "core").strip().lower() or "core"

            lessons_out.append(
                {
                    "title": title,
                    "summary": summary or f"Study the key ideas in {title}.",
                    "objectives": objectives[:3],
                    "prerequisites": prerequisites[:3],
                    "target_concepts": target_concepts,
                    "prerequisite_concepts": prerequisite_concepts,
                    "difficulty": difficulty,
                    "lesson_kind": lesson_kind,
                }
            )
            previous_lesson_title = title

        if lessons_out:
            normalized.append(
                {
                    "title": _qualify_chapter_title(chapter_title, lessons_out),
                    "lessons": lessons_out,
                }
            )

    return normalized


def build_learning_path_prompt(
    subject_label: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]] = None,
    target_chapter_count: Optional[int] = None,
) -> str:
    """Build a curriculum-only prompt for the cloud LLM."""
    learner_context = _build_learning_path_learner_context(planner_input)
    planning_guidance = _build_path_shape_guidance(
        level=level,
        mastery_band=str(learner_context.get("mastery_band") or ""),
        goal=goal,
    )
    compact_context = _compact_learning_path_prompt_context(learner_context)
    compact_guidance = _compact_learning_path_prompt_context(planning_guidance)
    chapter_count_instruction = (
        f"- Create exactly {max(2, int(target_chapter_count or 0))} chapters.\n"
        if target_chapter_count is not None
        else (
            "- Decide the number of chapters automatically based on goal scope, learner level, and time budget.\n"
            "- Usually create 3-6 chapters instead of a single oversized chapter.\n"
        )
    )
    reference_example = _build_prompt_reference_example(
        subject_label=subject_label,
        goal=goal,
        level=level,
        planner_input=planner_input,
        shape="curriculum",
        target_chapter_count=target_chapter_count,
    )
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        "Create a concise chapter-and-lesson learning path.\n\n"
        "Requirements:\n"
        "- Align tightly to the goal and learner context.\n"
        "- Sequence lessons by prerequisite concepts from fundamentals to application.\n"
        "- Prefer specific, skill-oriented titles.\n"
        "- Chapter titles must name a concrete topic, workflow, or milestone, not just a phase label.\n"
        "- Each chapter should feel like a distinct phase of progress toward the goal.\n"
        "- Avoid adjacent duplication unless difficulty or application clearly increases.\n"
        f"{chapter_count_instruction}"
        "- Keep each chapter to 2-4 lessons when possible.\n"
        "- Keep every field concise.\n"
        "- Keep summary to one short sentence.\n"
        "- Limit objectives to 2 items, prerequisites to 2 items, concept lists to 3 items.\n"
        "- Use short snake_case ids for target_concepts and prerequisite_concepts.\n"
        "- difficulty must be 1..10 and rise gradually.\n"
        "- lesson_kind must be one of bridge/core/practice/capstone.\n"
        "- Use at most one capstone near the end only if appropriate.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(compact_guidance, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Learner context:\n"
        f"{json.dumps(compact_context, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"{reference_example}"
        "Return valid JSON only:\n"
        '{"chapters":[{"title":"string","lessons":[{"title":"string","summary":"string","objectives":["string"],"prerequisites":["string"],"target_concepts":["string"],"prerequisite_concepts":["string"],"difficulty":1,"lesson_kind":"core"}]}]}\n\n'
        "Do not add markdown fences or explanations."
    )


def build_learning_path_enrichment_prompt(
    subject_label: str,
    goal: str,
    level: str,
    *,
    chapters: List[Dict[str, Any]],
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    learner_context = _build_learning_path_learner_context(planner_input)
    planning_guidance = _build_path_shape_guidance(
        level=level,
        mastery_band=str(learner_context.get("mastery_band") or ""),
        goal=goal,
    )
    compact_context = _compact_learning_path_prompt_context(learner_context)
    compact_guidance = _compact_learning_path_prompt_context(planning_guidance)
    chapter_blueprint = []
    for chapter_index, chapter in enumerate(chapters or [], start=1):
        lesson_blueprint = []
        for lesson_index, lesson in enumerate(chapter.get("lessons") or [], start=1):
            lesson_blueprint.append(
                {
                    "lesson_index": lesson_index,
                    "title": str(lesson.get("title") or "").strip(),
                    "summary": str(lesson.get("summary") or "").strip(),
                    "objectives": _normalize_string_list(
                        lesson.get("objectives"),
                        limit=3,
                    ),
                    "prerequisites": _normalize_string_list(
                        lesson.get("prerequisites"),
                        limit=3,
                    ),
                    "target_concepts": _normalize_string_list(
                        lesson.get("target_concepts"),
                        limit=5,
                    ),
                    "prerequisite_concepts": _normalize_string_list(
                        lesson.get("prerequisite_concepts"),
                        limit=5,
                    ),
                    "difficulty": _coerce_difficulty(lesson.get("difficulty")),
                    "lesson_kind": str(lesson.get("lesson_kind") or "core").strip().lower()
                    or "core",
                }
            )
        chapter_blueprint.append(
            {
                "chapter_index": chapter_index,
                "title": str(chapter.get("title") or "").strip() or f"Chapter {chapter_index}",
                "lessons": lesson_blueprint,
            }
        )
    reference_example = _build_prompt_reference_example(
        subject_label=subject_label,
        goal=goal,
        level=level,
        planner_input=planner_input,
        shape="curriculum",
        target_chapter_count=len(chapter_blueprint) or None,
    )

    return (
        "You are an AI curriculum editor.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        "You are given a deterministic learning-path skeleton that already has the correct chapter and lesson structure.\n"
        "Improve the wording so the path feels smoother and more personalized for the learner.\n\n"
        "Rules:\n"
        "- Keep the exact same number of chapters and lessons.\n"
        "- Keep the same lesson order.\n"
        "- Keep chapter_index and lesson_index aligned with the provided skeleton.\n"
        "- Rewrite titles, summaries, objectives, and prerequisites to be clearer and more goal-oriented.\n"
        "- Do not collapse chapters or add extra lessons.\n"
        "- Preserve target_concepts, prerequisite_concepts, difficulty, and lesson_kind unless a value is obviously missing.\n"
        "- If target_concepts or prerequisite_concepts are already present, keep their ids unchanged.\n"
        "- Keep summaries to one short sentence.\n"
        "- Keep objectives to at most 2 items and prerequisites to at most 2 items.\n"
        "- Titles should be practical and specific, not generic.\n"
        "- Avoid vague standalone titles like Introduction, Overview, Basics, Practice, Review, or Mini Project unless they are qualified by a concrete topic.\n"
        "- Chapter titles should reflect distinct phases of the path and not repeat each other with only small wording changes.\n"
        "- Lesson titles should describe a concrete skill, workflow, or concept outcome.\n"
        "- If a provided title is already specific, improve it lightly instead of replacing it with a broader title.\n"
        "- Return valid JSON only.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(compact_guidance, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Learner context:\n"
        f"{json.dumps(compact_context, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"{reference_example}"
        "Curriculum skeleton to enrich:\n"
        f"{json.dumps({'chapters': chapter_blueprint}, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Return valid JSON only using this shape:\n"
        '{"chapters":[{"title":"string","lessons":[{"title":"string","summary":"string","objectives":["string"],"prerequisites":["string"],"target_concepts":["string"],"prerequisite_concepts":["string"],"difficulty":1,"lesson_kind":"core"}]}]}\n\n'
        "Do not add markdown fences or explanations."
    )


def _build_learning_path_learner_context(
    planner_input: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    planner_input = planner_input or {}
    current_mastery = round(
        max(0.0, min(_coerce_float(planner_input.get("current_mastery"), default=0.0), 1.0)),
        4,
    )
    completion_rate = round(
        max(0.0, min(_coerce_float(planner_input.get("completion_rate"), default=0.0), 1.0)),
        4,
    )
    time_budget_minutes = int(
        max(0.0, _coerce_float(planner_input.get("time_budget_minutes"), default=0.0))
    )
    learner_context = {
        "current_mastery": current_mastery,
        "mastery_band": _band_mastery(current_mastery),
        "weak_concepts": _normalize_string_list(
            planner_input.get("weak_concepts"),
            limit=4,
        ),
        "current_focus_concepts": _normalize_string_list(
            planner_input.get("current_focus_concepts"),
            limit=4,
        ),
        "completion_rate": completion_rate,
        "time_budget_minutes": time_budget_minutes,
        "time_budget_band": _band_time_budget(time_budget_minutes),
        "preferred_resource_type": str(
            planner_input.get("preferred_resource_type") or "mixed"
        ),
        "learning_pace": str(planner_input.get("learning_pace") or "steady"),
        "target_role": planner_input.get("target_role"),
        "target_outcome": planner_input.get("target_outcome"),
        "desired_deadline": planner_input.get("desired_deadline"),
        "prior_knowledge_level": planner_input.get("prior_knowledge_level"),
        "diagnostic_average_score": round(
            max(0.0, min(_coerce_float(planner_input.get("diagnostic_average_score"), default=0.0), 1.0)),
            4,
        ),
        "diagnostic_recommended_level": planner_input.get(
            "diagnostic_recommended_level"
        ),
        "diagnostic_priority_gaps": _top_diagnostic_gaps(
            planner_input.get("diagnostic_scores") or {},
            limit=4,
        ),
        "recent_progress_signals": _summarize_progress_history(
            planner_input.get("progress_history") or [],
            limit=3,
        ),
    }
    return learner_context


def build_learning_path_outline_prompt(
    subject_label: str,
    goal: str,
    level: str,
    *,
    target_chapter_count: int,
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    learner_context = _build_learning_path_learner_context(planner_input)
    planning_guidance = _build_path_shape_guidance(
        level=level,
        mastery_band=str(learner_context.get("mastery_band") or ""),
        goal=goal,
    )
    compact_context = _compact_learning_path_prompt_context(learner_context)
    compact_guidance = _compact_learning_path_prompt_context(planning_guidance)
    reference_example = _build_prompt_reference_example(
        subject_label=subject_label,
        goal=goal,
        level=level,
        planner_input=planner_input,
        shape="outline",
        target_chapter_count=target_chapter_count,
    )
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        f"Create exactly {target_chapter_count} chapter outlines for this learner.\n\n"
        "Requirements:\n"
        "- Align to the goal and learner context.\n"
        "- Sequence chapters from fundamentals to applied outcomes.\n"
        "- Keep titles concise, practical, and non-generic.\n"
        "- Chapter titles must include the concrete topic, workflow, or outcome the learner will cover.\n"
        "- Make each chapter focus distinct.\n"
        "- Return only chapter title, short focus, and lesson_count.\n"
        "- lesson_count must be an integer from 2 to 4.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(compact_guidance, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Learner context:\n"
        f"{json.dumps(compact_context, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"{reference_example}"
        "Return valid JSON only:\n"
        '{"chapters":[{"title":"string","focus":"string","lesson_count":3}]}\n\n'
        "Do not add markdown fences or explanations."
    )


def build_learning_path_chapter_prompt(
    subject_label: str,
    goal: str,
    level: str,
    *,
    chapter_title: str,
    chapter_focus: str,
    chapter_index: int,
    total_chapters: int,
    target_lesson_count: int,
    prior_chapter_titles: Optional[List[str]] = None,
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    learner_context = _build_learning_path_learner_context(planner_input)
    planning_guidance = _build_path_shape_guidance(
        level=level,
        mastery_band=str(learner_context.get("mastery_band") or ""),
        goal=goal,
    )
    compact_context = _compact_learning_path_prompt_context(learner_context)
    compact_guidance = _compact_learning_path_prompt_context(planning_guidance)
    reference_example = _build_prompt_reference_example(
        subject_label=subject_label,
        goal=goal,
        level=level,
        planner_input=planner_input,
        shape="chapter",
        chapter_index=chapter_index,
    )
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n"
        f"Chapter position: {chapter_index} of {total_chapters}\n"
        f"Chapter title: {chapter_title}\n"
        f"Chapter focus: {chapter_focus}\n"
        f"Previous chapters: {json.dumps(prior_chapter_titles or [], ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"Create exactly {target_lesson_count} lessons for this chapter.\n\n"
        "Requirements:\n"
        "- Align lessons to the chapter focus and learner goal.\n"
        "- Sequence from simplest prerequisite to applied practice.\n"
        "- Make titles specific and skill-oriented.\n"
        "- Ensure the lesson set forms one coherent chapter arc, not a loose collection of related topics.\n"
        "- Avoid near-duplicate lessons.\n"
        "- Keep every field concise.\n"
        "- Keep each summary to one short sentence.\n"
        "- Limit objectives to 2 items, prerequisites to 2 items, and concept lists to 3 items.\n"
        "- Use short snake_case concept ids for target_concepts and prerequisite_concepts.\n"
        "- lesson_kind should be one of: bridge, core, practice, capstone.\n"
        "- difficulty must be 1..10 and should rise within the chapter.\n"
        "- prerequisites should refer to prior lesson titles when needed.\n"
        "- Use practice or capstone only when the chapter content has already built enough foundation.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(compact_guidance, ensure_ascii=False, separators=(',', ':'))}\n\n"
        "Learner context:\n"
        f"{json.dumps(compact_context, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"{reference_example}"
        "Return valid JSON only:\n"
        '{"lessons":[{"title":"string","summary":"string","objectives":["string"],"prerequisites":["string"],"target_concepts":["string"],"prerequisite_concepts":["string"],"difficulty":1,"lesson_kind":"core"}]}\n\n'
        "Do not add markdown fences or explanations."
    )


def _compact_learning_path_prompt_context(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = payload or {}
    compact: Dict[str, Any] = {}
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        compact[key] = value
    return compact


def extract_json_object(text: str) -> Optional[str]:
    """Extract a JSON object from raw LLM text."""
    if not text:
        return None
    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if fenced_match:
        return fenced_match.group(1).strip()
    raw_match = re.search(r"\{.*\}", text, re.DOTALL)
    if raw_match:
        return raw_match.group(0).strip()
    return None


def normalize_curriculum(
    payload: Dict[str, Any],
    *,
    goal: Optional[str] = None,
    planner_input: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
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
        lessons: List[Dict[str, Any]] = []
        if isinstance(lessons_payload, list):
            for lesson in lessons_payload:
                lesson_title = str(lesson.get("title") or "").strip()
                summary = str(lesson.get("summary") or "").strip()
                if not lesson_title:
                    continue
                lessons.append(
                    {
                        "title": lesson_title,
                        "summary": summary
                        or f"Study the key ideas in {lesson_title}.",
                        "objectives": _normalize_string_list(
                            lesson.get("objectives")
                        ),
                        "prerequisites": _normalize_string_list(
                            lesson.get("prerequisites")
                        ),
                        "target_concepts": _normalize_string_list(
                            lesson.get("target_concepts"),
                            limit=5,
                        ),
                        "prerequisite_concepts": _normalize_string_list(
                            lesson.get("prerequisite_concepts"),
                            limit=5,
                        ),
                        "difficulty": _coerce_difficulty(lesson.get("difficulty")),
                        "lesson_kind": str(lesson.get("lesson_kind") or "core")
                        .strip()
                        .lower()
                        or "core",
                    }
                )
        if lessons:
            normalized.append({"title": title, "lessons": lessons})

    return _apply_curriculum_defaults(
        normalized,
        goal=str(goal or payload.get("goal") or ""),
        planner_input=planner_input,
    )


def build_fallback_curriculum(
    subject_id: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a deterministic curriculum when the cloud LLM fails."""
    subject_key = (subject_id or "").strip().lower()
    use_vietnamese = _prefers_vietnamese(
        goal,
        (planner_input or {}).get("learning_goal"),
        (planner_input or {}).get("target_outcome"),
    )
    fallback_catalog = _FALLBACK_TEMPLATES_VI if use_vietnamese else _FALLBACK_TEMPLATES
    chapters = _resolve_curriculum_seed_chapters(
        subject_key=subject_key,
        goal=goal,
        planner_input=planner_input,
        use_vietnamese=use_vietnamese,
    )
    if not chapters:
        return _apply_curriculum_defaults(
            [
                {
                    "title": "Lộ Trình Nền Tảng" if use_vietnamese else "Foundational Path",
                    "lessons": [
                        {
                            "title": "Tổng quan môn học" if use_vietnamese else "Subject overview",
                            "summary": (
                                f"Xây dựng bức tranh tổng quan về môn học và mối liên hệ với mục tiêu {goal}."
                                if use_vietnamese
                                else f"Build a clear map of the subject and its connection to {goal}."
                            ),
                        },
                        {
                            "title": "Khái niệm cốt lõi" if use_vietnamese else "Core concepts",
                            "summary": (
                                f"Tập trung vào các khái niệm thiết yếu phù hợp với trình độ {level}."
                                if use_vietnamese
                                else f"Focus on the essential concepts needed for a {level} learner."
                            ),
                        },
                    ],
                },
                {
                    "title": "Thực Hành Theo Mục Tiêu" if use_vietnamese else "Goal-Oriented Practice",
                    "lessons": [
                        {
                            "title": "Áp dụng vào mục tiêu học tập" if use_vietnamese else "Apply the subject to the goal",
                            "summary": (
                                f"Kết nối kiến thức mới trực tiếp với mục tiêu học tập: {goal}."
                                if use_vietnamese
                                else f"Connect new knowledge directly to the learning goal: {goal}."
                            ),
                        },
                        {
                            "title": "Ôn tập và củng cố" if use_vietnamese else "Review and consolidation",
                            "summary": (
                                "Ôn lại các ý chính và chuẩn bị cho giai đoạn học tiếp theo."
                                if use_vietnamese
                                else "Revisit the important ideas and prepare for the next stage."
                            ),
                        },
                    ],
                },
            ],
            goal=goal,
            planner_input=planner_input,
        )

    return _apply_curriculum_defaults(
        chapters,
        goal=goal,
        planner_input=planner_input,
    )
