from backend.app.database.mongo import db
from datetime import datetime
from typing import Dict, Set


def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    mastery_threshold: float = 0.8
) -> Dict:

    # 1. Load concepts theo goal
    concepts = list(db.concepts.find(
        {"topic": {"$regex": goal, "$options": "i"}},
        {"_id": 0}
    ))

    if not concepts:
        return {"recommended_path": []}

    concept_map = {c["concept_id"]: c for c in concepts}
    concept_ids = set(concept_map.keys())

    # 2. Load progress
    progress = db.progress.find(
        {"user_id": user_id, "concept_id": {"$in": list(concept_ids)}},
        {"_id": 0}
    )

    mastery = {p["concept_id"]: p.get("mastery", 0) for p in progress}

    # 3. Concepts cần học
    targets: Set[int] = {
        cid for cid in concept_ids
        if mastery.get(cid, 0) < mastery_threshold
    }

    if not targets:
        return {"recommended_path": []}

    # 4. Load prerequisites
    prereqs = db.prerequisites.find(
        {"to_concept_id": {"$in": list(targets)}},
        {"_id": 0}
    )

    graph = {cid: set() for cid in targets}
    for p in prereqs:
        if p["from_concept_id"] in targets:
            graph[p["to_concept_id"]].add(p["from_concept_id"])

    # 5. Topological sort
    visited = set()
    order = []

    def dfs(cid):
        if cid in visited:
            return
        for pre in graph.get(cid, []):
            dfs(pre)
        visited.add(cid)
        order.append(cid)

    for cid in targets:
        dfs(cid)

    # 6. Save learning path
    path_id = db.learning_paths.insert_one({
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }).inserted_id

    items = []
    for idx, cid in enumerate(order):
        items.append({
            "path_id": path_id,
            "concept_id": cid,
            "order_index": idx + 1,
            "status": "pending"
        })

    if items:
        db.learning_path_items.insert_many(items)

    return {
        "path_id": str(path_id),
        "recommended_path": [
            concept_map[cid]["concept_name"] for cid in order
        ]
    }
