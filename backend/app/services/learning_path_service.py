from backend.app.database.mongo import db
from datetime import datetime
from typing import Dict, Set
from backend.app.services.resource_recommender import (
    recommend_resources_for_concept
)

LEVEL_FACTOR = {
    "beginner": 1.2,
    "intermediate": 1.0,
    "advanced": 0.8,
}


def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    mastery_threshold: float = 0.8
) -> Dict:

    # =========================
    # 1. LOAD CONCEPTS
    # =========================
    concepts = list(db.concepts.find(
        {"topic": {"$regex": goal, "$options": "i"}},
        {"_id": 0}
    ))

    if not concepts:
        return {"recommended_path": []}

    concept_map = {c["concept_id"]: c for c in concepts}
    concept_ids = set(concept_map.keys())

    # =========================
    # 2. LOAD USER PROGRESS
    # =========================
    progress = db.progress.find(
        {"user_id": user_id, "concept_id": {"$in": list(concept_ids)}},
        {"_id": 0}
    )

    mastery_map = {p["concept_id"]: p.get("mastery", 0) for p in progress}

    # =========================
    # 3. FILTER TARGET CONCEPTS
    # =========================
    targets: Set[int] = {
        cid for cid in concept_ids
        if mastery_map.get(cid, 0) < mastery_threshold
    }

    if not targets:
        return {"recommended_path": []}

    # =========================
    # 4. LOAD PREREQUISITES
    # =========================
    prereqs = db.prerequisites.find(
        {"to_concept_id": {"$in": list(targets)}},
        {"_id": 0}
    )

    graph = {cid: set() for cid in targets}
    for p in prereqs:
        if p["from_concept_id"] in targets:
            graph[p["to_concept_id"]].add(p["from_concept_id"])

    # =========================
    # 5. TOPOLOGICAL SORT
    # =========================
    visited = set()
    ordered = []

    def dfs(cid):
        if cid in visited:
            return
        for pre in graph.get(cid, []):
            dfs(pre)
        visited.add(cid)
        ordered.append(cid)

    for cid in targets:
        dfs(cid)

    # =========================
    # 6. SCORING (🔥 CORE)
    # =========================
    level_factor = LEVEL_FACTOR.get(level.lower(), 1.0)

    scored = []
    for cid in ordered:
        c = concept_map[cid]
        mastery = mastery_map.get(cid, 0)

        difficulty = c.get("difficulty", 1)
        weight = c.get("weight", 1.0)

        score = (
            (1 - mastery)
            * difficulty
            * weight
            * level_factor
        )

        scored.append((cid, round(score, 4)))

    # Sort theo score giảm dần
    scored.sort(key=lambda x: x[1], reverse=True)

    # =========================
    # 7. SAVE LEARNING PATH
    # =========================
    path_id = db.learning_paths.insert_one({
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }).inserted_id

    items = []
    for idx, (cid, score) in enumerate(scored):
        items.append({
            "path_id": path_id,
            "concept_id": cid,
            "order_index": idx + 1,
            "priority_score": score,
            "status": "pending"
        })

    if items:
        db.learning_path_items.insert_many(items)

    return {
        "path_id": str(path_id),
        "recommended_path": [
            {
                "concept_id": cid,
                "concept_name": concept_map[cid]["concept_name"],
                "priority_score": score,
                "resources": recommend_resources_for_concept(
                    concept_id=cid,
                    level=level,
                    query=concept_map[cid]["concept_name"]
                )
            }
            for cid, score in scored
        ]
    }
