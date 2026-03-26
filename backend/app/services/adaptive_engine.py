from typing import Any, Dict, List, Optional
from enum import Enum
import logging
import os

logger = logging.getLogger(__name__)


# =====================================================
# ADAPTIVE MODE ENUM
# =====================================================
class LearningMode(str, Enum):
    """Adaptive learning modes"""

    REMEDIAL = "remedial"  # học lại / bổ trợ (mastery < 0.5)
    NORMAL = "normal"  # học theo lộ trình chuẩn (default)
    ADVANCED = "advanced"  # tăng tốc / nâng cao (mastery >= 0.8)


# =====================================================
# CONFIG (from env, fallback defaults)
# =====================================================
class AdaptiveConfig:
    """Configuration for adaptive engine (externalize from code)"""

    # Mastery thresholds
    MASTERY_LOW = float(os.getenv("ADAPTIVE_MASTERY_LOW", "0.5"))
    MASTERY_HIGH = float(os.getenv("ADAPTIVE_MASTERY_HIGH", "0.8"))

    # Confidence thresholds
    CONFIDENCE_LOW = float(os.getenv("ADAPTIVE_CONFIDENCE_LOW", "0.4"))
    CONFIDENCE_HIGH = float(os.getenv("ADAPTIVE_CONFIDENCE_HIGH", "0.75"))

    # Attempt thresholds
    MAX_ATTEMPTS_FOR_ADVANCE = int(os.getenv("ADAPTIVE_MAX_ATTEMPTS_ADVANCE", "3"))
    MIN_ATTEMPTS_FOR_UNLOCK = int(os.getenv("ADAPTIVE_MIN_ATTEMPTS_UNLOCK", "1"))

    # Unlock next concept thresholds
    UNLOCK_MASTERY_THRESHOLD = float(os.getenv("ADAPTIVE_UNLOCK_MASTERY", "0.6"))
    UNLOCK_CONFIDENCE_THRESHOLD = float(os.getenv("ADAPTIVE_UNLOCK_CONFIDENCE", "0.5"))

    # Bloom levels for filtering
    REMEDIAL_BLOOM_LEVELS = ("remember", "understand")
    NORMAL_BLOOM_LEVELS = ("remember", "understand", "apply")
    ADVANCED_BLOOM_LEVELS = ("apply", "analyze", "evaluate", "create")

    @classmethod
    def validate(cls):
        """Validate config values"""
        assert (
            0 <= cls.MASTERY_LOW < cls.MASTERY_HIGH <= 1
        ), "Invalid mastery thresholds"
        assert (
            0 <= cls.CONFIDENCE_LOW < cls.CONFIDENCE_HIGH <= 1
        ), "Invalid confidence thresholds"
        assert (
            cls.MAX_ATTEMPTS_FOR_ADVANCE > 0
        ), "MAX_ATTEMPTS_FOR_ADVANCE must be positive"
        logger.info(
            f"Adaptive config loaded: "
            f"mastery=[{cls.MASTERY_LOW}, {cls.MASTERY_HIGH}], "
            f"confidence=[{cls.CONFIDENCE_LOW}, {cls.CONFIDENCE_HIGH}], "
            f"max_attempts={cls.MAX_ATTEMPTS_FOR_ADVANCE}"
        )


# Validate on import
try:
    AdaptiveConfig.validate()
except AssertionError as e:
    logger.error(f"Invalid adaptive config: {e}")
    raise


