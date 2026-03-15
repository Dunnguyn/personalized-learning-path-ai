from datetime import datetime
from typing import Dict, Set, List, Optional
import logging
import uuid
import os
from functools import lru_cache
import json
import re
import random

from backend.app.database.mongo import get_db
from backend.app.services.resource_recommender import recommend_resources_for_concept
from backend.app.services.progress_service import get_progress
from backend.app.services.question_generator import generate_questions as generate_template_questions
from backend.app.services.adaptive_engine import (
    decide_learning_mode,
    filter_resources_by_mode,
    can_unlock_next_concept,
    LearningMode
)
from backend.app.services.rag_pipeline import RAGPipeline, USE_LLM

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
LESSON_ASSESSMENT_QUESTION_COUNT = 10
MCQ_OPTION_KEYS = ["A", "B", "C", "D"]


def calculate_min_correct_required(required_questions: int) -> int:
    if required_questions <= 0:
        return 0
    return max(1, min(required_questions, int(required_questions * 0.7 + 0.9999)))


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
        logger.warning("Cycle detected in prerequisite graph; returning arbitrary order")
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
        "Return ONLY valid JSON in this schema:\n"
        "{\"chapters\":[{\"title\":string,\"lessons\":[{\"title\":string,\"summary\":string,\"resources\":[string]}]}]}\n"
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


def _difficulty_from_level(level: str) -> str:
    mapping = {
        "beginner": "easy",
        "intermediate": "medium",
        "advanced": "hard"
    }
    return mapping.get(level, "medium")


def _relation_answer_text(item: Dict, fallback_concept: str) -> str:
    concept_name = item.get("concept") or fallback_concept
    related = item.get("related_concepts") or [concept_name]
    relation_type = item.get("relation_type", "definition")

    if relation_type == "prerequisite" and len(related) >= 2:
        return f"{related[0]} la kien thuc nen tang can nam truoc khi hoc {related[1]}."
    if relation_type == "used_in" and len(related) >= 2:
        return f"{related[0]} duoc ap dung truc tiep trong {related[1]}."
    if relation_type == "part_of" and len(related) >= 2:
        return f"{related[0]} la mot thanh phan cau thanh cua {related[1]}."
    if relation_type == "related_to" and len(related) >= 2:
        return f"{related[0]} co moi lien he truc tiep va ho tro viec hieu {related[1]}."
    if relation_type == "comparison" and len(related) >= 2:
        return f"{related[0]} va {related[1]} khac nhau ve vai tro, dac diem hoac cach ap dung."
    return f"{concept_name} la mot khai niem can duoc hieu ro trong chuong hoc nay."


def _relation_distractors(item: Dict, fallback_concept: str) -> List[str]:
    concept_name = item.get("concept") or fallback_concept
    related = item.get("related_concepts") or [concept_name]
    other_name = related[1] if len(related) > 1 else concept_name
    relation_type = item.get("relation_type", "definition")

    if relation_type == "prerequisite":
        return [
            f"{other_name} can hoc truoc ma khong can biet {concept_name}.",
            f"{concept_name} va {other_name} hoan toan doc lap, khong co thu tu hoc tap.",
            f"{concept_name} chi la mot vi du phu, khong anh huong den viec hoc {other_name}.",
        ]
    if relation_type == "used_in":
        return [
            f"{concept_name} khong duoc su dung trong {other_name}.",
            f"{other_name} chi lien quan den ghi nho ly thuyet, khong can {concept_name}.",
            f"{concept_name} va {other_name} thuoc hai chu de tach biet, khong giao nhau.",
        ]
    if relation_type == "part_of":
        return [
            f"{concept_name} khong nam trong cau truc cua {other_name}.",
            f"{other_name} co the hieu day du ma khong can den {concept_name}.",
            f"{concept_name} chi la mot vi du ngoai le, khong phai thanh phan cua {other_name}.",
        ]
    if relation_type == "related_to":
        return [
            f"{concept_name} khong lien quan den viec hieu {other_name}.",
            f"{concept_name} va {other_name} khong co diem chung trong chuong hoc nay.",
            f"{other_name} chi thuoc mot chu de khac, khong can xet {concept_name}.",
        ]
    if relation_type == "comparison":
        return [
            f"{concept_name} va {other_name} hoan toan giong nhau, khong co diem nao can phan biet.",
            f"{concept_name} va {other_name} khong the dat canh de so sanh.",
            f"Chi can hoc mot trong hai, vi {concept_name} va {other_name} la mot.",
        ]

    return [
        f"{concept_name} khong co lien quan den noi dung cua chuong hoc nay.",
        f"{concept_name} chi can ghi nho ten goi, khong can hieu quan he voi {other_name}.",
        f"{concept_name} thuoc mot chu de khac va khong xuat hien trong chuong nay.",
    ]


