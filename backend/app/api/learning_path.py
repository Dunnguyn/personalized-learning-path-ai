from typing import List, Dict
from datetime import datetime

from fastapi import APIRouter, HTTPException
from backend.app.database.mongo import db

router = APIRouter()

# =========================
# 1. DATA ACCESS
# =========================

def get_user_mastery(user_id: int) -> Dict[int, float]:
    """
    {concept_id: mastery}
    """
    progress = db.progress.find({"user_id": user_id})
    return {p["concept_id"]: p.get("mastery", 0.0) for p in progress}


def get_concepts_by_goal(goal: str) -> List[Dict]:
    """
    Lấy concept theo course (goal)
    """
    course = db.courses.find_one({"course_name": goal})
    if not course:
        return []

    return list(db.concepts.find({"course_id": course["_id"]}))


def get_prerequisite_map() -> Dict[int, List[int]]:
    """
    {concept_id: [prerequisite_concept_id]}
    """
    prereqs = {}
    for p in db.prerequisites.find():
        prereqs.setdefault(p["to_concept_id"], []).append(p["from_concept_id"])
    return prereqs


# =========================
# 2. PRIORITY LOGIC
# =========================

def compute_priority(concept: Dict, mastery: float) -> float:
    """
    priority = (1 - mastery) * difficulty
    """
    difficulty = concept.get("difficulty", 1)
    return round((1 - mastery) * difficulty, 3)


def prerequisite_satisfied(
    concept_id: int,
    mastery_map: Dict[int, float],
    prereq_map: Dict[int, List[int]],
    threshold: float = 0.6
) -> bool:
    """
    Kiểm tra prerequisite đã đạt mastery chưa
    """
    prereqs = prereq_map.get(concept_id, [])
    for pid in prereqs:
        if mastery_map.get(pid, 0.0) < threshold:
            return False
    return True


# =========================
# 3. CORE ENGINE
# =========================

def generate_learning_path(
    user_id: int,
    goal: str,
    level: str,
    max_items: int = 10
) -> Dict:
    """
    Sinh learning path + lưu DB
    """

    mastery_map = get_user_mastery(user_id)
    concepts = get_concepts_by_goal(goal)
    prereq_map = get_prerequisite_map()

    if not concepts:
        raise HTTPException(status_code=404, detail="No concepts found for this goal")

    candidates = []

    for c in concepts:
        cid = c["_id"]
        mastery = mastery_map.get(cid, 0.0)

        if mastery >= 0.85:
            continue

        if not prerequisite_satisfied(cid, mastery_map, prereq_map):
            continue

        priority = compute_priority(c, mastery)

        candidates.append({
            "concept_id": cid,
            "concept_name": c["concept_name"],
            "priority": priority,
            "mastery": mastery,
            "reason": (
                "Chưa nắm vững kiến thức nền"
                if mastery < 0.5
                else "Cần củng cố để học nâng cao"
            )
        })

    candidates.sort(key=lambda x: x["priority"], reverse=True)
    selected = candidates[:max_items]

    # =========================
    # 4. SAVE LEARNING PATH
    # =========================

    path_doc = {
        "user_id": user_id,
        "goal": goal,
        "level": level,
        "generated_at": datetime.utcnow()
    }

    path_id = db.learning_paths.insert_one(path_doc).inserted_id

    items = []
    for idx, item in enumerate(selected, start=1):
        items.append({
            "path_id": path_id,
            "concept_id": item["concept_id"],
            "order_index": idx,
            "reason": item["reason"],
            "status": "pending"
        })

    if items:
        db.learning_path_items.insert_many(items)

    # =========================
    # 5. RESPONSE
    # =========================

    return {
        "path_id": str(path_id),
        "goal": goal,
        "level": level,
        "items": selected
    }


# =========================
# 4. API ENDPOINT
# =========================

@router.post("/generate")
def generate_learning_path_api(
    user_id: int,
    goal: str,
    level: str
):
    """
    Generate learning path dựa trên mastery + prerequisite
    """
    return generate_learning_path(
        user_id=user_id,
        goal=goal,
        level=level
    )