# =====================================================
# CORE ADAPTIVE DECISION
# =====================================================
def decide_learning_mode(
    mastery: float, confidence: float, total_attempts: int
) -> LearningMode:
    """
    Quyết định chế độ học tập dựa trên tiến độ người học.

    Decision tree:
    1. If mastery < LOW OR confidence < LOW → REMEDIAL (need reteach)
    2. Else if mastery >= HIGH AND confidence >= HIGH AND attempts <= MAX → ADVANCED (skip ahead)
    3. Else → NORMAL (standard path)

    Parameters
    ----------
    mastery : float (0.0 – 1.0)
        Mức độ nắm vững kiến thức
    confidence : float (0.0 – 1.0)
        Độ tự tin / ổn định học tập (AI-evaluated)
    total_attempts : int
        Số lần học / thử

    Returns
    -------
    LearningMode : remedial | normal | advanced

    Examples
    --------
    >>> decide_learning_mode(0.3, 0.3, 1)  # Poor mastery
    <LearningMode.REMEDIAL>

    >>> decide_learning_mode(0.85, 0.8, 1)  # High mastery, few attempts
    <LearningMode.ADVANCED>

    >>> decide_learning_mode(0.6, 0.6, 5)  # Medium mastery, many attempts
    <LearningMode.NORMAL>
    """

    # Validate inputs
    mastery = max(0.0, min(mastery, 1.0))
    confidence = max(0.0, min(confidence, 1.0))
    total_attempts = max(0, total_attempts)

    # Decision logic
    # Case 1: Poor mastery or confidence → REMEDIAL
    if (
        mastery < AdaptiveConfig.MASTERY_LOW
        or confidence < AdaptiveConfig.CONFIDENCE_LOW
    ):
        mode = LearningMode.REMEDIAL
        logger.debug(
            f"Mode: REMEDIAL (mastery={mastery:.2f}<{AdaptiveConfig.MASTERY_LOW}, "
            f"confidence={confidence:.2f}<{AdaptiveConfig.CONFIDENCE_LOW})"
        )
        return mode

    # Case 2: High mastery + high confidence + few attempts → ADVANCED
    if (
        mastery >= AdaptiveConfig.MASTERY_HIGH
        and confidence >= AdaptiveConfig.CONFIDENCE_HIGH
        and total_attempts <= AdaptiveConfig.MAX_ATTEMPTS_FOR_ADVANCE
    ):
        mode = LearningMode.ADVANCED
        logger.debug(
            f"Mode: ADVANCED (mastery={mastery:.2f}>={AdaptiveConfig.MASTERY_HIGH}, "
            f"confidence={confidence:.2f}>={AdaptiveConfig.CONFIDENCE_HIGH}, "
            f"attempts={total_attempts}<={AdaptiveConfig.MAX_ATTEMPTS_FOR_ADVANCE})"
        )
        return mode

    # Case 3: Default → NORMAL
    mode = LearningMode.NORMAL
    logger.debug(
        f"Mode: NORMAL (mastery={mastery:.2f}, confidence={confidence:.2f}, attempts={total_attempts})"
    )
    return mode


# =====================================================
# RESOURCE FILTERING BY MODE
# =====================================================
def filter_resources_by_mode(resources: List[Dict], mode: LearningMode) -> List[Dict]:
    """
    Filter tài nguyên học tập theo chế độ học (Bloom taxonomy).

    - REMEDIAL: only basic levels (remember, understand)
    - NORMAL: all levels including apply
    - ADVANCED: high-order thinking (analyze, evaluate, create)

    Parameters
    ----------
    resources : List[Dict]
        List of resources with optional `bloom_level` field
    mode : LearningMode
        Current learning mode

    Returns
    -------
    List[Dict] : filtered resources

    Examples
    --------
    >>> resources = [
    ...     {"id": 1, "bloom_level": "remember"},
    ...     {"id": 2, "bloom_level": "analyze"},
    ... ]
    >>> filtered = filter_resources_by_mode(resources, LearningMode.REMEDIAL)
    >>> [r["id"] for r in filtered]
    [1]
    """

    if not resources:
        return []

    # Map mode to acceptable Bloom levels
    bloom_levels_map = {
        LearningMode.REMEDIAL: AdaptiveConfig.REMEDIAL_BLOOM_LEVELS,
        LearningMode.NORMAL: AdaptiveConfig.NORMAL_BLOOM_LEVELS,
        LearningMode.ADVANCED: AdaptiveConfig.ADVANCED_BLOOM_LEVELS,
    }

    allowed_levels = bloom_levels_map.get(mode, AdaptiveConfig.NORMAL_BLOOM_LEVELS)

    # Filter resources
    filtered = [
        r
        for r in resources
        if r.get("bloom_level") in allowed_levels or "bloom_level" not in r
    ]

    logger.debug(
        f"Filtered resources: mode={mode.value}, "
        f"original={len(resources)}, filtered={len(filtered)}"
    )

    return filtered