def _build_chapter_graph_questions(
    chapter_id: str,
    fallback_concept: str,
    difficulty: str,
    num_questions: int,
    variation_seed: int
) -> List[Dict]:
    try:
        generated = generate_template_questions(
            chapter_id=chapter_id,
            num_questions=max(num_questions * 2, num_questions)
        )
    except Exception as e:
        logger.warning(f"QuestionGenerator failed for chapter {chapter_id}: {e}")
        return []

    if not generated:
        return []

    rng = random.Random(f"chapter:{chapter_id}:{difficulty}:{variation_seed}")
    pool = generated[:]
    rng.shuffle(pool)

    normalized: List[Dict] = []
    seen_questions = set()

    for idx, item in enumerate(pool):
        question_text = str(item.get("question", "")).strip()
        if not question_text:
            continue
        question_key = question_text.lower()
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)

        correct_text = _relation_answer_text(item, fallback_concept)
        distractors = _relation_distractors(item, fallback_concept)

        option_payload = [
            {"is_correct": True, "text": correct_text},
            {"is_correct": False, "text": distractors[0]},
            {"is_correct": False, "text": distractors[1]},
            {"is_correct": False, "text": distractors[2]},
        ]
        rng.shuffle(option_payload)

        options = []
        correct_option = "A"
        for option_key, payload in zip(MCQ_OPTION_KEYS, option_payload):
            options.append({"key": option_key, "text": payload["text"]})
            if payload["is_correct"]:
                correct_option = option_key

        normalized.append({
            "question_id": uuid.uuid4().hex,
            "question": question_text,
            "answer": correct_text,
            "explanation": "Cau hoi duoc sinh tu concept va quan he trong knowledge graph cua chuong hoc.",
            "difficulty": difficulty,
            "concept": item.get("concept") or fallback_concept,
            "options": options,
            "correct_option": correct_option
        })

        if len(normalized) >= num_questions:
            break

    return normalized


def generate_lesson_mcq_questions(
    concept: str,
    level: str,
    lesson_summary: str,
    lesson_resources: List[str],
    num_questions: int = LESSON_ASSESSMENT_QUESTION_COUNT,
    variation_seed: int = 0,
    chapter_id: Optional[str] = None
) -> List[Dict]:
    difficulty = _difficulty_from_level(level)
    if not chapter_id:
        raise ValueError("chapter_id is required for assessment question generation")

    questions = _build_chapter_graph_questions(
        chapter_id=chapter_id,
        fallback_concept=concept,
        difficulty=difficulty,
        num_questions=num_questions,
        variation_seed=variation_seed
    )
    if not questions:
        raise ValueError(f"No knowledge-graph questions generated for chapter_id={chapter_id}")
    return questions


