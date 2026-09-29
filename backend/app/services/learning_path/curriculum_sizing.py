"""Curriculum sizing policy helpers for adaptive learning paths."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple


MIN_CHAPTERS = 4
TARGET_CHAPTERS = 5
MAX_CHAPTERS = 7
LESSONS_PER_CHAPTER_MIN = 2
LESSONS_PER_CHAPTER_MAX = 3
MIN_LESSONS = MIN_CHAPTERS * LESSONS_PER_CHAPTER_MIN
TARGET_LESSONS = TARGET_CHAPTERS * LESSONS_PER_CHAPTER_MAX
MAX_LESSONS = MAX_CHAPTERS * LESSONS_PER_CHAPTER_MAX

_BROAD_GOAL_KEYWORDS = {
    "backend",
    "back end",
    "developer",
    "api",
    "apis",
    "fastapi",
    "django",
    "flask",
    "database",
    "databases",
    "sql",
    "orm",
    "authentication",
    "auth",
    "deployment",
    "server",
    "web backend",
    "fullstack",
    "full stack",
    "master",
    "tro thanh",
    "become",
}

_NARROW_GOAL_KEYWORDS = {
    "loop",
    "loops",
    "for",
    "while",
    "variable",
    "variables",
    "syntax",
    "condition",
    "conditions",
    "if else",
    "function basics",
    "vong lap",
    "bien",
}

_SUBJECT_COMPLEXITY = {
    "python": 1.0,
    "web": 1.05,
    "java": 1.1,
    "csharp": 1.1,
    "cpp": 1.15,
}

_MONGO_OBJECT_ID_RE = re.compile(r"^[a-f0-9]{24}$", re.IGNORECASE)


def _canonical_text(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9#+.]+", " ", text.lower()).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        number = float(value)
    except Exception:
        return default
    if not math.isfinite(number):
        return default
    return int(number)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    return number if math.isfinite(number) else default


def _clamp_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    number = _safe_int(value, default)
    return max(minimum, min(maximum, number))


def _lesson_count(chapters: List[Dict[str, Any]]) -> int:
    return sum(len(chapter.get("lessons", []) or []) for chapter in chapters or [])


def estimate_curriculum_scope(
    *,
    subject_id: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Estimate whether the goal is narrow, standard, or comprehensive."""
    planner_input = planner_input or {}
    explicit_goal = _canonical_text(goal)
    if explicit_goal:
        canonical_goal = explicit_goal
    else:
        canonical_goal = _canonical_text(
            " ".join(
                str(item or "")
                for item in (
                    planner_input.get("learning_goal"),
                    planner_input.get("target_outcome"),
                    planner_input.get("target_role"),
                )
            )
        )
    tokens = canonical_goal.split()
    broad_hits = sorted(
        keyword for keyword in _BROAD_GOAL_KEYWORDS if keyword in canonical_goal
    )
    narrow_hits = sorted(
        keyword for keyword in _NARROW_GOAL_KEYWORDS if keyword in canonical_goal
    )
    subject_complexity = _SUBJECT_COMPLEXITY.get(str(subject_id or "").lower(), 1.0)
    level_key = str(level or "beginner").lower()
    mastery = 0.0
    learner_model = planner_input.get("learner_model")
    if isinstance(learner_model, dict):
        mastery = max(
            0.0,
            min(_safe_float(learner_model.get("current_mastery"), 0.0), 1.0),
        )
    goal_width_score = min(1.0, len(tokens) / 10.0)
    score = (
        0.45 * min(1.0, len(broad_hits) / 3.0)
        + 0.2 * goal_width_score
        + 0.15 * max(0.0, subject_complexity - 0.9)
        + (0.15 if level_key == "beginner" and broad_hits else 0.0)
        - (0.2 if narrow_hits and len(tokens) <= 8 else 0.0)
        - (0.15 if mastery >= 0.75 else 0.0)
    )
    if broad_hits and ("backend" in canonical_goal or "api" in canonical_goal):
        scope = "comprehensive"
    elif score >= 0.55:
        scope = "comprehensive"
    elif narrow_hits and len(tokens) <= 8 and not broad_hits:
        scope = "narrow"
    else:
        scope = "standard"
    return {
        "goal_scope": scope,
        "broad_goal": scope == "comprehensive",
        "broad_hits": broad_hits,
        "narrow_hits": narrow_hits,
        "subject_complexity": subject_complexity,
        "scope_score": round(score, 4),
    }


