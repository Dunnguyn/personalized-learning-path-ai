from typing import List, Dict
from backend.app.database.mongo import db


# ===== 1. LOAD DATA =====

def get_all_concepts(goal: str) -> List[Dict]:
    """
    Lấy danh sách concept theo goal (course)
    """
    return list(db.concepts.find({"course": goal}))


def get_user_progress(user_id: str) -> Dict[str, float]:
    """
    Trả về dict: {concept_name: mastery}
    """
    progress = db.progress.find({"user_id": user_id})
    return {p["concept"]: p.get("mastery", 0.0) for p in progress}


# ===== 2. PRIORITY FUNCTION =====

def compute_priority(concept: Dict, mastery: float) -> float:
    """
    priority = (1 - mastery) * prerequisite_weight
    """
    weight = concept.get("weight", 1.0)
    return (1 - mastery) * weight


# ===== 3. LEARNING PATH ENGINE =====

def generate_learning_path(
    user_id: str,
    goal: str,
    max_items: int = 5
) -> List[Dict]:
    """
    Sinh lộ trình học tập cá nhân hóa
    """

    concepts = get_all_concepts(goal)
    mastery_map = get_user_progress(user_id)

    candidates = []

    for c in concepts:
        name = c["name"]
        mastery = mastery_map.get(name, 0.0)

        # Bỏ qua nếu đã nắm vững
        if mastery >= 0.8:
            continue

        priority = compute_priority(c, mastery)

        candidates.append({
            "concept": name,
            "mastery": mastery,
            "priority": round(priority, 3),
            "reason": (
                "Chưa nắm vững kiến thức nền"
                if mastery < 0.5
                else "Cần củng cố để học nâng cao"
            )
        })

    # Sắp xếp theo độ ưu tiên
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    return candidates[:max_items]
