"""Prompt and fallback helpers for learning-path curriculum generation."""

from __future__ import annotations

import json
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


def _band_mastery(value: Any) -> str:
    mastery = max(0.0, min(_coerce_float(value, default=0.0), 1.0))
    if mastery < 0.2:
        return "starting_from_scratch"
    if mastery < 0.45:
        return "needs_foundation"
    if mastery < 0.7:
        return "can_build_core_workflows"
    return "ready_for_application"


def _band_time_budget(value: Any) -> str:
    minutes = max(0, int(_coerce_float(value, default=0.0)))
    if minutes <= 0:
        return "unknown"
    if minutes < 180:
        return "tight"
    if minutes < 420:
        return "moderate"
    return "ample"


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
            normalized.append({"title": chapter_title, "lessons": lessons_out})

    return normalized


def build_learning_path_prompt(
    subject_label: str,
    goal: str,
    level: str,
    planner_input: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a curriculum-only prompt for the cloud LLM."""
    learner_context = _build_learning_path_learner_context(planner_input)
    planning_guidance = _build_path_shape_guidance(
        level=level,
        mastery_band=str(learner_context.get("mastery_band") or ""),
        goal=goal,
    )
    schema = {
        "chapters": [
            {
                "title": "string",
                "lessons": [
                    {
                        "title": "string",
                        "summary": "string",
                        "objectives": ["string"],
                        "prerequisites": ["string"],
                        "target_concepts": ["string"],
                        "prerequisite_concepts": ["string"],
                        "difficulty": 1,
                        "lesson_kind": "core",
                    }
                ],
            }
        ]
    }
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        "Create a chapter and lesson learning path for this learner.\n\n"
        "Requirements:\n"
        "- Keep the path tightly aligned to the subject and learner goal.\n"
        "- Model the curriculum as a concept prerequisite graph, not just a linear lesson sequence.\n"
        "- Sequence lessons from fundamentals to applied outcomes based on prerequisite concepts.\n"
        "- Adapt the plan using learner context and priority gaps.\n"
        "- Prefer specific, skill-oriented chapter and lesson titles.\n"
        "- Avoid generic titles like Introduction, Overview, Basics, or Final Project unless scoped clearly.\n"
        "- Avoid repeating the same concept across adjacent lessons unless difficulty or application clearly increases.\n"
        "- Each chapter should contain 2 to 4 lessons when possible.\n"
        "- Keep every field concise to reduce output length.\n"
        "- Keep each lesson summary to one short sentence focused on what the learner will be able to do.\n"
        "- Limit objectives to 2 items, prerequisites to 2 items, and concept lists to 3 items.\n"
        "- Use short snake_case concept ids for target_concepts and prerequisite_concepts.\n"
        "- Each lesson must include title, summary, objectives, prerequisites, target_concepts, prerequisite_concepts, difficulty, and lesson_kind.\n"
        "- `target_concepts` are the concepts this lesson teaches.\n"
        "- `prerequisite_concepts` are concept ids that must be mastered before the lesson unlocks.\n"
        "- `difficulty` must be an integer from 1 to 10 and should rise gradually across the path.\n"
        "- `lesson_kind` should be one of: bridge, core, practice, capstone.\n"
        "- Use at most one capstone lesson, and place it near the end of the final chapter only when appropriate.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(planning_guidance, ensure_ascii=False)}\n\n"
        "Learner context:\n"
        f"{json.dumps(learner_context, ensure_ascii=False)}\n\n"
        "Return valid JSON only with this schema:\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
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
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        f"Create exactly {target_chapter_count} chapter outlines for this learner.\n\n"
        "Requirements:\n"
        "- Keep the path aligned to the subject and learner goal.\n"
        "- Sequence chapters from fundamentals to applied outcomes.\n"
        "- Adapt the chapter order using the learner context and priority gaps.\n"
        "- Keep titles concise, practical, and non-generic.\n"
        "- Make each chapter focus distinct.\n"
        "- Return only chapter title, short focus, and lesson_count.\n"
        "- lesson_count must be an integer from 2 to 4.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(planning_guidance, ensure_ascii=False)}\n\n"
        "Learner context:\n"
        f"{json.dumps(learner_context, ensure_ascii=False)}\n\n"
        "Return valid JSON only with this schema:\n"
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
    return (
        "You are an AI curriculum planner.\n\n"
        f"Subject: {subject_label}\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n"
        f"Chapter position: {chapter_index} of {total_chapters}\n"
        f"Chapter title: {chapter_title}\n"
        f"Chapter focus: {chapter_focus}\n"
        f"Previous chapters: {json.dumps(prior_chapter_titles or [], ensure_ascii=False)}\n\n"
        f"Create exactly {target_lesson_count} lessons for this chapter.\n\n"
        "Requirements:\n"
        "- Keep lessons aligned to the chapter focus and learner goal.\n"
        "- Sequence lessons from simplest prerequisite to applied practice.\n"
        "- Make each lesson title specific and skill-oriented, not generic.\n"
        "- Avoid near-duplicate lessons and avoid repeating the same concept without a stronger application reason.\n"
        "- Keep every field concise.\n"
        "- Keep each summary to one short sentence stating the skill or outcome.\n"
        "- Limit objectives to 2 items, prerequisites to 2 items, and concept lists to 3 items.\n"
        "- Use short snake_case concept ids for target_concepts and prerequisite_concepts.\n"
        "- lesson_kind should be one of: bridge, core, practice, capstone.\n"
        "- difficulty must be an integer from 1 to 10 and should rise within the chapter.\n"
        "- prerequisites should refer to prior lesson titles when needed.\n"
        "- Use practice or capstone only when the chapter content has already built enough foundation.\n\n"
        "Planning guidance:\n"
        f"{json.dumps(planning_guidance, ensure_ascii=False)}\n\n"
        "Learner context:\n"
        f"{json.dumps(learner_context, ensure_ascii=False)}\n\n"
        "Return valid JSON only with this schema:\n"
        '{"lessons":[{"title":"string","summary":"string","objectives":["string"],"prerequisites":["string"],"target_concepts":["string"],"prerequisite_concepts":["string"],"difficulty":1,"lesson_kind":"core"}]}\n\n'
        "Do not add markdown fences or explanations."
    )


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
    chapters = _FALLBACK_TEMPLATES.get(subject_key, [])
    if not chapters:
        return _apply_curriculum_defaults(
            [
                {
                    "title": "Foundational Path",
                    "lessons": [
                        {
                            "title": "Subject overview",
                            "summary": f"Build a clear map of the subject and its connection to {goal}.",
                        },
                        {
                            "title": "Core concepts",
                            "summary": f"Focus on the essential concepts needed for a {level} learner.",
                        },
                    ],
                },
                {
                    "title": "Goal-Oriented Practice",
                    "lessons": [
                        {
                            "title": "Apply the subject to the goal",
                            "summary": f"Connect new knowledge directly to the learning goal: {goal}.",
                        },
                        {
                            "title": "Review and consolidation",
                            "summary": "Revisit the important ideas and prepare for the next stage.",
                        },
                    ],
                },
            ],
            goal=goal,
            planner_input=planner_input,
        )

    fallback: List[Dict[str, Any]] = []
    for chapter in chapters:
        lessons = []
        for lesson in chapter["lessons"]:
            lessons.append(
                {
                    "title": lesson["title"],
                    "summary": (
                        f"{lesson['summary']} Goal context: {goal}. "
                        f"Current learner level: {level}."
                    ),
                }
            )
        fallback.append({"title": chapter["title"], "lessons": lessons})

    return _apply_curriculum_defaults(
        fallback,
        goal=goal,
        planner_input=planner_input,
    )
