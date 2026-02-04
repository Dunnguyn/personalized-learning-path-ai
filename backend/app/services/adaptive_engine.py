from typing import Dict, List


# =====================================================
# ADAPTIVE MODE CONSTANTS
# =====================================================
MODE_REMEDIAL = "remedial"     # học lại / bổ trợ
MODE_NORMAL = "normal"         # học theo lộ trình chuẩn
MODE_ADVANCED = "advanced"     # tăng tốc / nâng cao


# =====================================================
# CORE ADAPTIVE DECISION
# =====================================================
def decide_learning_mode(
    mastery: float,
    confidence: float,
    total_attempts: int
) -> str:
    """
    Quyết định chế độ học tập dựa trên tiến độ người học

    Parameters
    ----------
    mastery : float (0.0 – 1.0)
        Mức độ nắm vững kiến thức
    confidence : float (0.0 – 1.0)
        Độ tự tin / ổn định học tập
    total_attempts : int
        Số lần học / thử

    Returns
    -------
    str : remedial | normal | advanced
    """

    # Trường hợp học yếu hoặc không ổn định
    if mastery < 0.5 or confidence < 0.4:
        return MODE_REMEDIAL

    # Trường hợp học tốt, ổn định
    if mastery >= 0.8 and confidence >= 0.75 and total_attempts <= 2:
        return MODE_ADVANCED

    # Mặc định
    return MODE_NORMAL


# =====================================================
# RESOURCE FILTERING BY MODE
# =====================================================
def filter_resources_by_mode(
    resources: List[Dict],
    mode: str
) -> List[Dict]:
    """
    Lọc tài nguyên học tập theo chế độ học

    resource format (dict):
    {
        "resource_id": int,
        "pedagogy_type": str,
        "bloom_level": str
    }
    """

    if mode == MODE_REMEDIAL:
        return [
            r for r in resources
            if r.get("bloom_level") in ["remember", "understand"]
        ]

    if mode == MODE_ADVANCED:
        return [
            r for r in resources
            if r.get("bloom_level") in ["analyze", "evaluate", "create"]
        ]

    # MODE_NORMAL
    return resources


# =====================================================
# NEXT CONCEPT DECISION
# =====================================================
def can_unlock_next_concept(
    mastery: float,
    confidence: float
) -> bool:
    """
    Kiểm tra có được mở concept tiếp theo hay không
    """

    return mastery >= 0.6 and confidence >= 0.5


# =====================================================
# ADAPTIVE SUMMARY (DEBUG / LOG)
# =====================================================
def adaptive_decision_summary(
    mastery: float,
    confidence: float,
    total_attempts: int
) -> Dict:
    """
    Trả về thông tin quyết định – tiện debug & log
    """

    mode = decide_learning_mode(mastery, confidence, total_attempts)

    return {
        "mode": mode,
        "mastery": mastery,
        "confidence": confidence,
        "attempts": total_attempts,
        "unlock_next": can_unlock_next_concept(mastery, confidence)
    }
