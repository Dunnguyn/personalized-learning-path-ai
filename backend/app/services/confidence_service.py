from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional

from backend.app.database.mongo import get_db


# =====================================================
# ANALYSIS
# =====================================================
# - Quiz confidence needs to stay in [0, 1].
# - MVP confidence is based on accuracy and attempt number.
# - Each quiz submission stores its own confidence_score.
# - Each lesson also keeps an aggregated confidence snapshot for the user.
# - This snapshot can later feed mastery / adaptive learning decisions.


# =====================================================
# PSEUDOCODE
# =====================================================
# calculate_confidence_score(correct_count, total_questions, attempt_number):
# 1. accuracy_score = correct_count / total_questions
# 2. attempt_score = max(0.6, 1 - 0.15 * (attempt_number - 1))
# 3. confidence = 0.75 * accuracy_score + 0.25 * attempt_score
# 4. clamp confidence into [0, 1]
# 5. return confidence
#
# upsert_lesson_confidence_progress(...):
# 1. Load existing lesson progress snapshot for user + lesson
# 2. Derive new mastery from previous mastery and new confidence
# 3. Update attempts, best_confidence, latest attempt metadata
# 4. Persist lesson progress snapshot
#
# get_user_confidence_overview(user_id):
# 1. Load lesson confidence snapshots for the user
# 2. Average confidence and mastery
# 3. Compare recent confidence events to previous period for trend
# 4. Return summary payload for frontend


LESSON_MASTERY_ALPHA = 0.4


def clamp(value: float, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(max_value, value))


def calculate_confidence_score(
    correct_count: int,
    total_questions: int,
    attempt_number: int,
) -> float:
    if total_questions <= 0:
        return 0.0

    accuracy_score = clamp(correct_count / total_questions)
    attempt_score = clamp(max(0.6, 1 - 0.15 * (max(attempt_number, 1) - 1)))
    confidence_score = (0.75 * accuracy_score) + (0.25 * attempt_score)
    return round(clamp(confidence_score), 4)


def derive_lesson_mastery(previous_mastery: float, confidence_score: float) -> float:
    return round(clamp((previous_mastery * (1 - LESSON_MASTERY_ALPHA)) + (confidence_score * LESSON_MASTERY_ALPHA)), 4)


def infer_confidence_band(confidence_score: float) -> str:
    if confidence_score >= 0.8:
        return "high"
    if confidence_score >= 0.6:
        return "medium"
    return "low"


