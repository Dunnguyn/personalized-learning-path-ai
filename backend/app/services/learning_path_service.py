from backend.app.database.mongo import db
from datetime import datetime
from typing import Dict, Set, List


def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    mastery_threshold: float = 0.8
) -> Dict:
    """
    Generate personalized learning path using:
    - prerequisite graph
    - mastery
    - difficulty
    - weight
    """

    # =========================
    # 1. LOAD CONCEPTS BY GOAL
    # =========================
    concepts = list(db.concepts.find(
        {"course": {"$regex": goal, "$options": "i"}},
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

    mastery_map = {
        p["concept_id"]: p.get("mastery", 0)
        for p in progress
    }

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
    # 5. TOPOLOGICAL SORT (DFS)
    # =========================
    visited = set()
    topo_order: List[int] = []

    def dfs(cid: int):
        if cid in visited:
            return
        for pre in graph.get(cid, []):
            dfs(pre)
        visited.add(cid)
        topo_order.append(cid)

    for cid in targets:
        dfs(cid)

    # =========================
    # 6. PRIORITY SCORING
    # =========================
    def priority_score(cid: int) -> float:
        concept = concept_map[cid]
        weight = concept.get("weight", 1.0)
        difficulty = concept.get("difficulty", 1)
        mastery = mastery_map.get(cid, 0)

        return round(
            weight * (1 + difficulty / 5) * (1 - mastery),
            4
        )

    scored = [
        {
            "concept_id": cid,
            "score": priority_score(cid)
        }
        for cid in topo_order
    ]

    # =========================
    # 7. SORT BY PRIORITY
    # =========================
    scored.sort(key=lambda x: x["score"], reverse=True)

    final_order = [item["concept_id"] for item in scored]

    # =========================
    # 8. SAVE LEARNING PATH
    # =========================
    path_id = db.learning_paths.insert_one({
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }).inserted_id

    items = []
    for idx, cid in enumerate(final_order):
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
            {
                "concept_id": cid,
                "concept_name": concept_map[cid]["concept_name"],
                "priority_score": priority_score(cid)
            }
            for cid in final_order
        ]
    }
