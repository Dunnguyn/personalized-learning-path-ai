from datetime import datetime
from typing import Dict, Set, List, Optional
import logging
import uuid
import os
from functools import lru_cache
import json
import re
import time

from backend.app.database.mongo import get_db
from backend.app.services.learning_path.recommender import (
    recommend_resources_for_concept,
)
from backend.app.services.progress_tracking.progress import get_progress
from backend.app.services.adaptive_engine import (
    decide_learning_mode,
    filter_resources_by_mode,
    can_unlock_next_concept,
    LearningMode,
)
import backend.app.services.ai_tutor.rag as rag_service
from backend.app.services.ai_tutor.rag import RAGPipeline, USE_LLM

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# =====================================================
# CONFIG
# =====================================================
LEVEL_FACTOR = {
    "beginner": 1.2,
    "intermediate": 1.0,
    "advanced": 0.8,
}

MAX_RECOMMENDATIONS = int(os.getenv("MAX_LEARNING_PATH_RECS", "15"))
MASTERY_THRESHOLD_DEFAULT = 0.8
MAX_CYCLE_DETECTION_DEPTH = 100  # Prevent infinite loops

logger.info(f"Learning path service initialized: max_recs={MAX_RECOMMENDATIONS}")

_curriculum_rag = RAGPipeline()
CURRICULUM_MAX_OUTPUT_TOKENS = int(
    os.getenv("LEARNING_PATH_CURRICULUM_MAX_OUTPUT_TOKENS", "4096")
)
CURRICULUM_PARSE_RETRIES = int(os.getenv("LEARNING_PATH_CURRICULUM_PARSE_RETRIES", "2"))


def _get_learning_path_llm_status() -> Dict[str, Optional[object]]:
    cooldown_active = time.time() < getattr(rag_service, "LLM_COOLDOWN_UNTIL", 0.0)
    return {
        "provider": "gemini",
        "enabled": bool(
            rag_service.USE_LLM
            and getattr(rag_service, "client", None)
            and not cooldown_active
            and not getattr(rag_service, "LLM_DISABLED_REASON", None)
        ),
        "cooldown_active": cooldown_active,
        "reason": getattr(rag_service, "LLM_DISABLED_REASON", None),
        "model": getattr(rag_service, "PRIMARY_MODEL", None),
    }


