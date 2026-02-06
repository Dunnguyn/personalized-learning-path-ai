from datetime import datetime
from typing import Dict, Set, List, Optional
import logging
import uuid
from functools import lru_cache

from backend.app.database.mongo import db
from backend.app.services.resource_recommender import recommend_resources_for_concept
from backend.app.services.adaptive_engine import (
    decide_learning_mode,
    filter_resources_by_mode,
    can_unlock_next_concept,
    LearningMode
)

logger = logging.getLogger(__name__)

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


# =====================================================
# CYCLE DETECTION (for safer topological sort)
# =====================================================
def _has_cycle(graph: Dict[int, Set[int]]) -> bool:
    """
    Simple cycle detection using DFS.
    Returns True if graph has cycle.
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
# MAIN FUNCTION
# =====================================================
def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    mastery_threshold: float = MASTERY_THRESHOLD_DEFAULT,
    max_recommendations: Optional[int] = None
) -> Dict:
    """
    Generate personalized learning path based on:
    - Knowledge Graph (prerequisites)
    - User Progress (mastery, confidence)
    - Adaptive rule engine
    - Difficulty and learning mode
    
    Parameters
    ----------
    user_id : int
        User ID
    goal : str
        Learning goal/topic
    level : str
        User's current level (beginner/intermediate/advanced)
    mastery_threshold : float
        Concepts with mastery >= threshold are considered complete (default 0.8)
    max_recommendations : int
        Max number of concept recommendations (default 15)
    
    Returns
    -------
    Dict : {"path_id", "user_id", "goal", "level", "generated_at", "recommended_path"}
    """
    
    if max_recommendations is None:
        max_recommendations = MAX_RECOMMENDATIONS
    
    logger.info(
        f"Generating learning path: user={user_id}, goal={goal}, level={level}, "
        f"threshold={mastery_threshold}, max_recs={max_recommendations}"
    )
    
    try:
        # Validate inputs
        if user_id <= 0:
            raise ValueError("user_id must be positive")
        if not goal or not goal.strip():
            raise ValueError("goal cannot be empty")
        if level not in LEVEL_FACTOR:
            logger.warning(f"Unknown level '{level}'; using 'intermediate' instead")
            level = "intermediate"
        if not (0 <= mastery_threshold <= 1):
            raise ValueError("mastery_threshold must be in [0, 1]")
        
        # =========================
        # 1. LOAD CONCEPTS
        # =========================
        concepts = list(db.concepts.find(
            {"topic": {"$regex": goal, "$options": "i"}},
            {"_id": 0}
        ))
        
        if not concepts:
            logger.info(f"No concepts found for goal '{goal}'")
            return {
                "path_id": str(uuid.uuid4()),
                "user_id": user_id,
                "goal": goal,
                "level": level,
                "generated_at": datetime.utcnow(),
                "recommended_path": [],
                "message": f"No concepts found for goal: {goal}"
            }
        
        concept_map = {c["concept_id"]: c for c in concepts}
        concept_ids = set(concept_map.keys())
        
        logger.debug(f"Loaded {len(concepts)} concepts for goal '{goal}'")
        
        # =========================
        # 2. LOAD USER PROGRESS
        # =========================
        try:
            progress_list = list(db.progress.find(
                {"user_id": user_id, "concept_id": {"$in": list(concept_ids)}},
                {"_id": 0}
            ))
        except Exception as e:
            logger.exception(f"Error loading progress: {e}")
            progress_list = []
        
        mastery_map = {p["concept_id"]: p.get("mastery", 0.0) for p in progress_list}
        confidence_map = {p["concept_id"]: p.get("confidence", 0.5) for p in progress_list}
        attempts_map = {p["concept_id"]: p.get("total_attempts", 0) for p in progress_list}
        
        # =========================
        # 3. FILTER TARGET CONCEPTS (not yet mastered)
        # =========================
        targets = {
            cid for cid in concept_ids
            if mastery_map.get(cid, 0.0) < mastery_threshold
        }
        
        if not targets:
            logger.info(f"User {user_id} has mastered all concepts for goal '{goal}'")
            return {
                "path_id": str(uuid.uuid4()),
                "user_id": user_id,
                "goal": goal,
                "level": level,
                "generated_at": datetime.utcnow(),
                "recommended_path": [],
                "message": f"Congratulations! You've mastered all concepts for {goal}"
            }
        
        logger.debug(f"Target concepts (not yet mastered): {len(targets)}")
        
        # =========================
        # 4. BUILD PREREQUISITE GRAPH
        # =========================
        try:
            prereqs = list(db.prerequisites.find(
                {"to_concept_id": {"$in": list(targets)}},
                {"_id": 0}
            ))
        except Exception as e:
            logger.exception(f"Error loading prerequisites: {e}")
            prereqs = []
        
        graph = {cid: set() for cid in targets}
        for p in prereqs:
            src = p.get("from_concept_id")
            dst = p.get("to_concept_id")
            if src and dst and dst in targets:
                graph[dst].add(src)
        
        logger.debug(f"Built prerequisite graph with {len(graph)} nodes")
        
        # =========================
        # 5. TOPOLOGICAL SORT
        # =========================
        try:
            ordered = _topological_sort(graph)
        except Exception as e:
            logger.exception(f"Topological sort failed: {e}; using arbitrary order")
            ordered = list(targets)
        
        # =========================
        # 6. ADAPTIVE SCORING
        # =========================
        level_factor = LEVEL_FACTOR.get(level.lower(), 1.0)
        scored = []
        
        for cid in ordered:
            try:
                concept = concept_map.get(cid)
                if not concept:
                    continue
                
                mastery = mastery_map.get(cid, 0.0)
                confidence = confidence_map.get(cid, 0.5)
                attempts = attempts_map.get(cid, 0)
                
                mode = decide_learning_mode(
                    mastery=mastery,
                    confidence=confidence,
                    total_attempts=attempts
                )
                
                difficulty = concept.get("difficulty", 1)
                weight = concept.get("weight", 1.0)
                
                # Score = urgency * difficulty * weight * level_adjustment
                priority_score = (1 - mastery) * difficulty * weight * level_factor
                
                scored.append({
                    "concept_id": cid,
                    "concept_name": concept.get("concept_name"),
                    "difficulty": difficulty,
                    "bloom_level": concept.get("bloom_level"),
                    "mastery": round(mastery, 3),
                    "confidence": round(confidence, 3),
                    "mode": mode.value if isinstance(mode, LearningMode) else mode,
                    "priority_score": round(priority_score, 4),
                    "attempts": attempts
                })
            except Exception as e:
                logger.debug(f"Error scoring concept {cid}: {e}")
                continue
        
        # Sort by priority (descending)
        scored.sort(key=lambda x: x["priority_score"], reverse=True)
        
        logger.debug(f"Scored {len(scored)} concepts")
        
        # =========================
        # 7. SAVE LEARNING PATH to DB
        # =========================
        path_id = str(uuid.uuid4())
        path_doc = {
            "path_id": path_id,
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "total_concepts": len(scored)
        }
        
        try:
            db.learning_paths.insert_one(path_doc)
            
            # Insert path items
            path_items = [
                {
                    "path_id": path_id,
                    "concept_id": item["concept_id"],
                    "order_index": idx + 1,
                    "priority_score": item["priority_score"],
                    "mode": item["mode"],
                    "status": "pending"
                }
                for idx, item in enumerate(scored)
            ]
            if path_items:
                db.learning_path_items.insert_many(path_items)
            
            logger.info(f"Saved learning path {path_id} with {len(path_items)} items")
        except Exception as e:
            logger.exception(f"Error saving learning path: {e}")
            # Don't fail — continue to build response
        
        # =========================
        # 8. ATTACH RESOURCES & FILTER BY MODE
        # =========================
        recommended_path = []
        
        for item in scored[:max_recommendations]:
            try:
                cid = item["concept_id"]
                concept_name = item["concept_name"]
                mode_str = item["mode"]
                
                # Fetch resources
                resources = recommend_resources_for_concept(
                    concept_id=cid,
                    level=level,
                    query=concept_name
                ) or []
                
                # Filter by adaptive mode
                try:
                    mode_enum = LearningMode(mode_str)
                    filtered_resources = filter_resources_by_mode(resources, mode_enum)
                except Exception as e:
                    logger.debug(f"Mode filtering error: {e}; using all resources")
                    filtered_resources = resources
                
                # Limit resources per concept
                filtered_resources = filtered_resources[:5]
                
                recommended_path.append({
                    "concept_id": cid,
                    "concept_name": concept_name,
                    "difficulty": item["difficulty"],
                    "bloom_level": item["bloom_level"],
                    "mode": mode_str,
                    "priority_score": item["priority_score"],
                    "mastery": item["mastery"],
                    "confidence": item["confidence"],
                    "attempts": item["attempts"],
                    "resources": filtered_resources
                })
            except Exception as e:
                logger.debug(f"Error building path item for concept {item.get('concept_id')}: {e}")
                continue
        
        logger.info(
            f"Generated path for user {user_id}: {len(recommended_path)} recommendations "
            f"from {len(scored)} target concepts"
        )
        
        # =========================
        # 9. RETURN RESPONSE
        # =========================
        return {
            "path_id": path_id,
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": path_doc["generated_at"],
            "total_target_concepts": len(scored),
            "recommended_path": recommended_path,
            "message": f"Generated {len(recommended_path)} recommendations for {goal}"
        }
    
    except ValueError as e:
        logger.warning(f"Validation error in generate_learning_path: {e}")
        return {
            "path_id": str(uuid.uuid4()),
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "recommended_path": [],
            "error": str(e)
        }
    except Exception as e:
        logger.exception(f"Unexpected error generating learning path: {e}")
        return {
            "path_id": str(uuid.uuid4()),
            "user_id": user_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "recommended_path": [],
            "error": "Could not generate learning path. Please try again."
        }