# =====================================================
# UNLOCK NEXT CONCEPT CHECK
# =====================================================
def can_unlock_next_concept(
    mastery: float, confidence: float, total_attempts: int = 0
) -> bool:
    """
    Kiểm tra có được mở khóa concept tiếp theo hay không.

    Requirements:
    - mastery >= threshold (typically 0.6)
    - confidence >= threshold (typically 0.5)
    - Optional: attempts >= minimum (prevent trivial wins)

    Parameters
    ----------
    mastery : float
        Current mastery score [0, 1]
    confidence : float
        Current confidence score [0, 1]
    total_attempts : int
        Number of attempts (optional)

    Returns
    -------
    bool : True if ready for next concept
    """

    mastery = max(0.0, min(mastery, 1.0))
    confidence = max(0.0, min(confidence, 1.0))
    total_attempts = max(0, total_attempts)

    # Check thresholds
    can_unlock = (
        mastery >= AdaptiveConfig.UNLOCK_MASTERY_THRESHOLD
        and confidence >= AdaptiveConfig.UNLOCK_CONFIDENCE_THRESHOLD
        and total_attempts >= AdaptiveConfig.MIN_ATTEMPTS_FOR_UNLOCK
    )

    logger.debug(
        f"Unlock check: mastery={mastery:.2f}, confidence={confidence:.2f}, "
        f"attempts={total_attempts} → {can_unlock}"
    )

    return can_unlock


# =====================================================
# DIFFICULTY RECOMMENDATION
# =====================================================
def recommend_difficulty_boost(
    mastery: float, confidence: float, current_difficulty: int
) -> int:
    """
    Recommend next difficulty level based on performance.

    - If mastery + confidence very high → increase difficulty
    - If mastery + confidence low → decrease difficulty
    - Else → same difficulty

    Parameters
    ----------
    mastery : float
        Current mastery [0, 1]
    confidence : float
        Current confidence [0, 1]
    current_difficulty : int
        Current difficulty level (1-10)

    Returns
    -------
    int : recommended difficulty (-1, 0, or +1 adjustment)
    """

    combined_score = (mastery + confidence) / 2

    # High performance → increase
    if combined_score >= 0.85:
        logger.debug(f"Recommend difficulty +1 (score={combined_score:.2f})")
        return min(current_difficulty + 1, 10)

    # Low performance → decrease
    if combined_score < 0.4:
        logger.debug(f"Recommend difficulty -1 (score={combined_score:.2f})")
        return max(current_difficulty - 1, 1)

    # Medium → keep same
    logger.debug(f"Keep difficulty (score={combined_score:.2f})")
    return current_difficulty


# =====================================================
# ADAPTIVE PRACTICE RECOMMENDATIONS
# =====================================================
def get_practice_recommendations(
    mastery: float, confidence: float, total_attempts: int
) -> Dict[str, Any]:
    """
    Get personalized practice recommendations based on performance.

    Returns dict with:
    - practice_type: "drill" | "spaced_review" | "challenge"
    - intensity: number of repetitions/difficulty
    - urgency: "immediate" | "soon" | "optional"

    Parameters
    ----------
    mastery : float
        Current mastery
    confidence : float
        Current confidence
    total_attempts : int
        Number of attempts

    Returns
    -------
    Dict : practice recommendations
    """

    mode = decide_learning_mode(mastery, confidence, total_attempts)
    combined = (mastery + confidence) / 2

    if mode == LearningMode.REMEDIAL:
        return {
            "practice_type": "drill",
            "intensity": 5,  # 5 repetitions
            "urgency": "immediate",
            "description": "Basic drilling needed to build foundation",
        }

    elif mode == LearningMode.ADVANCED:
        return {
            "practice_type": "challenge",
            "intensity": 3,  # 3 challenging problems
            "urgency": "optional",
            "description": "Advanced challenges to deepen mastery",
        }

    else:  # NORMAL
        if combined < 0.6:
            return {
                "practice_type": "spaced_review",
                "intensity": 4,
                "urgency": "soon",
                "description": "Regular review to consolidate learning",
            }
        else:
            return {
                "practice_type": "spaced_review",
                "intensity": 2,
                "urgency": "optional",
                "description": "Periodic review to maintain mastery",
            }