def resolve_curriculum_size_policy(
    *,
    subject_id: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]] = None,
    curriculum_depth: Optional[str] = None,
    target_chapter_count: Optional[int] = None,
    target_lesson_count: Optional[int] = None,
    resource_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Resolve the fixed, quality-optimized curriculum size envelope."""
    planner_input = planner_input or {}
    scope = estimate_curriculum_scope(
        subject_id=subject_id,
        goal=goal,
        level=level,
        planner_input=planner_input,
    )
    min_chapters = MIN_CHAPTERS
    target_chapters = TARGET_CHAPTERS
    max_chapters = MAX_CHAPTERS
    lessons_per_chapter_min = LESSONS_PER_CHAPTER_MIN
    lessons_per_chapter_max = LESSONS_PER_CHAPTER_MAX
    min_lessons = MIN_LESSONS
    target_lessons = TARGET_LESSONS
    max_lessons = MAX_LESSONS

    time_budget = _safe_int(planner_input.get("time_budget_minutes"), 0)
    if resource_count is None and planner_input.get("resource_count") is not None:
        resource_count = _safe_int(planner_input.get("resource_count"), 0)

    explicit_chapters = target_chapter_count
    if explicit_chapters is None:
        explicit_chapters = planner_input.get("target_chapter_count")
    explicit_lessons = target_lesson_count
    if explicit_lessons is None:
        explicit_lessons = planner_input.get("target_lesson_count")
    if explicit_chapters is not None:
        target_chapters = _clamp_int(
            explicit_chapters,
            min_chapters,
            max_chapters,
            target_chapters,
        )
        max_chapters = max(max_chapters, target_chapters)
    if explicit_lessons is not None:
        target_lessons = _clamp_int(
            explicit_lessons,
            min_lessons,
            max_lessons,
            target_lessons,
        )
        max_lessons = max(max_lessons, target_lessons)

    max_chapters = min(MAX_CHAPTERS, max(max_chapters, min_chapters, target_chapters))
    max_lessons = min(MAX_LESSONS, max(max_lessons, min_lessons, target_lessons))
    target_chapters = max(min_chapters, min(max_chapters, target_chapters))
    target_lessons = max(min_lessons, min(max_lessons, target_lessons))
    target_lessons = max(
        target_lessons,
        target_chapters * lessons_per_chapter_min,
    )
    target_lessons = min(max_lessons, target_lessons)

    sizing_reason = (
        f"{scope['goal_scope']}_goal:{','.join(scope['broad_hits'] or scope['narrow_hits'] or ['general'])};"
        f"level:{level or 'beginner'};time_budget:{time_budget or 'unknown'}"
    )
    if resource_count is not None:
        sizing_reason += f";resources:{resource_count}"

    return {
        **scope,
        "curriculum_depth": "quality_optimized",
        "min_chapters": min_chapters,
        "target_chapters": target_chapters,
        "max_chapters": max_chapters,
        "min_lessons": min_lessons,
        "target_lessons": target_lessons,
        "max_lessons": max_lessons,
        "lessons_per_chapter_min": lessons_per_chapter_min,
        "lessons_per_chapter_max": lessons_per_chapter_max,
        "lessons_per_chapter_range": [
            lessons_per_chapter_min,
            lessons_per_chapter_max,
        ],
        "sizing_reason": sizing_reason,
    }


def curriculum_size_metadata(
    *,
    policy: Dict[str, Any],
    chapters: List[Dict[str, Any]],
    repaired: bool = False,
) -> Dict[str, Any]:
    actual_chapters = len(chapters or [])
    actual_lessons = _lesson_count(chapters)
    under_generated = (
        actual_chapters < int(policy.get("min_chapters") or 0)
        or actual_lessons < int(policy.get("min_lessons") or 0)
    )
    return {
        "curriculum_depth": policy.get("curriculum_depth"),
        "goal_scope": policy.get("goal_scope"),
        "min_chapters": int(policy.get("min_chapters") or 0),
        "target_chapters": int(policy.get("target_chapters") or 0),
        "max_chapters": int(policy.get("max_chapters") or 0),
        "actual_chapters": actual_chapters,
        "min_lessons": int(policy.get("min_lessons") or 0),
        "target_lessons": int(policy.get("target_lessons") or 0),
        "max_lessons": int(policy.get("max_lessons") or 0),
        "actual_lessons": actual_lessons,
        "lessons_per_chapter_range": list(
            policy.get("lessons_per_chapter_range") or [2, 4]
        ),
        "sizing_reason": policy.get("sizing_reason"),
        "repaired": bool(repaired),
        "under_generated": bool(under_generated),
    }


def normalize_curriculum_size(
    chapters: List[Dict[str, Any]],
    *,
    policy: Dict[str, Any],
    subject_id: str,
    goal: str,
    level: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Expand a curriculum to satisfy the selected policy without exceeding caps."""
    before = curriculum_size_metadata(policy=policy, chapters=chapters, repaired=False)
    needs_expand = before["under_generated"]
    expanded = expand_curriculum_to_policy(
        chapters=chapters,
        policy=policy,
        subject_id=subject_id,
        goal=goal,
        level=level,
    ) if needs_expand else _trim_to_policy(chapters, policy)
    after = curriculum_size_metadata(
        policy=policy,
        chapters=expanded,
        repaired=needs_expand,
    )
    return expanded, after