def _build_lesson_assessment(
    lesson_title: str,
    level: str,
    lesson_summary: str,
    lesson_resources: List[str],
    variation_seed: int = 0,
    chapter_id: Optional[str] = None
) -> Dict:
    concept = lesson_title or "concept"

    questions = generate_lesson_mcq_questions(
        concept=concept,
        level=level,
        lesson_summary=lesson_summary,
        lesson_resources=lesson_resources,
        num_questions=LESSON_ASSESSMENT_QUESTION_COUNT,
        variation_seed=variation_seed,
        chapter_id=chapter_id
    )
    required_questions = len(questions)
    min_correct_required = calculate_min_correct_required(required_questions)

    return {
        "required_questions": required_questions,
        "attempted_questions": 0,
        "completed": False,
        "generation": variation_seed,
        "correct_answers": 0,
        "min_correct_required": min_correct_required,
        "passed": False,
        "score_percent": 0.0,
        "question_results": [],
        "questions": questions
    }


def _build_curriculum_from_recommended(recommended: List[Dict], level: str) -> List[Dict]:
    chapters: List[Dict] = []
    if not recommended:
        return chapters

    chunk_size = 3
    for idx in range(0, len(recommended), chunk_size):
        chunk = recommended[idx:idx + chunk_size]
        chapter_id = uuid.uuid4().hex
        lessons = []
        for item in chunk:
            lesson_resources = [r.get("title") for r in item.get("resources", []) if r.get("title")]
            lessons.append({
                "lesson_id": uuid.uuid4().hex,
                "title": item.get("concept_name") or "Bai hoc",
                "summary": "Hoc va luyen tap cac kien thuc co ban cho muc nay.",
                "resources": lesson_resources,
                "assessment": _build_lesson_assessment(
                    lesson_title=item.get("concept_name") or "Bai hoc",
                    level=level,
                    lesson_summary="Hoc va luyen tap cac kien thuc co ban cho muc nay.",
                    lesson_resources=lesson_resources,
                    chapter_id=chapter_id
                )
            })
        chapters.append({
            "chapter_id": chapter_id,
            "title": f"Chuong {len(chapters) + 1}",
            "lessons": lessons
        })
    return chapters


def _generate_curriculum(goal: str, level: str, recommended: List[Dict]) -> List[Dict]:
    if not (USE_LLM and _curriculum_rag):
        return _build_curriculum_from_recommended(recommended, level)

    try:
        resources = _curriculum_rag.retrieve_context(
            query=goal,
            goal=goal,
            level=level,
            k=6
        )
        prompt = _build_curriculum_prompt(goal, level, resources)
        response_text = _curriculum_rag._call_llm_with_retry(prompt)
        json_text = _extract_json_block(response_text or "")
        if not json_text:
            return _build_curriculum_from_recommended(recommended, level)

        data = json.loads(json_text)
        chapters = data.get("chapters") if isinstance(data, dict) else None
        if not chapters or not isinstance(chapters, list):
            return _build_curriculum_from_recommended(recommended, level)

        normalized = []
        for chapter in chapters:
            chapter_id = chapter.get("chapter_id") or uuid.uuid4().hex
            title = chapter.get("title") or "Chuong"
            lessons = []
            for lesson in chapter.get("lessons", []):
                lessons.append({
                    "lesson_id": lesson.get("lesson_id") or uuid.uuid4().hex,
                    "title": lesson.get("title") or "Bai hoc",
                    "summary": lesson.get("summary") or "",
                    "resources": lesson.get("resources") or [],
                    "assessment": _build_lesson_assessment(
                        lesson_title=lesson.get("title") or "Bai hoc",
                        level=level,
                        lesson_summary=lesson.get("summary") or "",
                        lesson_resources=lesson.get("resources") or [],
                        chapter_id=chapter_id
                    )
                })
            if lessons:
                normalized.append({
                    "chapter_id": chapter_id,
                    "title": title,
                    "lessons": lessons
                })
        return _add_lesson_ids(normalized) or _build_curriculum_from_recommended(recommended, level)
    except Exception as e:
        logger.warning(f"Curriculum generation failed: {e}")
        return _build_curriculum_from_recommended(recommended, level)
