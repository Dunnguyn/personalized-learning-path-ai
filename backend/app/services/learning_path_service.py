from datetime import datetime
from typing import Dict, Set, List

from backend.app.database.mongo import db
from backend.app.services.resource_recommender import (
    recommend_resources_for_concept
)
from backend.app.services.adaptive_engine import (
    decide_learning_mode,
    filter_resources_by_mode,
    can_unlock_next_concept
)

# =====================================================
# LEVEL FACTOR – điều chỉnh theo trình độ người học
# =====================================================
LEVEL_FACTOR = {
    "beginner": 1.2,
    "intermediate": 1.0,
    "advanced": 0.8,
}


# =====================================================
# MAIN FUNCTION
# =====================================================
def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    mastery_threshold: float = 0.8
) -> Dict:
    """
    Sinh lộ trình học tập cá nhân hóa dựa trên:
    - Knowledge Graph (prerequisite)
    - Progress (mastery, confidence)
    - Adaptive rule engine
    """

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
    progress_list = list(db.progress.find(
        {"user_id": user_id, "concept_id": {"$in": list(concept_ids)}},
        {"_id": 0}
    ))

    mastery_map = {
        p["concept_id"]: p.get("mastery", 0.0)
        for p in progress_list
    }
    confidence_map = {
        p["concept_id"]: p.get("confidence", 0.5)
        for p in progress_list
    }
    attempts_map = {
        p["concept_id"]: p.get("total_attempts", 0)
        for p in progress_list
    }

    # =========================
    # 3. FILTER TARGET CONCEPTS
    # =========================
    targets: Set[int] = {
        cid for cid in concept_ids
        if mastery_map.get(cid, 0.0) < mastery_threshold
        or cid not in mastery_map
    }

    if not targets:
        return {"recommended_path": []}

    # =========================
    # 4. BUILD PREREQUISITE GRAPH
    # =========================
    prereqs = list(db.prerequisites.find(
        {"to_concept_id": {"$in": list(targets)}},
        {"_id": 0}
    ))

    graph = {cid: set() for cid in targets}
    for p in prereqs:
        src = p["from_concept_id"]
        dst = p["to_concept_id"]
        if src in targets:
            graph[dst].add(src)

    # =========================
    # 5. TOPOLOGICAL SORT (DFS)
    # =========================
    visited = set()
    ordered: List[int] = []

    def dfs(cid: int):
        if cid in visited:
            return
        for pre in graph.get(cid, []):
            dfs(pre)
        visited.add(cid)
        ordered.append(cid)

    for cid in targets:
        dfs(cid)

    # =========================
    # 6. ADAPTIVE SCORING
    # =========================
    level_factor = LEVEL_FACTOR.get(level.lower(), 1.0)
    scored = []

    for cid in ordered:
        concept = concept_map[cid]

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

        score = (
            (1 - mastery)
            * difficulty
            * weight
            * level_factor
        )

        scored.append({
            "concept_id": cid,
            "concept_name": concept["concept_name"],
            "difficulty": difficulty,
            "bloom_level": concept.get("bloom_level"),
            "mastery": mastery,
            "confidence": confidence,
            "mode": mode,
            "priority_score": round(score, 4)
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)

    # =========================
    # 7. SAVE LEARNING PATH
    # =========================
    path_doc = {
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }
    path_id = db.learning_paths.insert_one(path_doc).inserted_id

    db.learning_path_items.insert_many([
        {
            "path_id": path_id,
            "concept_id": item["concept_id"],
            "order_index": idx + 1,
            "priority_score": item["priority_score"],
            "mode": item["mode"],
            "status": "pending"
        }
        for idx, item in enumerate(scored)
    ])

    # =========================
    # 8. ATTACH RESOURCES (FIX BEGINNER LOGIC)
    # =========================
    recommended_path = []

    # 👉 CASE 1: BEGINNER – chọn concept nền tảng
    if level.lower() == "beginner":
        # concept không có prerequisite
        base_concepts = [
            item for item in scored
            if not db.prerequisites.find_one(
                {"to_concept_id": item["concept_id"]}
            )
        ]

        # sort theo độ khó tăng dần
        base_concepts.sort(key=lambda x: x["difficulty"])

        if base_concepts:
            item = base_concepts[0]
            cid = item["concept_id"]

            resources = recommend_resources_for_concept(
                concept_id=cid,
                level=level,
                query=item["concept_name"]
            ) or []

            recommended_path.append({
                "concept_id": cid,
                "concept_name": item["concept_name"],
                "difficulty": item["difficulty"],
                "bloom_level": item["bloom_level"],
                "mode": "remedial",
                "priority_score": item["priority_score"],
                "resources": filter_resources_by_mode(
                    resources=resources,
                    mode="remedial"
                )
            })

    # 👉 CASE 2: INTERMEDIATE / ADVANCED – giữ logic cũ
    else:
        for item in scored:
            if not can_unlock_next_concept(
                mastery=item["mastery"],
                confidence=item["confidence"]
            ):
                continue

            cid = item["concept_id"]

            resources = recommend_resources_for_concept(
                concept_id=cid,
                level=level,
                query=item["concept_name"]
            ) or []

            recommended_path.append({
                "concept_id": cid,
                "concept_name": item["concept_name"],
                "difficulty": item["difficulty"],
                "bloom_level": item["bloom_level"],
                "mode": item["mode"],
                "priority_score": item["priority_score"],
                "resources": filter_resources_by_mode(
                    resources=resources,
                    mode=item["mode"]
                )
            })

    # =========================
    # 9. RETURN RESPONSE
    # =========================
    return {
        "path_id": str(path_id),
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": path_doc["generated_at"],
        "recommended_path": recommended_path
    }