def expand_curriculum_to_policy(
    *,
    chapters: List[Dict[str, Any]],
    policy: Dict[str, Any],
    subject_id: str,
    goal: str,
    level: str,
) -> List[Dict[str, Any]]:
    min_chapters = int(policy.get("min_chapters") or 2)
    target_chapters = int(policy.get("target_chapters") or min_chapters)
    max_chapters = int(policy.get("max_chapters") or MAX_CHAPTERS)
    min_lessons = int(policy.get("min_lessons") or 5)
    target_lessons = int(policy.get("target_lessons") or min_lessons)
    max_lessons = int(policy.get("max_lessons") or MAX_LESSONS)
    lpc_min = int(policy.get("lessons_per_chapter_min") or 2)
    lpc_max = int(policy.get("lessons_per_chapter_max") or 4)

    result = _dedupe_curriculum(chapters)
    templates = _template_chapters(subject_id=subject_id, goal=goal, level=level)
    template_cursor = max(0, len(result) - 1) % max(1, len(templates))
    while len(result) < min(target_chapters, max_chapters):
        template = templates[template_cursor % len(templates)]
        template_cursor += 1
        if _contains_chapter(result, template["title"]):
            continue
        result.append(_clone_chapter(template, lesson_limit=lpc_max))
        if template_cursor > len(templates) + max_chapters:
            break

    result = _ensure_lessons_per_chapter(
        result,
        templates=templates,
        lpc_min=lpc_min,
        lpc_max=lpc_max,
        max_lessons=max_lessons,
    )
    while _lesson_count(result) < min(target_lessons, max_lessons):
        changed = False
        for chapter_index, chapter in enumerate(result):
            if _lesson_count(result) >= min(target_lessons, max_lessons):
                break
            lessons = chapter.setdefault("lessons", [])
            if len(lessons) >= lpc_max:
                continue
            extra = _make_extension_lesson(
                chapter_title=str(chapter.get("title") or f"Chapter {chapter_index + 1}"),
                index=len(lessons) + 1,
                goal=goal,
                level=level,
            )
            if not _contains_lesson(result, extra["title"]):
                lessons.append(extra)
                changed = True
        if changed:
            continue
        if len(result) >= max_chapters:
            break
        template = templates[template_cursor % len(templates)]
        template_cursor += 1
        title = template["title"]
        if _contains_chapter(result, title):
            title = f"{title} Practice"
        result.append(_clone_chapter({**template, "title": title}, lesson_limit=lpc_max))

    return _trim_to_policy(result, policy)