# =====================================================
# COMPREHENSIVE ADAPTIVE SUMMARY
# =====================================================
def adaptive_decision_summary(
    mastery: float, confidence: float, total_attempts: int, current_difficulty: int = 5
) -> Dict:
    """
    Comprehensive adaptive decision summary for logging/API response.

    Returns all adaptive metrics in one dict for clarity.

    Parameters
    ----------
    mastery : float
        Current mastery
    confidence : float
        Current confidence
    total_attempts : int
        Number of attempts
    current_difficulty : int
        Current difficulty level

    Returns
    -------
    Dict : complete adaptive summary

    Example
    -------
    {
        "mode": "advanced",
        "mastery": 0.85,
        "confidence": 0.8,
        "attempts": 2,
        "can_unlock_next": True,
        "recommended_difficulty": 6,
        "practice_recommendation": {...}
    }
    """

    mode = decide_learning_mode(mastery, confidence, total_attempts)
    can_unlock = can_unlock_next_concept(mastery, confidence, total_attempts)
    recommended_difficulty = recommend_difficulty_boost(
        mastery, confidence, current_difficulty
    )
    practice_recs = get_practice_recommendations(mastery, confidence, total_attempts)

    summary = {
        "mode": mode.value,
        "mastery": round(mastery, 3),
        "confidence": round(confidence, 3),
        "attempts": total_attempts,
        "combined_score": round((mastery + confidence) / 2, 3),
        "can_unlock_next": can_unlock,
        "recommended_difficulty": recommended_difficulty,
        "practice_recommendation": practice_recs,
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(f"Adaptive summary: {summary}")
    return summary


# =====================================================
# BATCH ADAPTIVE DECISIONS (for multiple resources)
# =====================================================
def rank_resources_by_adaptiveness(
    resources: List[Dict], mastery: float, confidence: float, total_attempts: int
) -> List[Dict]:
    """
    Rank resources by how adaptive/suitable they are for current state.

    Scoring factors:
    - Bloom level match (50%)
    - Difficulty adjustment (30%)
    - Recency (20%)

    Parameters
    ----------
    resources : List[Dict]
        Resources with fields: bloom_level, difficulty, created_at
    mastery : float
        Current mastery
    confidence : float
        Current confidence
    total_attempts : int
        Number of attempts

    Returns
    -------
    List[Dict] : resources ranked by adaptiveness
    """

    mode = decide_learning_mode(mastery, confidence, total_attempts)

    # Filter by mode first
    filtered = filter_resources_by_mode(resources, mode)

    if not filtered:
        logger.warning(f"No resources match mode {mode.value}")
        return []

    # Score each resource
    scored = []
    for r in filtered:
        score = 0

        # 1. Bloom level match (50%)
        bloom_match = r.get("bloom_level") in AdaptiveConfig.NORMAL_BLOOM_LEVELS
        score += 50 if bloom_match else 25

        # 2. Difficulty alignment (30%)
        resource_difficulty = r.get("difficulty", 5)
        recommended_difficulty = recommend_difficulty_boost(mastery, confidence, 5)

        if abs(resource_difficulty - recommended_difficulty) <= 1:
            score += 30
        elif abs(resource_difficulty - recommended_difficulty) <= 2:
            score += 15

        # 3. Recency (20%)
        from datetime import datetime, timedelta

        created_at = r.get("created_at")
        if created_at:
            days_old = (datetime.utcnow() - created_at).days
            if days_old <= 7:
                score += 20
            elif days_old <= 30:
                score += 10
        else:
            score += 20  # Default high if unknown

        scored.append({**r, "adaptiveness_score": round(score, 1)})

    # Sort by score
    scored.sort(key=lambda x: x["adaptiveness_score"], reverse=True)

    logger.debug(
        f"Ranked {len(scored)} resources by adaptiveness for mode {mode.value}"
    )

    return scored


# =====================================================
# UNIT TEST HELPERS
# =====================================================
if __name__ == "__main__":
    # Quick validation
    print("Adaptive Engine Tests")
    print("=" * 50)

    test_cases = [
        (0.3, 0.3, 1, LearningMode.REMEDIAL),
        (0.85, 0.8, 1, LearningMode.ADVANCED),
        (0.6, 0.6, 5, LearningMode.NORMAL),
        (0.9, 0.5, 2, LearningMode.NORMAL),  # High mastery but low confidence
    ]

    for mastery, confidence, attempts, expected_mode in test_cases:
        mode = decide_learning_mode(mastery, confidence, attempts)
        status = "✓" if mode == expected_mode else "✗"
        print(
            f"{status} decide_learning_mode({mastery}, {confidence}, {attempts}) = {mode.value}"
        )

    print()
    print("Unlock criteria tests:")
    print("-" * 50)

    unlock_cases = [
        (0.5, 0.4, 1, False),  # Below threshold
        (0.6, 0.5, 1, True),  # At threshold
        (0.8, 0.8, 0, False),  # No attempts yet
    ]

    for mastery, confidence, attempts, expected in unlock_cases:
        can_unlock = can_unlock_next_concept(mastery, confidence, attempts)
        status = "✓" if can_unlock == expected else "✗"
        print(
            f"{status} can_unlock_next({mastery}, {confidence}, {attempts}) = {can_unlock}"
        )

    print()
    print("Adaptive summary:")
    print("-" * 50)
    summary = adaptive_decision_summary(0.75, 0.7, 2)
    for key, value in summary.items():
        print(f"  {key}: {value}")
