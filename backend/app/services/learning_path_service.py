from backend.app.database.mongo import db
from datetime import datetime
from typing import Dict, List, Set


MASTERY_THRESHOLD = 0.8


# ==================================================
# CORE API
# ==================================================
def generate_learning_path(
    user_id: int,
    goal: str,
    level: str
) -> Dict:
    """
    Generate personalized learning path based on:
    - User mastery
    - Concept prerequisites
    """

    concepts = _load_concepts(goal)
    if not concepts:
        return _empty_path()

    concept_map = {c["concept_id"]: c for c in concepts}
    concept_ids = set(concept_map.keys())

    mastery = _load_mastery(user_id, concept_ids)

    target_concepts = _select_target_concepts(
        concept_ids, mastery
    )

    if not target_concepts:
        return _empty_path()

    graph = _build_prerequisite_graph(target_concepts)

    ordered_concepts = _topological_sort(graph)

    return _save_learning_path(
        user_id=user_id,
        goal=goal,
        level=level,
        ordered_concepts=ordered_concepts,
        concept_map=concept_map
    )


# ==================================================
# DATA LOADING
# ==================================================
def _load_concepts(goal: str) -> List[Dict]:
    return list(db.concepts.find(
        {"topic": {"$regex": goal, "$options": "i"}},
        {"_id": 0}
    ))


def _load_mastery(user_id: int, concept_ids: Set[int]) -> Dict[int, float]:
    progress = db.progress.find(
        {"user_id": user_id, "concept_id": {"$in": list(concept_ids)}},
        {"_id": 0}
    )
    return {p["concept_id"]: p.get("mastery", 0.0) for p in progress}


# ==================================================
# LOGIC
# ==================================================
def _select_target_concepts(
    concept_ids: Set[int],
    mastery: Dict[int, float]
) -> Set[int]:
    """
    Select concepts that user has NOT mastered
    """
    return {
        cid for cid in concept_ids
        if mastery.get(cid, 0.0) < MASTERY_THRESHOLD
    }


def _build_prerequisite_graph(
    targets: Set[int]
) -> Dict[int, Set[int]]:
    """
    Build dependency graph: concept -> prerequisites
    """
    graph = {cid: set() for cid in targets}

    prereqs = db.prerequisites.find(
        {"to_concept_id": {"$in": list(targets)}},
        {"_id": 0}
    )

    for p in prereqs:
        src = p["from_concept_id"]
        dst = p["to_concept_id"]

        if src in targets:
            graph[dst].add(src)

    return graph


# ==================================================
# TOPOLOGICAL SORT (SAFE)
# ==================================================
def _topological_sort(
    graph: Dict[int, Set[int]]
) -> List[int]:
    visited = set()
    visiting = set()
    order = []

    def dfs(cid: int):
        if cid in visiting:
            raise ValueError("Cycle detected in prerequisite graph")

        if cid in visited:
            return

        visiting.add(cid)
        for pre in graph.get(cid, []):
            dfs(pre)

        visiting.remove(cid)
        visited.add(cid)
        order.append(cid)

    for cid in graph:
        if cid not in visited:
            dfs(cid)

    return order


# ==================================================
# SAVE & RESPONSE
# ==================================================
def _save_learning_path(
    user_id: int,
    goal: str,
    level: str,
    ordered_concepts: List[int],
    concept_map: Dict[int, Dict]
) -> Dict:
    path_id = db.learning_paths.insert_one({
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }).inserted_id

    items = [{
        "path_id": path_id,
        "concept_id": cid,
        "order_index": idx + 1,
        "status": "pending"
    } for idx, cid in enumerate(ordered_concepts)]

    if items:
        db.learning_path_items.insert_many(items)

    return {
        "path_id": str(path_id),
        "recommended_path": [
            concept_map[cid]["concept_name"]
            for cid in ordered_concepts
        ]
    }


def _empty_path() -> Dict:
    return {
        "recommended_path": []
    }