def _trim_to_policy(
    chapters: List[Dict[str, Any]],
    policy: Dict[str, Any],
) -> List[Dict[str, Any]]:
    max_chapters = int(policy.get("max_chapters") or MAX_CHAPTERS)
    max_lessons = int(policy.get("max_lessons") or MAX_LESSONS)
    result: List[Dict[str, Any]] = []
    total = 0
    for chapter in _dedupe_curriculum(chapters)[:max_chapters]:
        lessons = []
        for lesson in chapter.get("lessons", []) or []:
            if total >= max_lessons:
                break
            lessons.append(lesson)
            total += 1
        if lessons:
            result.append({**chapter, "lessons": lessons})
    return result


def _template_chapters(*, subject_id: str, goal: str, level: str) -> List[Dict[str, Any]]:
    canonical = _canonical_text(f"{subject_id} {goal}")
    if "python" in canonical and ("backend" in canonical or "api" in canonical):
        return [
            _chapter("Python Foundations", ["Syntax, variables, and data types", "Conditionals and loops", "Functions and error handling"]),
            _chapter("Python Data and Modules", ["Lists, tuples, dictionaries, and sets", "File I/O and JSON", "Modules, packages, and virtual environments"]),
            _chapter("Backend and HTTP Foundations", ["Client-server architecture", "HTTP requests, responses, and status codes", "REST API design basics"]),
            _chapter("Building APIs with FastAPI", ["FastAPI project setup and routing", "Request and response schemas with Pydantic", "Validation and structured error handling"]),
            _chapter("Database Integration", ["SQL and relational data modeling basics", "Connecting Python APIs to a database", "CRUD workflows and ORM fundamentals"]),
            _chapter("Production Backend Practices", ["Authentication and authorization basics", "Testing API endpoints", "Logging, configuration, and deployment basics"]),
            _chapter("Backend Project Integration", ["Design a small backend service", "Connect API, database, and validation layers", "Refactor and document the backend project"]),
            _chapter("Adaptive Review and Assessment", ["Review weak backend concepts", "Practice API and database troubleshooting", "Final backend checkpoint quiz"]),
        ]
    subject = _display_subject_name(subject_id=subject_id, goal=goal)
    return [
        _chapter(f"{subject} Foundations", ["Core vocabulary and setup", "Essential syntax and concepts", "Guided foundation practice"]),
        _chapter(f"{subject} Core Skills", ["Primary workflows", "Common patterns", "Error handling and debugging"]),
        _chapter(f"{subject} Data and Structure", ["Data modeling basics", "Organizing project files", "Working with external inputs"]),
        _chapter(f"{subject} Applied Workflows", ["Build a goal-specific workflow", "Integrate multiple concepts", "Practice realistic tasks"]),
        _chapter(f"{subject} Quality and Review", ["Test the solution", "Review weak concepts", "Prepare the final checkpoint"]),
        _chapter(f"{subject} Goal Project", ["Plan the capstone", "Implement the capstone", "Reflect and next steps"]),
    ]


def _display_subject_name(*, subject_id: str, goal: str) -> str:
    canonical = _canonical_text(f"{subject_id} {goal}")
    known_subjects = {
        "python": "Python",
        "cpp": "C++",
        "csharp": "C#",
        "java": "Java",
        "web": "Web",
    }
    for key, label in known_subjects.items():
        if key in canonical:
            return label
    raw_subject = str(subject_id or "").strip()
    if not raw_subject or _MONGO_OBJECT_ID_RE.fullmatch(raw_subject):
        return "Subject"
    return raw_subject.title()


def _chapter(title: str, lesson_titles: List[str]) -> Dict[str, Any]:
    return {
        "title": title,
        "lessons": [
            _lesson(title=lesson_title, chapter_title=title, index=index)
            for index, lesson_title in enumerate(lesson_titles, start=1)
        ],
    }