# =====================================================
# CYCLE DETECTION (for safer topological sort)
# =====================================================
def _has_cycle(graph: Dict[int, Set[int]]) -> bool:
    """
    Simple cycle detection using DFS.
    Returns True if graph has cycle.

    Args:
        graph: Dict mapping concept_id → Set of prerequisite concept_ids

    Returns:
        True if cycle detected, False otherwise
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in graph}

    def visit(node: int, depth: int = 0) -> bool:
        if depth > MAX_CYCLE_DETECTION_DEPTH:
            logger.warning("Cycle detection depth exceeded; assuming cycle exists")
            return True

        if color[node] == GRAY:
            return True  # Back edge = cycle
        if color[node] == BLACK:
            return False

        color[node] = GRAY
        for neighbor in graph.get(node, []):
            if visit(neighbor, depth + 1):
                return True
        color[node] = BLACK
        return False

    for node in graph:
        if color[node] == WHITE:
            if visit(node):
                return True
    return False


# =====================================================
# TOPOLOGICAL SORT (with cycle detection)
# =====================================================
def _topological_sort(graph: Dict[int, Set[int]]) -> List[int]:
    """
    Topological sort using DFS.
    If cycle detected, return nodes in arbitrary order.

    Args:
        graph: Dict mapping concept_id → Set of prerequisite concept_ids

    Returns:
        List of concept_ids in topological order
    """
    if _has_cycle(graph):
        logger.warning(
            "Cycle detected in prerequisite graph; returning arbitrary order"
        )
        return list(graph.keys())

    visited = set()
    ordered = []

    def dfs(node: int, depth: int = 0):
        if depth > MAX_CYCLE_DETECTION_DEPTH:
            logger.warning("DFS depth exceeded")
            return

        if node in visited:
            return

        visited.add(node)
        for prereq in graph.get(node, []):
            dfs(prereq, depth + 1)
        ordered.append(node)

    for node in graph:
        if node not in visited:
            dfs(node)

    return ordered


# =====================================================
# MAIN FUNCTION: GENERATE LEARNING PATH
# =====================================================
def _extract_json_block(text: str) -> Optional[str]:
    if not text:
        return None

    fenced_match = re.search(
        r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL | re.IGNORECASE
    )
    if fenced_match:
        return fenced_match.group(1).strip()

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return match.group(0)

    return None


def _build_curriculum_prompt(goal: str, level: str, resources: List[Dict]) -> str:
    resource_lines = []
    for idx, resource in enumerate(resources, start=1):
        title = resource.get("title") or "Unknown"
        snippet = (resource.get("snippet") or "").strip()
        if len(snippet) > 200:
            snippet = snippet[:200].rstrip() + "..."
        resource_lines.append(f"- {idx}. {title}: {snippet}")

    materials = "\n".join(resource_lines) or "- No learning materials available."

    return (
        "You are an AI curriculum designer.\n"
        "Create a step-by-step learning path with chapters and lessons for the given goal.\n"
        "Make it suitable for the learner level and grounded in the provided materials.\n"
        "Return strictly valid JSON only. Do not wrap JSON in markdown fences.\n"
        "Every chapter must contain at least 2 lessons when possible.\n"
        "Return ONLY valid JSON in this schema:\n"
        '{"chapters":[{"title":string,"lessons":[{"title":string,"summary":string,"resources":[string]}]}]}\n'
        "No extra commentary.\n\n"
        f"Goal: {goal}\n"
        f"Level: {level}\n\n"
        "Materials:\n"
        f"{materials}\n"
    )


def _add_lesson_ids(chapters: List[Dict]) -> List[Dict]:
    for chapter in chapters:
        if not chapter.get("chapter_id"):
            chapter["chapter_id"] = uuid.uuid4().hex
        lessons = chapter.get("lessons", [])
        for lesson in lessons:
            if not lesson.get("lesson_id"):
                lesson["lesson_id"] = uuid.uuid4().hex
    return chapters


def _build_goal_seed_concepts(goal: str, level: str) -> List[Dict]:
    normalized_goal = (goal or "").strip()
    lower_goal = normalized_goal.lower()

    tracks: List[tuple[str, List[str]]] = [
        (
            "python_backend",
            [
                "Gioi thieu Python",
                "Kieu du lieu va bien",
                "Cau truc dieu khien",
                "Ham va module",
                "Lap trinh huong doi tuong",
                "HTTP co ban",
                "REST API",
                "FastAPI co ban",
                "Ket noi MongoDB",
            ],
        ),
        (
            "frontend_web",
            [
                "Nen tang HTML CSS",
                "JavaScript co ban",
                "TypeScript co ban",
                "React component",
                "State va props",
                "Routing frontend",
                "Goi API",
                "Quan ly state",
                "Toi uu giao dien",
            ],
        ),
        (
            "data_python",
            [
                "Python cho du lieu",
                "NumPy co ban",
                "Pandas co ban",
                "Lam sach du lieu",
                "Truc quan du lieu",
                "Thong ke mo ta",
                "Feature engineering",
                "Mo hinh co ban",
                "Danh gia mo hinh",
            ],
        ),
    ]

    matched_concepts: List[str] = []
    if "python" in lower_goal and "backend" in lower_goal:
        matched_concepts.extend(dict(tracks)["python_backend"])
    elif "react" in lower_goal or "frontend" in lower_goal or "web" in lower_goal:
        matched_concepts.extend(dict(tracks)["frontend_web"])
    elif (
        "data" in lower_goal
        or "machine learning" in lower_goal
        or "phan tich" in lower_goal
    ):
        matched_concepts.extend(dict(tracks)["data_python"])

    if not matched_concepts:
        goal_tokens = [
            token.capitalize()
            for token in re.findall(r"[a-zA-Z0-9]+", normalized_goal)[:5]
        ]
        matched_concepts = [
            f"Tong quan ve {normalized_goal or 'chu de hoc tap'}",
            f"Khai niem cot loi cua {goal_tokens[0] if goal_tokens else 'chu de'}",
            f"Thuc hanh co ban",
            f"Ung dung thuc te",
            f"Mo rong va tong ket",
        ]

    level_tail = {
        "beginner": ["Bai tap nhap mon", "Tong ket co ban"],
        "intermediate": ["Thuc hanh nang cao", "Du an nho"],
        "advanced": ["Kien truc he thong", "Toi uu va mo rong"],
    }.get(level, ["Tong ket va on tap"])

    full_list = matched_concepts + level_tail

    unique: List[Dict] = []
    seen = set()
    for index, name in enumerate(full_list, start=1):
        clean_name = str(name).strip()
        if not clean_name:
            continue
        key = clean_name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(
            {
                "concept_id": 900000 + index,
                "concept_name": clean_name,
                "difficulty": min(10, max(1, 2 + (index // 2))),
                "bloom_level": "understand" if index <= 3 else "apply",
                "mode": "normal",
                "priority_score": round(max(0.5, 1.0 - (index * 0.03)), 2),
                "resources": [],
            }
        )

    return unique[:MAX_RECOMMENDATIONS]


def _build_recommended_from_curriculum(
    curriculum: List[Dict], default_mode: str = "normal"
) -> List[Dict]:
    recommended: List[Dict] = []
    sequence = 1

    for chapter in curriculum or []:
        for lesson in chapter.get("lessons", []) or []:
            concept_name = (
                lesson.get("concept_name")
                or lesson.get("title")
                or f"Lesson {sequence}"
            )
            resources = [
                {"title": title}
                for title in (lesson.get("resources") or [])
                if isinstance(title, str) and title.strip()
            ]
            recommended.append(
                {
                    "concept_id": 950000 + sequence,
                    "concept_name": str(concept_name),
                    "difficulty": min(10, max(1, 2 + (sequence // 2))),
                    "bloom_level": "understand" if sequence <= 3 else "apply",
                    "mode": default_mode,
                    "priority_score": round(max(0.5, 1.0 - (sequence * 0.03)), 2),
                    "resources": resources,
                }
            )
            sequence += 1

    return recommended[:MAX_RECOMMENDATIONS]


def _call_curriculum_llm(prompt: str) -> Optional[str]:
    client = getattr(rag_service, "client", None)
    if not (rag_service.USE_LLM and client):
        return None

    try:
        if hasattr(client, "models") and hasattr(client.models, "generate_content"):
            response = client.models.generate_content(
                model=getattr(rag_service, "PRIMARY_MODEL", None),
                contents=prompt,
                config={
                    "temperature": 0.2,
                    "max_output_tokens": CURRICULUM_MAX_OUTPUT_TOKENS,
                    "response_mime_type": "application/json",
                },
            )
            return _curriculum_rag._extract_text_from_response(response)
    except Exception as e:
        logger.warning(
            f"Structured curriculum generation failed, falling back to shared retry path: {e}"
        )

    return _curriculum_rag._call_llm_with_retry(prompt)


def _build_curriculum_from_recommended(
    recommended: List[Dict], level: str
) -> List[Dict]:
    chapters: List[Dict] = []
    if not recommended:
        return chapters

    chunk_size = 3
    for idx in range(0, len(recommended), chunk_size):
        chunk = recommended[idx : idx + chunk_size]
        chapter_id = uuid.uuid4().hex
        chapter_concepts = []
        lessons = []
        for item in chunk:
            concept_name = item.get("concept_name") or "Bai hoc"
            concept_id = item.get("concept_id") or concept_name
            lesson_resources = [
                r.get("title") for r in item.get("resources", []) if r.get("title")
            ]
            chapter_concepts.append(
                {
                    "id": str(concept_id),
                    "name": str(concept_name),
                }
            )
            lessons.append(
                {
                    "lesson_id": uuid.uuid4().hex,
                    "title": concept_name,
                    "summary": f"Hoc va luyen tap noi dung cot loi cua {concept_name} cho muc {level}.",
                    "resources": lesson_resources,
                    "concept_id": str(concept_id),
                    "concept_name": str(concept_name),
                    "concept_list": [
                        {"id": str(concept_id), "name": str(concept_name)}
                    ],
                }
            )
        for lesson in lessons:
            lesson["concept_list"] = [dict(item) for item in chapter_concepts]
        chapters.append(
            {
                "chapter_id": chapter_id,
                "title": f"Chuong {len(chapters) + 1}",
                "concepts": chapter_concepts,
                "lessons": lessons,
            }
        )
    return chapters


def _generate_curriculum(goal: str, level: str, recommended: List[Dict]) -> Dict:
    llm_status = _get_learning_path_llm_status()
    fallback_notice = "AI tạm thời chưa sẵn sàng, hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể bắt đầu học."
    if not (USE_LLM and _curriculum_rag):
        return {
            "curriculum": _build_curriculum_from_recommended(recommended, level),
            "source": "fallback",
            "notice": fallback_notice,
            "llm_status": llm_status,
        }

    try:
        resources = _curriculum_rag.retrieve_context(
            query=goal, goal=goal, level=level, k=6
        )
        prompt = _build_curriculum_prompt(goal, level, resources)
        data = None
        parse_error: Optional[Exception] = None

        for attempt in range(max(1, CURRICULUM_PARSE_RETRIES)):
            response_text = _call_curriculum_llm(prompt)
            json_text = _extract_json_block(response_text or "")
            if not json_text:
                parse_error = ValueError("No JSON block returned by curriculum model")
                continue
            try:
                data = json.loads(json_text)
                break
            except json.JSONDecodeError as e:
                parse_error = e
                logger.warning(
                    "Curriculum JSON parse failed on attempt %s/%s: %s",
                    attempt + 1,
                    max(1, CURRICULUM_PARSE_RETRIES),
                    e,
                )

        if data is None:
            logger.warning("Curriculum model returned unusable JSON: %s", parse_error)
            return {
                "curriculum": _build_curriculum_from_recommended(recommended, level),
                "source": "fallback",
                "notice": "AI không trả về nội dung hợp lệ, hệ thống đã dùng lộ trình dự phòng.",
                "llm_status": _get_learning_path_llm_status(),
            }

        chapters = data.get("chapters") if isinstance(data, dict) else None
        if not chapters or not isinstance(chapters, list):
            return {
                "curriculum": _build_curriculum_from_recommended(recommended, level),
                "source": "fallback",
                "notice": "AI trả về dữ liệu chưa đúng định dạng, hệ thống đã dùng lộ trình dự phòng.",
                "llm_status": _get_learning_path_llm_status(),
            }

        normalized = []
        for chapter in chapters:
            chapter_id = chapter.get("chapter_id") or uuid.uuid4().hex
            title = chapter.get("title") or "Chuong"
            chapter_concepts = []
            lessons = []
            for lesson in chapter.get("lessons", []):
                lesson_title = lesson.get("title") or "Bai hoc"
                concept_id = lesson.get("concept_id") or lesson_title
                concept_name = lesson.get("concept_name") or lesson_title
                chapter_concepts.append(
                    {
                        "id": str(concept_id),
                        "name": str(concept_name),
                    }
                )
                lessons.append(
                    {
                        "lesson_id": lesson.get("lesson_id") or uuid.uuid4().hex,
                        "title": lesson_title,
                        "summary": lesson.get("summary") or "",
                        "resources": lesson.get("resources") or [],
                        "concept_id": str(concept_id),
                        "concept_name": str(concept_name),
                        "concept_list": [
                            {"id": str(concept_id), "name": str(concept_name)}
                        ],
                    }
                )
            for lesson in lessons:
                lesson["concept_list"] = [dict(item) for item in chapter_concepts]
            if lessons:
                normalized.append(
                    {
                        "chapter_id": chapter_id,
                        "title": title,
                        "concepts": chapter_concepts,
                        "lessons": lessons,
                    }
                )
        if normalized:
            return {
                "curriculum": _add_lesson_ids(normalized),
                "source": "ai",
                "notice": None,
                "llm_status": _get_learning_path_llm_status(),
            }
        return {
            "curriculum": _build_curriculum_from_recommended(recommended, level),
            "source": "fallback",
            "notice": "AI không sinh được danh sách bài học hợp lệ, hệ thống đã dùng lộ trình dự phòng.",
            "llm_status": _get_learning_path_llm_status(),
        }
    except Exception as e:
        logger.warning(f"Curriculum generation failed: {e}")
        return {
            "curriculum": _build_curriculum_from_recommended(recommended, level),
            "source": "fallback",
            "notice": "AI tạm thời không phản hồi, hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể tiếp tục.",
            "llm_status": _get_learning_path_llm_status(),
        }


def generate_learning_path(user_id: str, goal: str, level: str = "beginner") -> Dict:
    """
    Generate personalized adaptive learning path for user.

    Pipeline:
    1. Validate inputs (user_id, goal, level)
    2. Fetch user's current progress (what concepts they've completed)
    3. Build prerequisite graph (concept_id → prerequisites)
    4. Detect cycles + topological sort
    5. Filter concepts by level (match user level)
    6. Determine adaptive mode (remedial/normal/advanced based on progress)
    7. Filter resources per concept by adaptive mode
    8. Rank concepts by: difficulty + progress + prerequisites
    9. Select top N concepts (default: 15)
    10. Enrich with resource recommendations
    11. Return ordered path

    Args:
        user_id: MongoDB ObjectId as string
        goal: Learning goal (free text)
        level: Learning level (beginner/intermediate/advanced)

    Returns:
        Dict with:
        - path_id: UUID
        - user_id: str
        - goal: str
        - level: str
        - generated_at: datetime
        - recommended_path: List[Dict] (ordered concepts with resources)
        - message: str

    Example:
        >>> path = generate_learning_path(
        ...     user_id="507f1f77bcf86cd799439011",
        ...     goal="Learn Python fundamentals",
        ...     level="beginner"
        ... )
        >>> print(f"Path: {path['recommended_path']}")
    """
    logger.info(
        f"Generating learning path: user={user_id}, goal='{goal[:50]}...', level={level}"
    )

    try:
        # 1️⃣ VALIDATE INPUTS
        if not user_id:
            raise ValueError("user_id cannot be empty")

        if not goal or len(goal.strip()) < 3:
            raise ValueError("goal must be at least 3 characters")

        if level not in ["beginner", "intermediate", "advanced"]:
            raise ValueError(f"Invalid level: {level}")

        logger.debug(f"Input validation passed")

        db = get_db()

        # 2️⃣ FETCH USER'S CURRENT PROGRESS
        user_progress = list(
            db.progress.find({"user_id": user_id}, {"concept_id": 1, "mastery": 1})
        )

        completed_concepts = set(
            p["concept_id"]
            for p in user_progress
            if p.get("mastery", 0) >= MASTERY_THRESHOLD_DEFAULT
        )

        user_progress_map = {
            p["concept_id"]: p.get("mastery", 0) for p in user_progress
        }

        logger.debug(
            f"User progress: {len(user_progress)} concepts, {len(completed_concepts)} completed"
        )

        # 3️⃣ BUILD PREREQUISITE GRAPH
        all_concepts = list(
            db.concepts.find(
                {},
                {
                    "concept_id": 1,
                    "concept_name": 1,
                    "topic": 1,
                    "difficulty": 1,
                    "bloom_level": 1,
                },
            )
        )

        logger.debug(f"Fetched {len(all_concepts)} concepts from DB")

        if not all_concepts:
            logger.warning(
                "No concepts found in DB; using AI-first curriculum generation from goal seeds"
            )
            seed_recommended = _build_goal_seed_concepts(goal, level)
            curriculum_result = _generate_curriculum(
                goal=goal, level=level, recommended=seed_recommended
            )
            curriculum = curriculum_result.get("curriculum", [])
            recommended = (
                _build_recommended_from_curriculum(curriculum) or seed_recommended
            )
            path_id = str(uuid.uuid4())
            return {
                "path_id": path_id,
                "user_id": user_id,
                "goal": goal,
                "level": level,
                "generated_at": datetime.utcnow(),
                "recommended_path": recommended,
                "curriculum": curriculum,
                "curriculum_source": curriculum_result.get("source", "fallback"),
                "curriculum_notice": curriculum_result.get("notice"),
                "llm_status": curriculum_result.get("llm_status"),
                "message": f"Generated learning path with {len(recommended)} concepts",
            }

        # Build graph: concept_id → Set of prerequisite concept_ids
        prereq_graph: Dict[int, Set[int]] = {}
        for concept in all_concepts:
            concept_id = concept.get("concept_id")
            prereq_graph[concept_id] = set()

        # Add prerequisites
        prerequisites = list(
            db.prerequisites.find({}, {"from_concept_id": 1, "to_concept_id": 1})
        )

        for prereq in prerequisites:
            from_id = prereq.get("from_concept_id")
            to_id = prereq.get("to_concept_id")
            if to_id in prereq_graph:  # to_concept_id depends on from_concept_id
                prereq_graph[to_id].add(from_id)

        logger.debug(f"Prerequisites graph: {len(prerequisites)} edges")

        # 4️⃣ DETECT CYCLES + TOPOLOGICAL SORT
        sorted_concepts = _topological_sort(prereq_graph)
        logger.debug(f"Topological sort: {len(sorted_concepts)} concepts")

        # 5️⃣ FILTER BY LEVEL
        concept_by_id = {c.get("concept_id"): c for c in all_concepts}

        level_difficulty_range = {
            "beginner": (1, 4),
            "intermediate": (3, 7),
            "advanced": (6, 10),
        }

        min_diff, max_diff = level_difficulty_range.get(level, (1, 10))

        filtered_concepts = [
            c
            for c in sorted_concepts
            if min_diff <= concept_by_id.get(c, {}).get("difficulty", 5) <= max_diff
        ]

        logger.debug(
            f"Filtered by level: {len(filtered_concepts)} concepts match {level}"
        )

        # 6️⃣ DETERMINE ADAPTIVE MODE
        avg_mastery = (
            sum(user_progress_map.values()) / len(user_progress_map)
            if user_progress_map
            else 0
        )

        adaptive_mode = decide_learning_mode(
            mastery=avg_mastery,
            confidence=sum(1 for m in user_progress_map.values() if m >= 0.6)
            / max(len(user_progress_map), 1),
            total_attempts=len(user_progress_map),
        )

        logger.info(f"Adaptive mode: {adaptive_mode.value}")

        # 7️⃣ RANK + FILTER CONCEPTS
        recommended = []

        for concept_id in filtered_concepts:
            concept = concept_by_id.get(concept_id, {})

            # Skip if already completed
            if concept_id in completed_concepts:
                logger.debug(f"Skipping completed concept: {concept_id}")
                continue

            # Check prerequisites met
            prerequisites_met = all(
                p in completed_concepts for p in prereq_graph.get(concept_id, [])
            )

            if not prerequisites_met:
                logger.debug(f"Prerequisites not met for concept: {concept_id}")
                continue

            # Calculate priority score
            difficulty = concept.get("difficulty", 5)
            current_mastery = user_progress_map.get(concept_id, 0)

            # Priority: favor concepts matching user level
            level_match_bonus = 0.5 if min_diff <= difficulty <= max_diff else 0

            # Priority: favor concepts not started yet
            started_penalty = current_mastery * 0.3  # Lower priority if already started

            priority_score = (
                (LEVEL_FACTOR.get(level, 1.0) * (10 - difficulty) / 10)
                + level_match_bonus
                - started_penalty
            )

            # GET RESOURCE RECOMMENDATIONS
            resources = recommend_resources_for_concept(
                concept_id=concept_id, level=level, limit=3
            )

            recommended.append(
                {
                    "concept_id": concept_id,
                    "concept_name": concept.get("concept_name"),
                    "difficulty": difficulty,
                    "bloom_level": concept.get("bloom_level"),
                    "mode": adaptive_mode.value,
                    "priority_score": round(priority_score, 2),
                    "resources": resources,
                }
            )

            if len(recommended) >= MAX_RECOMMENDATIONS:
                break

        if not recommended:
            logger.warning(
                "No eligible concepts found from graph; using AI-first curriculum generation from goal seeds"
            )
            seed_recommended = _build_goal_seed_concepts(goal, level)
            curriculum_result = _generate_curriculum(
                goal=goal, level=level, recommended=seed_recommended
            )
            curriculum = curriculum_result.get("curriculum", [])
            recommended = (
                _build_recommended_from_curriculum(curriculum) or seed_recommended
            )
        else:
            curriculum_result = _generate_curriculum(
                goal=goal, level=level, recommended=recommended
            )
            curriculum = curriculum_result.get("curriculum", [])

        # 8️⃣ RETURN RESULT
        path_id = str(uuid.uuid4())

        logger.info(
            f"Learning path generated: path_id={path_id}, concepts={len(recommended)}, mode={adaptive_mode.value}"
        )

        return {
            "path_id": path_id,
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "recommended_path": recommended,
            "curriculum": curriculum,
            "curriculum_source": curriculum_result.get("source", "fallback"),
            "curriculum_notice": curriculum_result.get("notice"),
            "llm_status": curriculum_result.get("llm_status"),
            "message": f"Generated learning path with {len(recommended)} concepts in {adaptive_mode.value} mode",
        }

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error generating learning path: {e}")
        raise RuntimeError(f"Failed to generate learning path: {str(e)}")
