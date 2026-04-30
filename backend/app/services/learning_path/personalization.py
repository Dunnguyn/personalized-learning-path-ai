"""Learning-path personalization helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_learner_model(
    service: Any,
    *,
    profile: Dict[str, Any],
    resolved_subject_id: str,
    resolved_level: str,
    snapshot: Dict[str, Any],
    current_mastery: float,
    weak_concepts: List[str],
    time_budget_minutes: int,
    diagnostic_scores: Dict[str, Any],
    diagnostic_summary: Dict[str, Any],
) -> Dict[str, Any]:
    mastery_by_concept = service._normalize_concept_score_map(
        snapshot.get("mastery_by_concept")
    )
    diagnostic_baseline_by_concept = service._normalize_concept_score_map(
        diagnostic_scores
    )
    combined_mastery_by_concept = dict(diagnostic_baseline_by_concept)
    combined_mastery_by_concept.update(mastery_by_concept)

    diagnostic_average = service._clamp(
        service._safe_float(diagnostic_summary.get("average_score"), current_mastery)
    )
    recent_active_days = int(snapshot.get("recent_active_days") or 0)
    learning_velocity = service._clamp(
        service._safe_float(snapshot.get("learning_velocity"), 0.0)
    )
    engagement_score = service._clamp(
        service._safe_float(snapshot.get("engagement_score"), 0.0)
        or (
            0.5 * service._clamp(recent_active_days / 7.0)
            + 0.5 * service._clamp(
                service._safe_float(snapshot.get("completion_rate"), 0.0)
            )
        )
    )
    frustration_score = service._clamp(
        service._safe_float(snapshot.get("frustration_score"), 0.0)
        or service._safe_float(snapshot.get("fatigue_score"), 0.0)
    )
    friction_score = service._clamp(
        0.45 * frustration_score
        + 0.25 * service._clamp(int(snapshot.get("fail_streak") or 0) / 4.0)
        + 0.15 * service._clamp(1.0 - engagement_score)
        + 0.15
        * service._clamp(
            service._safe_float(snapshot.get("unfinished_resources"), 0.0) / 4.0
        )
    )
    pace_preference = {
        "light": 0.35,
        "steady": 0.6,
        "intensive": 0.85,
    }.get(str(profile.get("learning_pace") or "steady").strip().lower(), 0.6)
    pace_score = service._clamp((0.6 * pace_preference) + (0.4 * learning_velocity))
    time_budget_score = service._clamp(time_budget_minutes / 360.0)

    weak_pool = service._dedupe(
        [
            *weak_concepts,
            *service._low_score_concepts(
                combined_mastery_by_concept, threshold=0.55, limit=5
            ),
            *service._low_score_concepts(
                diagnostic_baseline_by_concept, threshold=0.5, limit=4
            ),
        ],
        limit=6,
    )

    return {
        "version": "learner_model_v1",
        "subject_id": resolved_subject_id,
        "level": resolved_level,
        "current_mastery": round(service._clamp(current_mastery), 4),
        "mastery_by_concept": mastery_by_concept,
        "combined_mastery_by_concept": combined_mastery_by_concept,
        "weak_concepts": weak_pool,
        "pace_score": round(pace_score, 4),
        "time_budget_score": round(time_budget_score, 4),
        "diagnostic_baseline": round(diagnostic_average, 4),
        "diagnostic_baseline_by_concept": diagnostic_baseline_by_concept,
        "engagement_score": round(engagement_score, 4),
        "friction_score": round(friction_score, 4),
        "learning_velocity": round(learning_velocity, 4),
        "risk_level": str(snapshot.get("risk_level") or "low"),
        "recent_active_days": recent_active_days,
        "avg_session_duration": round(
            service._safe_float(snapshot.get("avg_session_duration"), 0.0), 2
        ),
        "quiz_accuracy": round(
            service._safe_float(snapshot.get("quiz_accuracy"), 0.0), 4
        ),
        "completion_rate": round(
            service._safe_float(snapshot.get("completion_rate"), 0.0), 4
        ),
        "fail_streak": int(snapshot.get("fail_streak") or 0),
        "retry_count": int(snapshot.get("retry_count") or 0),
        "preferred_time_window": str(snapshot.get("preferred_time_window") or "evening"),
        "recovery_need_flag": bool(snapshot.get("recovery_need_flag")),
    }


def lesson_priority_score(
    service: Any,
    *,
    lesson: Dict[str, Any],
    learner_model: Dict[str, Any],
    planned_concepts: set[str],
    order_index: int,
) -> Dict[str, Any]:
    target_concepts = [
        service._normalize_concept_key(item)
        for item in (lesson.get("target_concepts") or [])
        if service._normalize_concept_key(item)
    ]
    prerequisite_concepts = [
        service._normalize_concept_key(item)
        for item in (lesson.get("prerequisite_concepts") or [])
        if service._normalize_concept_key(item)
    ]
    mastery_by_concept = service._normalize_concept_score_map(
        learner_model.get("combined_mastery_by_concept")
        or learner_model.get("mastery_by_concept")
    )
    diagnostic_by_concept = service._normalize_concept_score_map(
        learner_model.get("diagnostic_baseline_by_concept")
    )
    weak_concepts = {
        service._normalize_concept_key(item)
        for item in (learner_model.get("weak_concepts") or [])
        if service._normalize_concept_key(item)
    }
    friction_score = service._safe_float(learner_model.get("friction_score"), 0.0)
    pace_score = service._safe_float(learner_model.get("pace_score"), 0.0)
    time_budget_score = service._safe_float(
        learner_model.get("time_budget_score"), 0.0
    )
    diagnostic_baseline = service._safe_float(
        learner_model.get("diagnostic_baseline"), 0.0
    )
    lesson_kind = str(lesson.get("lesson_kind") or "core").strip().lower() or "core"
    difficulty = max(1, min(int(lesson.get("difficulty") or 1), 10))
    difficulty_norm = difficulty / 10.0

    weak_overlap = (
        sum(1 for concept in target_concepts if concept in weak_concepts)
        / max(len(target_concepts), 1)
    )
    prerequisite_gap = (
        sum(
            1.0 - mastery_by_concept.get(concept, diagnostic_by_concept.get(concept, 0.45))
            for concept in prerequisite_concepts
        )
        / max(len(prerequisite_concepts), 1)
        if prerequisite_concepts
        else 0.0
    )
    target_mastery_need = (
        sum(
            1.0 - mastery_by_concept.get(concept, diagnostic_by_concept.get(concept, 0.45))
            for concept in target_concepts
        )
        / max(len(target_concepts), 1)
        if target_concepts
        else max(0.2, 1.0 - diagnostic_baseline)
    )
    novelty_ratio = (
        sum(1 for concept in target_concepts if concept not in planned_concepts)
        / max(len(target_concepts), 1)
    )
    prerequisite_ready_ratio = (
        sum(
            1
            for concept in prerequisite_concepts
            if mastery_by_concept.get(concept, diagnostic_by_concept.get(concept, 0.0))
            >= service.PREREQUISITE_MASTERY_THRESHOLD
        )
        / max(len(prerequisite_concepts), 1)
        if prerequisite_concepts
        else 1.0
    )
    bridge_bonus = 1.0 if lesson_kind == "bridge" and diagnostic_baseline < 0.55 else 0.0
    challenge_bonus = (
        0.12 if pace_score >= 0.72 and difficulty_norm >= 0.55 and friction_score <= 0.45 else 0.0
    )
    review_penalty = 0.18 if lesson_kind == "review" and weak_overlap < 0.3 else 0.0
    repeated_penalty = 0.1 if novelty_ratio < 0.34 and weak_overlap < 0.34 else 0.0

    score = (
        0.32 * target_mastery_need
        + 0.22 * weak_overlap
        + 0.16 * prerequisite_gap
        + 0.12 * novelty_ratio
        + 0.08 * bridge_bonus
        + 0.07 * (1.0 - abs(difficulty_norm - max(pace_score, 0.35)))
        + 0.03 * time_budget_score
        + challenge_bonus
        - review_penalty
        - repeated_penalty
    )

    if prerequisite_concepts and prerequisite_ready_ratio < 0.45:
        score -= 0.12
    if friction_score >= 0.7 and difficulty_norm > 0.7:
        score -= 0.1

    reasons: List[str] = []
    if weak_overlap >= 0.34:
        reasons.append("targets a current weak concept")
    if prerequisite_gap >= 0.4:
        reasons.append("repairs a prerequisite gap before later lessons")
    if lesson_kind == "bridge" and bridge_bonus >= 0.45:
        reasons.append("acts as a bridge lesson for low baseline knowledge")
    if friction_score >= 0.65 and difficulty <= 4:
        reasons.append("keeps difficulty controlled because recent friction is high")
    if time_budget_score <= 0.4 and difficulty <= 4:
        reasons.append("fits the learner time budget")
    if challenge_bonus > 0:
        reasons.append("keeps momentum by adding more challenge")
    if not reasons:
        reasons.append("maintains concept order while matching the learner profile")

    return {
        "score": round(max(score, 0.05), 4),
        "reasons": reasons[:3],
        "prerequisite_ready_ratio": round(service._clamp(prerequisite_ready_ratio), 4),
    }


def prioritize_curriculum(
    service: Any,
    *,
    chapters: List[Dict[str, Any]],
    learner_model: Dict[str, Any],
) -> List[Dict[str, Any]]:
    chapter_titles = [
        str(chapter.get("title") or "").strip()
        for chapter in chapters or []
        if str(chapter.get("title") or "").strip()
    ]
    flat_lessons: List[Dict[str, Any]] = []
    original_index = 0
    for chapter_index, chapter in enumerate(chapters or [], start=1):
        for lesson_index, lesson in enumerate(chapter.get("lessons", []) or [], start=1):
            original_index += 1
            lesson_copy = dict(lesson)
            lesson_copy["_original_index"] = original_index
            lesson_copy["_original_chapter_index"] = chapter_index
            lesson_copy["_original_lesson_index"] = lesson_index
            flat_lessons.append(lesson_copy)

    if len(flat_lessons) <= 1:
        return chapters

    planned_concepts: set[str] = set()
    remaining = list(flat_lessons)
    ordered: List[Dict[str, Any]] = []

    while remaining:
        eligible: List[Dict[str, Any]] = []
        for lesson in remaining:
            prereqs = [
                service._normalize_concept_key(item)
                for item in (lesson.get("prerequisite_concepts") or [])
                if service._normalize_concept_key(item)
            ]
            if not prereqs:
                eligible.append(lesson)
                continue
            unresolved = [
                concept
                for concept in prereqs
                if concept not in planned_concepts
                and service._safe_float(
                    (learner_model.get("combined_mastery_by_concept") or {}).get(
                        concept
                    ),
                    0.0,
                )
                < service.PREREQUISITE_MASTERY_THRESHOLD
            ]
            if not unresolved:
                eligible.append(lesson)

        candidate_pool = eligible or remaining
        scored_candidates: List[tuple[float, int, Dict[str, Any], Dict[str, Any]]] = []
        for lesson in candidate_pool:
            score_payload = lesson_priority_score(
                service,
                lesson=lesson,
                learner_model=learner_model,
                planned_concepts=planned_concepts,
                order_index=int(lesson.get("_original_index") or 0),
            )
            scored_candidates.append(
                (
                    float(score_payload["score"]),
                    -int(lesson.get("_original_index") or 0),
                    lesson,
                    score_payload,
                )
            )
        scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _score, _neg_original_index, chosen, score_payload = scored_candidates[0]
        chosen_copy = dict(chosen)
        chosen_copy["priority_score"] = score_payload["score"]
        chosen_copy["priority_reasons"] = list(score_payload["reasons"])
        chosen_copy["why_this_lesson_now"] = "; ".join(score_payload["reasons"])
        chosen_copy["prerequisite_ready_ratio"] = score_payload[
            "prerequisite_ready_ratio"
        ]
        ordered.append(chosen_copy)
        planned_concepts.update(
            service._normalize_concept_key(item)
            for item in (chosen_copy.get("target_concepts") or [])
            if service._normalize_concept_key(item)
        )
        remaining = [item for item in remaining if item is not chosen]

    chapter_count = max(len(chapter_titles), 1)
    chunk_size = int(__import__("math").ceil(len(ordered) / float(chapter_count))) if ordered else 1
    chapters_out: List[Dict[str, Any]] = []
    cursor = 0
    for chapter_index in range(chapter_count):
        lesson_slice = ordered[cursor : cursor + chunk_size]
        cursor += chunk_size
        if not lesson_slice:
            continue
        chapter_title = (
            chapter_titles[chapter_index]
            if chapter_index < len(chapter_titles)
            else f"Concept Block {chapter_index + 1}"
        )
        normalized_lessons: List[Dict[str, Any]] = []
        for lesson in lesson_slice:
            lesson_out = dict(lesson)
            lesson_out.pop("_original_index", None)
            lesson_out.pop("_original_chapter_index", None)
            lesson_out.pop("_original_lesson_index", None)
            normalized_lessons.append(lesson_out)
        chapters_out.append({"title": chapter_title, "lessons": normalized_lessons})
    return chapters_out


def user_profile(service: Any, user_id: Optional[str]) -> Dict[str, Any]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return {}
    context = service.learner_profile_service.personalization_context(
        user_id=normalized_user_id
    )
    profile = dict(context.get("profile") or {})
    return {
        "user_id": normalized_user_id,
        "level": str(context.get("level") or profile.get("level") or "beginner")
        .strip()
        .lower(),
        "learning_goal": str(
            context.get("goal") or profile.get("learning_goal") or ""
        ).strip(),
        "time_budget_minutes": int(context.get("time_budget_minutes") or 0),
        "preferred_resource_type": str(
            context.get("preferred_resource_type")
            or profile.get("preferred_resource_type")
            or "mixed"
        ),
        "learning_pace": str(
            context.get("learning_pace") or profile.get("learning_pace") or "steady"
        ),
        "target_role": profile.get("target_role"),
        "target_outcome": profile.get("target_outcome"),
        "desired_deadline": profile.get("desired_deadline"),
        "prior_knowledge_by_subject": dict(profile.get("prior_knowledge_by_subject") or {}),
        "diagnostic_summary_by_subject": dict(
            profile.get("diagnostic_summary_by_subject") or {}
        ),
        "diagnostic_scores_by_subject": dict(
            profile.get("diagnostic_scores_by_subject") or {}
        ),
    }


def latest_path(
    service: Any,
    *,
    user_id: Optional[str],
    subject_id: Optional[str] = None,
    goal: Optional[str] = None,
    level: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return None
    query: Dict[str, Any] = {"user_id": normalized_user_id}
    if subject_id:
        query["subject_id"] = str(subject_id).strip().lower()
    if goal:
        query["goal"] = str(goal).strip()
    if level:
        query["level"] = str(level).strip().lower()
    return service.learning_path_repository.collection.find_one(
        query,
        sort=[("updated_at", -1), ("created_at", -1)],
    )


def subject_id(
    service: Any,
    *,
    subject_id: Optional[str],
    goal: Optional[str],
    profile: Dict[str, Any],
    latest_path: Optional[Dict[str, Any]],
) -> str:
    get_subject_label = service._get_subject_label_helper
    normalized = str(subject_id or "").strip().lower()
    if get_subject_label(normalized):
        return normalized
    latest_subject = str((latest_path or {}).get("subject_id") or "").strip().lower()
    if get_subject_label(latest_subject):
        return latest_subject
    haystack = " ".join(
        [str(goal or ""), str(profile.get("learning_goal") or "")]
    ).lower()
    for candidate, hints in service._SUBJECT_HINTS.items():
        if any(hint in haystack for hint in hints):
            return candidate
    return "python"


def completion_history(
    service: Any,
    user_id: Optional[str],
    *,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return []
    documents = list(
        service.learning_path_repository.collection.find(
            {
                "user_id": normalized_user_id
            },
            {
                "path_id": 1,
                "goal": 1,
                "subject_id": 1,
                "level": 1,
                "lesson_progress": 1,
                "updated_at": 1,
                "created_at": 1,
            },
        )
        .sort([("updated_at", -1), ("created_at", -1)])
        .limit(limit)
    )
    history: List[Dict[str, Any]] = []
    for document in documents:
        lesson_progress = dict(document.get("lesson_progress") or {})
        total_lessons = len(lesson_progress)
        completed_lessons = sum(
            1
            for status in lesson_progress.values()
            if service._status(status) == "completed"
        )
        history.append(
            {
                "path_id": str(document.get("path_id") or ""),
                "subject_id": str(document.get("subject_id") or ""),
                "goal": str(document.get("goal") or ""),
                "level": str(document.get("level") or "beginner"),
                "completion_rate": round(
                    (completed_lessons / total_lessons) if total_lessons else 0.0, 4
                ),
                "completed_lessons": completed_lessons,
                "total_lessons": total_lessons,
                "updated_at": service._resolve_generated_at(document).isoformat(),
            }
        )
    return history