def _lesson(*, title: str, chapter_title: str, index: int) -> Dict[str, Any]:
    concept = _canonical_text(title).replace(" ", "_") or "core_concept"
    prerequisite = _canonical_text(chapter_title).replace(" ", "_") or "foundation"
    return {
        "title": title,
        "summary": f"Build practical understanding of {title.lower()}.",
        "objectives": [f"Explain {title.lower()}", f"Apply it in a small task"],
        "prerequisites": [] if index == 1 else [f"Previous {chapter_title} lesson"],
        "target_concepts": [concept],
        "prerequisite_concepts": [] if index == 1 else [prerequisite],
        "difficulty": max(1, min(10, index)),
        "estimated_minutes": 25,
        "lesson_kind": "practice" if index >= 3 else "core",
        "reason": f"This lesson supports the {chapter_title} stage of the path.",
    }


def _make_extension_lesson(
    *,
    chapter_title: str,
    index: int,
    goal: str,
    level: str,
) -> Dict[str, Any]:
    suffixes = ["Guided Practice", "Review Checkpoint", "Applied Mini Task", "Troubleshooting"]
    suffix = suffixes[(index - 1) % len(suffixes)]
    title = f"{chapter_title} {suffix}"
    lesson = _lesson(title=title, chapter_title=chapter_title, index=index)
    lesson["summary"] = f"Practice {chapter_title.lower()} in the context of {goal}."
    lesson["lesson_kind"] = "practice" if suffix != "Review Checkpoint" else "bridge"
    lesson["difficulty"] = max(1, min(10, index + (1 if level == "advanced" else 0)))
    return lesson


def _dedupe_curriculum(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    chapter_keys: set[str] = set()
    lesson_keys: set[str] = set()
    for chapter in chapters or []:
        title = str(chapter.get("title") or "").strip()
        key = _canonical_text(title)
        if not title or key in chapter_keys:
            continue
        chapter_keys.add(key)
        lessons = []
        for lesson in chapter.get("lessons", []) or []:
            lesson_title = str(lesson.get("title") or "").strip()
            lesson_key = _canonical_text(lesson_title)
            if not lesson_title or lesson_key in lesson_keys:
                continue
            lesson_keys.add(lesson_key)
            lessons.append(dict(lesson))
        if lessons:
            result.append({**chapter, "title": title, "lessons": lessons})
    return result


def _clone_chapter(chapter: Dict[str, Any], *, lesson_limit: int) -> Dict[str, Any]:
    lessons = [dict(lesson) for lesson in (chapter.get("lessons") or [])[:lesson_limit]]
    return {"title": str(chapter.get("title") or "").strip(), "lessons": lessons}


def _contains_chapter(chapters: List[Dict[str, Any]], title: str) -> bool:
    key = _canonical_text(title)
    return any(_canonical_text(chapter.get("title")) == key for chapter in chapters or [])


def _contains_lesson(chapters: List[Dict[str, Any]], title: str) -> bool:
    key = _canonical_text(title)
    return any(
        _canonical_text(lesson.get("title")) == key
        for chapter in chapters or []
        for lesson in chapter.get("lessons", []) or []
    )


def _ensure_lessons_per_chapter(
    chapters: List[Dict[str, Any]],
    *,
    templates: List[Dict[str, Any]],
    lpc_min: int,
    lpc_max: int,
    max_lessons: int,
) -> List[Dict[str, Any]]:
    for chapter_index, chapter in enumerate(chapters):
        lessons = chapter.setdefault("lessons", [])
        template = templates[chapter_index % len(templates)]
        for lesson in template.get("lessons", []) or []:
            if len(lessons) >= lpc_min or _lesson_count(chapters) >= max_lessons:
                break
            if not _contains_lesson(chapters, lesson.get("title")):
                lessons.append(dict(lesson))
        while len(lessons) < lpc_min and _lesson_count(chapters) < max_lessons:
            extra = _make_extension_lesson(
                chapter_title=str(chapter.get("title") or f"Chapter {chapter_index + 1}"),
                index=len(lessons) + 1,
                goal=str(chapter.get("title") or ""),
                level="beginner",
            )
            if _contains_lesson(chapters, extra["title"]):
                break
            lessons.append(extra)
        if len(lessons) > lpc_max:
            chapter["lessons"] = lessons[:lpc_max]
    return chapters
