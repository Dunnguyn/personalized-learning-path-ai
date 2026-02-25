from datetime import datetime
from typing import Dict, Set, List, Optional
import logging
import uuid
import os
from functools import lru_cache
import json
import re

from backend.app.database.mongo import get_db
from backend.app.services.resource_recommender import recommend_resources_for_concept
from backend.app.services.progress_service import get_progress
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
        lessons = chapter.get("lessons", [])
        for lesson in lessons:
            if not lesson.get("lesson_id"):
                lesson["lesson_id"] = uuid.uuid4().hex
    return chapters


def _build_curriculum_from_recommended(recommended: List[Dict]) -> List[Dict]:
    chapters: List[Dict] = []
    if not recommended:
        return chapters

    chunk_size = 3
    for idx in range(0, len(recommended), chunk_size):
        chunk = recommended[idx:idx + chunk_size]
        lessons = []
        for item in chunk:
            lesson_resources = [r.get("title") for r in item.get("resources", []) if r.get("title")]
            lessons.append({
                "lesson_id": uuid.uuid4().hex,
                "title": item.get("concept_name") or "Bai hoc",
                "summary": "Hoc va luyen tap cac kien thuc co ban cho muc nay.",
                "resources": lesson_resources
            })
        chapters.append({
            "title": f"Chuong {len(chapters) + 1}",
            "lessons": lessons
        })
    return chapters


def _generate_curriculum(goal: str, level: str, recommended: List[Dict]) -> List[Dict]:
    if not (USE_LLM and _curriculum_rag):
        return _build_curriculum_from_recommended(recommended)

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
            return _build_curriculum_from_recommended(recommended)

        data = json.loads(json_text)
        chapters = data.get("chapters") if isinstance(data, dict) else None
        if not chapters or not isinstance(chapters, list):
            return _build_curriculum_from_recommended(recommended)

        normalized = []
        for chapter in chapters:
            title = chapter.get("title") or "Chuong"
            lessons = []
            for lesson in chapter.get("lessons", []):
                lessons.append({
                    "lesson_id": lesson.get("lesson_id") or uuid.uuid4().hex,
                    "title": lesson.get("title") or "Bai hoc",
                    "summary": lesson.get("summary") or "",
                    "resources": lesson.get("resources") or []
                })
            if lessons:
                normalized.append({
                    "title": title,
                    "lessons": lessons
                })
        return _add_lesson_ids(normalized) or _build_curriculum_from_recommended(recommended)
    except Exception as e:
        logger.warning(f"Curriculum generation failed: {e}")
        return _build_curriculum_from_recommended(recommended)
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