def upsert_lesson_confidence_progress(
    *,
    user_id: str,
    lesson_id: str,
    attempt_id: str,
    attempt_number: int,
    correct_count: int,
    total_questions: int,
    score: float,
    confidence_score: float,
    is_passed: bool,
) -> Dict:
    db = get_db()
    collection = db.lesson_confidence_progress
    existing = collection.find_one({"user_id": user_id, "lesson_id": lesson_id}, {"_id": 0}) or {}

    previous_mastery = float(existing.get("mastery_score", 0.0) or 0.0)
    mastery_score = derive_lesson_mastery(previous_mastery, confidence_score)
    best_confidence_score = max(float(existing.get("best_confidence_score", 0.0) or 0.0), confidence_score)
    now = datetime.utcnow()

    document = {
        "user_id": user_id,
        "lesson_id": lesson_id,
        "latest_attempt_id": attempt_id,
        "attempt_count": max(int(existing.get("attempt_count", 0) or 0), attempt_number),
        "confidence_score": round(confidence_score, 4),
        "best_confidence_score": round(best_confidence_score, 4),
        "mastery_score": mastery_score,
        "correct_count": int(correct_count),
        "total_questions": int(total_questions),
        "score": float(score),
        "is_passed": bool(is_passed),
        "band": infer_confidence_band(confidence_score),
        "updated_at": now,
    }

    collection.update_one(
        {"user_id": user_id, "lesson_id": lesson_id},
        {
            "$set": document,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return document


def record_confidence_event(
    *,
    user_id: str,
    lesson_id: str,
    attempt_id: str,
    confidence_score: float,
    score: float,
    correct_count: int,
    total_questions: int,
    attempt_number: int,
    is_passed: bool,
) -> None:
    db = get_db()
    db.confidence_events.insert_one(
        {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "attempt_id": attempt_id,
            "confidence": round(clamp(confidence_score), 4),
            "score": float(score),
            "correct_count": int(correct_count),
            "total_questions": int(total_questions),
            "attempt_number": int(attempt_number),
            "is_passed": bool(is_passed),
            "source": "lesson_quiz_attempt",
            "created_at": datetime.utcnow(),
        }
    )


def get_attempt_confidence(user_id: str, attempt_id: str) -> Dict:
    db = get_db()
    attempt = db.lesson_quiz_attempts.find_one(
        {"attempt_id": attempt_id, "user_id": user_id},
        {"_id": 0},
    )
    if not attempt:
        raise ValueError(f"Attempt not found: {attempt_id}")

    return {
        "attempt_id": str(attempt["attempt_id"]),
        "lesson_id": str(attempt["lesson_id"]),
        "confidence_score": float(attempt.get("confidence_score", 0.0) or 0.0),
        "correct_count": int(attempt.get("correct_count", 0) or 0),
        "total_questions": int(attempt.get("total_questions", len(attempt.get("selected_question_ids", [])) or 0) or 0),
        "attempt_number": int(attempt.get("attempt_number", 1) or 1),
        "is_passed": bool(attempt.get("is_passed", False)),
        "score": float(attempt.get("score", 0.0) or 0.0),
        "submitted_at": attempt.get("submitted_at"),
    }


def get_lesson_confidence(user_id: str, lesson_id: str) -> Dict:
    db = get_db()
    progress = db.lesson_confidence_progress.find_one(
        {"user_id": user_id, "lesson_id": lesson_id},
        {"_id": 0},
    )
    if not progress:
        raise ValueError(f"Lesson confidence not found for lesson_id={lesson_id}")

    return {
        "lesson_id": str(progress["lesson_id"]),
        "confidence_score": float(progress.get("confidence_score", 0.0) or 0.0),
        "mastery_score": float(progress.get("mastery_score", 0.0) or 0.0),
        "best_confidence_score": float(progress.get("best_confidence_score", 0.0) or 0.0),
        "correct_count": int(progress.get("correct_count", 0) or 0),
        "total_questions": int(progress.get("total_questions", 0) or 0),
        "attempt_number": int(progress.get("attempt_count", 0) or 0),
        "is_passed": bool(progress.get("is_passed", False)),
        "score": float(progress.get("score", 0.0) or 0.0),
        "band": str(progress.get("band", "low")),
        "updated_at": progress.get("updated_at"),
    }


def _average(values: Iterable[float]) -> float:
    series = list(values)
    if not series:
        return 0.0
    return sum(series) / len(series)


def get_user_confidence_overview(user_id: str) -> Dict:
    db = get_db()
    rows: List[Dict] = list(db.lesson_confidence_progress.find({"user_id": user_id}, {"_id": 0}))
    lesson_count = len(rows)
    average_confidence = round(_average(float(row.get("confidence_score", 0.0) or 0.0) for row in rows), 4)
    average_mastery = round(_average(float(row.get("mastery_score", 0.0) or 0.0) for row in rows), 4)
    passed_lessons = sum(1 for row in rows if row.get("is_passed"))

    recent_events: List[Dict] = list(
        db.confidence_events.find({"user_id": user_id, "source": "lesson_quiz_attempt"}, {"_id": 0, "confidence": 1})
        .sort("created_at", -1)
        .limit(10)
    )
    recent_average = round(_average(float(item.get("confidence", 0.0) or 0.0) for item in recent_events), 4)

    return {
        "user_id": user_id,
        "confidence": average_confidence,
        "average_mastery": average_mastery,
        "lesson_count": lesson_count,
        "passed_lessons": passed_lessons,
        "recent_average_confidence": recent_average,
        "details": rows,
    }