def generate_learning_path(
    user_id: str,
    goal: str,
    level: str = "beginner"
) -> Dict:
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
    logger.info(f"Generating learning path: user={user_id}, goal='{goal[:50]}...', level={level}")
    
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
        user_progress = list(db.progress.find(
            {"user_id": user_id},
            {"concept_id": 1, "mastery": 1}
        ))
        
        completed_concepts = set(
            p["concept_id"] for p in user_progress
            if p.get("mastery", 0) >= MASTERY_THRESHOLD_DEFAULT
        )
        
        user_progress_map = {
            p["concept_id"]: p.get("mastery", 0)
            for p in user_progress
        }
        
        logger.debug(f"User progress: {len(user_progress)} concepts, {len(completed_concepts)} completed")
        
        # 3️⃣ BUILD PREREQUISITE GRAPH
        all_concepts = list(db.concepts.find({}, {
            "concept_id": 1,
            "concept_name": 1,
            "topic": 1,
            "difficulty": 1,
            "bloom_level": 1
        }))
        
        logger.debug(f"Fetched {len(all_concepts)} concepts from DB")
        
        # Build graph: concept_id → Set of prerequisite concept_ids
        prereq_graph: Dict[int, Set[int]] = {}
        for concept in all_concepts:
            concept_id = concept.get("concept_id")
            prereq_graph[concept_id] = set()
        
        # Add prerequisites
        prerequisites = list(db.prerequisites.find({}, {
            "from_concept_id": 1,
            "to_concept_id": 1
        }))
        
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
            "advanced": (6, 10)
        }
        
        min_diff, max_diff = level_difficulty_range.get(level, (1, 10))
        
        filtered_concepts = [
            c for c in sorted_concepts
            if min_diff <= concept_by_id.get(c, {}).get("difficulty", 5) <= max_diff
        ]
        
        logger.debug(f"Filtered by level: {len(filtered_concepts)} concepts match {level}")
        
        # 6️⃣ DETERMINE ADAPTIVE MODE
        avg_mastery = (
            sum(user_progress_map.values()) / len(user_progress_map)
            if user_progress_map else 0
        )
        
        adaptive_mode = decide_learning_mode(
            mastery=avg_mastery,
            confidence=sum(1 for m in user_progress_map.values() if m >= 0.6) / max(len(user_progress_map), 1),
            total_attempts=len(user_progress_map)
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
                (LEVEL_FACTOR.get(level, 1.0) * (10 - difficulty) / 10) +
                level_match_bonus -
                started_penalty
            )
            
            # GET RESOURCE RECOMMENDATIONS
            resources = recommend_resources_for_concept(
                concept_id=concept_id,
                level=level,
                limit=3
            )
            
            recommended.append({
                "concept_id": concept_id,
                "concept_name": concept.get("concept_name"),
                "difficulty": difficulty,
                "bloom_level": concept.get("bloom_level"),
                "mode": adaptive_mode.value,
                "priority_score": round(priority_score, 2),
                "resources": resources
            })
            
            if len(recommended) >= MAX_RECOMMENDATIONS:
                break
        
        # 8️⃣ RETURN RESULT
        path_id = str(uuid.uuid4())
        
        logger.info(
            f"Learning path generated: path_id={path_id}, concepts={len(recommended)}, mode={adaptive_mode.value}"
        )
        
        curriculum = _generate_curriculum(goal=goal, level=level, recommended=recommended)

        return {
            "path_id": path_id,
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "recommended_path": recommended,
            "curriculum": curriculum,
            "message": f"Generated learning path with {len(recommended)} concepts in {adaptive_mode.value} mode"
        }
    
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise
    except Exception as e:
        logger.exception(f"Error generating learning path: {e}")
        raise RuntimeError(f"Failed to generate learning path: {str(e)}")
