"""Unified learning-path orchestration shared across product flows."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import math
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.services.learning_path.chapter_lesson_builder import (
    adaptation_metadata as build_lesson_adaptation_metadata,
    generate_curriculum_chapter as generate_learning_path_chapter,
    generate_curriculum_outline as generate_learning_path_outline,
    resource_payload as build_learning_path_resource_payload,
)
from backend.app.services.learning_path.concept_graph_builder import (
    stable_concept_numeric_id as build_stable_concept_numeric_id,
)
from backend.app.services.learning_path.persistence import (
    build_recommended_path as build_learning_path_recommended_path,
    normalize_chapters as normalize_learning_path_chapters,
    serialize_learning_path as serialize_unified_learning_path,
)
from backend.app.services.learning_path.personalization import (
    build_learner_model as build_learning_path_learner_model,
    completion_history as collect_learning_path_completion_history,
    latest_path as resolve_latest_learning_path,
    lesson_priority_score as score_learning_path_lesson_priority,
    prioritize_curriculum as prioritize_learning_path_curriculum,
    subject_id as resolve_learning_path_subject_id,
    user_profile as resolve_learning_path_user_profile,
)
from backend.app.services.learning_path_prompt_builder import (
    build_fallback_curriculum,
    build_learning_path_prompt,
    build_learning_path_enrichment_prompt,
    build_learning_path_chapter_prompt,
    build_learning_path_outline_prompt,
    extract_json_object,
    get_subject_label,
    normalize_curriculum,
)
from backend.app.services.concept_graph_service import concept_graph_service
from backend.app.services.learning_path_service import HybridLearningPathService
from backend.app.services.learner_state_service import learner_state_service
from backend.app.services.learner_profile_service import learner_profile_service

logger = logging.getLogger(__name__)

UNIFIED_CURRICULUM_ENRICH_MAX_OUTPUT_TOKENS = 2400
UNIFIED_CURRICULUM_DYNAMIC_PLAN_MAX_OUTPUT_TOKENS = 2800
UNIFIED_CURRICULUM_GENERATION_MODE = (
    os.getenv("UNIFIED_LEARNING_PATH_CURRICULUM_MODE", "legacy_strict")
    .strip()
    .lower()
)


class UnifiedLearningPathService(HybridLearningPathService):
    PREREQUISITE_MASTERY_THRESHOLD = 0.7
    _SUBJECT_HINTS: Dict[str, tuple[str, ...]] = {
        "python": ("python", "fastapi", "django", "flask", "numpy", "pandas"),
        "cpp": ("c++", "cpp", "stl"),
        "csharp": ("c#", "csharp", ".net", "asp.net"),
        "java": ("java", "spring", "jvm"),
        "web": ("web", "frontend", "html", "css", "javascript", "typescript", "react"),
    }

    def __init__(self) -> None:
        super().__init__()
        self.db = get_db()
        self.learner_state_service = learner_state_service
        self.learner_profile_service = learner_profile_service

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _dedupe(values: List[Any], *, limit: int = 5) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _status(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"complete", "completed"}:
            return "completed"
        if normalized == "in_progress":
            return normalized
        return "not_started"

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _normalize_concept_key(value: Any) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower())
        return normalized.strip("_")

    @classmethod
    def _normalize_concept_score_map(cls, value: Any) -> Dict[str, float]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, float] = {}
        for key, raw_score in value.items():
            concept_key = cls._normalize_concept_key(key)
            if not concept_key:
                continue
            normalized[concept_key] = round(cls._clamp(cls._safe_float(raw_score, 0.0)), 4)
        return normalized

    @classmethod
    def _low_score_concepts(
        cls,
        score_map: Dict[str, float],
        *,
        threshold: float,
        limit: int,
    ) -> List[str]:
        ranked = sorted(
            score_map.items(),
            key=lambda item: (item[1], item[0]),
        )
        return [
            concept_id
            for concept_id, score in ranked
            if score <= threshold
        ][:limit]

    def _build_learner_model(
        self,
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
        mastery_by_concept = self._normalize_concept_score_map(
            snapshot.get("mastery_by_concept")
        )
        diagnostic_baseline_by_concept = self._normalize_concept_score_map(
            diagnostic_scores
        )
        combined_mastery_by_concept = dict(diagnostic_baseline_by_concept)
        combined_mastery_by_concept.update(mastery_by_concept)

        diagnostic_average = self._clamp(
            self._safe_float(diagnostic_summary.get("average_score"), current_mastery)
        )
        recent_active_days = int(snapshot.get("recent_active_days") or 0)
        learning_velocity = self._clamp(
            self._safe_float(snapshot.get("learning_velocity"), 0.0)
        )
        engagement_score = self._clamp(
            self._safe_float(snapshot.get("engagement_score"), 0.0)
            or (
                0.5 * self._clamp(recent_active_days / 7.0)
                + 0.5 * self._clamp(
                    self._safe_float(snapshot.get("completion_rate"), 0.0)
                )
            )
        )
        frustration_score = self._clamp(
            self._safe_float(snapshot.get("frustration_score"), 0.0)
            or self._safe_float(snapshot.get("fatigue_score"), 0.0)
        )
        friction_score = self._clamp(
            0.45 * frustration_score
            + 0.25 * self._clamp(int(snapshot.get("fail_streak") or 0) / 4.0)
            + 0.15 * self._clamp(1.0 - engagement_score)
            + 0.15 * self._clamp(
                self._safe_float(snapshot.get("unfinished_resources"), 0.0) / 4.0
            )
        )
        pace_preference = {
            "light": 0.35,
            "steady": 0.6,
            "intensive": 0.85,
        }.get(str(profile.get("learning_pace") or "steady").strip().lower(), 0.6)
        pace_score = self._clamp((0.6 * pace_preference) + (0.4 * learning_velocity))
        time_budget_score = self._clamp(time_budget_minutes / 360.0)

        weak_pool = self._dedupe(
            [
                *weak_concepts,
                *self._low_score_concepts(combined_mastery_by_concept, threshold=0.55, limit=5),
                *self._low_score_concepts(diagnostic_baseline_by_concept, threshold=0.5, limit=4),
            ],
            limit=6,
        )

        return {
            "version": "learner_model_v1",
            "subject_id": resolved_subject_id,
            "level": resolved_level,
            "current_mastery": round(self._clamp(current_mastery), 4),
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
                self._safe_float(snapshot.get("avg_session_duration"), 0.0), 2
            ),
            "quiz_accuracy": round(
                self._safe_float(snapshot.get("quiz_accuracy"), 0.0), 4
            ),
            "completion_rate": round(
                self._safe_float(snapshot.get("completion_rate"), 0.0), 4
            ),
            "fail_streak": int(snapshot.get("fail_streak") or 0),
            "retry_count": int(snapshot.get("retry_count") or 0),
            "preferred_time_window": str(
                snapshot.get("preferred_time_window") or "evening"
            ),
            "recovery_need_flag": bool(snapshot.get("recovery_need_flag")),
        }

    def _lesson_priority_score(
        self,
        *,
        lesson: Dict[str, Any],
        learner_model: Dict[str, Any],
        planned_concepts: set[str],
        order_index: int,
    ) -> Dict[str, Any]:
        target_concepts = [
            self._normalize_concept_key(item)
            for item in (lesson.get("target_concepts") or [])
            if self._normalize_concept_key(item)
        ]
        prerequisite_concepts = [
            self._normalize_concept_key(item)
            for item in (lesson.get("prerequisite_concepts") or [])
            if self._normalize_concept_key(item)
        ]
        mastery_by_concept = self._normalize_concept_score_map(
            learner_model.get("combined_mastery_by_concept")
            or learner_model.get("mastery_by_concept")
        )
        diagnostic_by_concept = self._normalize_concept_score_map(
            learner_model.get("diagnostic_baseline_by_concept")
        )
        weak_concepts = {
            self._normalize_concept_key(item)
            for item in (learner_model.get("weak_concepts") or [])
            if self._normalize_concept_key(item)
        }
        friction_score = self._safe_float(learner_model.get("friction_score"), 0.0)
        pace_score = self._safe_float(learner_model.get("pace_score"), 0.0)
        time_budget_score = self._safe_float(
            learner_model.get("time_budget_score"), 0.0
        )
        diagnostic_baseline = self._safe_float(
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
            sum(1.0 - mastery_by_concept.get(concept, diagnostic_by_concept.get(concept, 0.45)) for concept in prerequisite_concepts)
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
            else 0.5
        )
        mastered_prerequisites = sum(
            1
            for concept in prerequisite_concepts
            if concept in planned_concepts
            or mastery_by_concept.get(concept, diagnostic_by_concept.get(concept, 0.0))
            >= self.PREREQUISITE_MASTERY_THRESHOLD
        )
        prerequisite_ready_ratio = (
            mastered_prerequisites / max(len(prerequisite_concepts), 1)
            if prerequisite_concepts
            else 1.0
        )

        target_difficulty = self._clamp(
            0.22
            + (0.34 * pace_score)
            + (0.24 * self._safe_float(learner_model.get("current_mastery"), 0.0))
            + (0.10 * time_budget_score)
            - (0.16 * friction_score)
        )
        difficulty_fit = 1.0 - abs(difficulty_norm - target_difficulty)
        stability_bias = 1.0 / max(order_index + 2, 2)

        bridge_bonus = 0.0
        if lesson_kind == "bridge":
            bridge_bonus = max(
                weak_overlap,
                prerequisite_gap,
                1.0 - diagnostic_baseline,
            )
        challenge_bonus = (
            0.18
            if lesson_kind in {"practice", "capstone"}
            and pace_score >= 0.7
            and self._safe_float(learner_model.get("current_mastery"), 0.0) >= 0.62
            else 0.0
        )
        friction_penalty = (
            0.18
            if friction_score >= 0.65 and lesson_kind in {"practice", "capstone"}
            else 0.0
        )

        score = (
            0.28 * self._clamp(target_mastery_need)
            + 0.20 * self._clamp(weak_overlap)
            + 0.14 * self._clamp(prerequisite_gap)
            + 0.12 * self._clamp(prerequisite_ready_ratio)
            + 0.12 * self._clamp(difficulty_fit)
            + 0.08 * self._clamp(bridge_bonus)
            + 0.04 * self._clamp(stability_bias)
            + challenge_bonus
            - friction_penalty
        )

        reasons: List[str] = []
        if weak_overlap >= 0.5:
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
            "prerequisite_ready_ratio": round(self._clamp(prerequisite_ready_ratio), 4),
        }

    def _prioritize_curriculum(
        self,
        *,
        chapters: List[Dict[str, Any]],
        learner_model: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        planned_concepts: set[str] = set()
        chapters_out: List[Dict[str, Any]] = []
        original_index = 0
        for chapter_index, chapter in enumerate(chapters or [], start=1):
            chapter_title = str(chapter.get("title") or "").strip() or f"Chapter {chapter_index}"
            remaining: List[Dict[str, Any]] = []
            for lesson_index, lesson in enumerate(chapter.get("lessons", []) or [], start=1):
                original_index += 1
                lesson_copy = dict(lesson)
                lesson_copy["_original_index"] = original_index
                lesson_copy["_original_chapter_index"] = chapter_index
                lesson_copy["_original_lesson_index"] = lesson_index
                remaining.append(lesson_copy)

            if not remaining:
                continue

            ordered: List[Dict[str, Any]] = []
            while remaining:
                eligible: List[Dict[str, Any]] = []
                for lesson in remaining:
                    prereqs = [
                        self._normalize_concept_key(item)
                        for item in (lesson.get("prerequisite_concepts") or [])
                        if self._normalize_concept_key(item)
                    ]
                    if not prereqs:
                        eligible.append(lesson)
                        continue
                    unresolved = [
                        concept
                        for concept in prereqs
                        if concept not in planned_concepts
                        and self._safe_float(
                            (
                                learner_model.get("combined_mastery_by_concept") or {}
                            ).get(concept),
                            0.0,
                        )
                        < self.PREREQUISITE_MASTERY_THRESHOLD
                    ]
                    if not unresolved:
                        eligible.append(lesson)

                candidate_pool = eligible or remaining
                scored_candidates: List[tuple[float, int, Dict[str, Any], Dict[str, Any]]] = []
                for lesson in candidate_pool:
                    score_payload = self._lesson_priority_score(
                        lesson=lesson,
                        learner_model=learner_model,
                        planned_concepts=planned_concepts,
                        order_index=int(lesson.get("_original_index") or 0),
                    )
                    scored_candidates.append(
                        (
                            float(score_payload["score"]),
                            -int(lesson.get("_original_lesson_index") or 0),
                            lesson,
                            score_payload,
                        )
                    )
                scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
                _score, _neg_original_lesson_index, chosen, score_payload = scored_candidates[0]
                chosen_copy = dict(chosen)
                chosen_copy["priority_score"] = score_payload["score"]
                chosen_copy["priority_reasons"] = list(score_payload["reasons"])
                chosen_copy["why_this_lesson_now"] = "; ".join(score_payload["reasons"])
                chosen_copy["prerequisite_ready_ratio"] = score_payload[
                    "prerequisite_ready_ratio"
                ]
                ordered.append(chosen_copy)
                planned_concepts.update(
                    self._normalize_concept_key(item)
                    for item in (chosen_copy.get("target_concepts") or [])
                    if self._normalize_concept_key(item)
                )
                remaining = [item for item in remaining if item is not chosen]

            normalized_lessons: List[Dict[str, Any]] = []
            for lesson in ordered:
                lesson_out = dict(lesson)
                lesson_out.pop("_original_index", None)
                lesson_out.pop("_original_chapter_index", None)
                lesson_out.pop("_original_lesson_index", None)
                normalized_lessons.append(lesson_out)
            chapters_out.append({"title": chapter_title, "lessons": normalized_lessons})
        return chapters_out

    def _user_profile(self, user_id: Optional[str]) -> Dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return {}
        context = self.learner_profile_service.personalization_context(
            user_id=normalized_user_id
        )
        profile = dict(context.get("profile") or {})
        return {
            "user_id": normalized_user_id,
            "level": str(context.get("level") or profile.get("level") or "beginner")
            .strip()
            .lower(),
            "learning_goal": str(context.get("goal") or profile.get("learning_goal") or "")
            .strip(),
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
            "prior_knowledge_by_subject": dict(
                profile.get("prior_knowledge_by_subject") or {}
            ),
            "diagnostic_summary_by_subject": dict(
                profile.get("diagnostic_summary_by_subject") or {}
            ),
            "diagnostic_scores_by_subject": dict(
                profile.get("diagnostic_scores_by_subject") or {}
            ),
        }

    def _latest_path(
        self,
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
        return self.learning_path_repository.collection.find_one(
            query,
            sort=[("updated_at", -1), ("created_at", -1)],
        )

    def _subject_id(
        self,
        *,
        subject_id: Optional[str],
        goal: Optional[str],
        profile: Dict[str, Any],
        latest_path: Optional[Dict[str, Any]],
    ) -> str:
        normalized = str(subject_id or "").strip().lower()
        if get_subject_label(normalized):
            return normalized
        latest_subject = str((latest_path or {}).get("subject_id") or "").strip().lower()
        if get_subject_label(latest_subject):
            return latest_subject
        haystack = " ".join([str(goal or ""), str(profile.get("learning_goal") or "")]).lower()
        for candidate, hints in self._SUBJECT_HINTS.items():
            if any(hint in haystack for hint in hints):
                return candidate
        return "python"

    def _completion_history(self, user_id: Optional[str], *, limit: int = 3) -> List[Dict[str, Any]]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return []
        documents = list(
            self.learning_path_repository.collection.find(
                {"user_id": normalized_user_id},
                {"path_id": 1, "goal": 1, "subject_id": 1, "level": 1, "lesson_progress": 1, "updated_at": 1, "created_at": 1},
            ).sort([("updated_at", -1), ("created_at", -1)]).limit(limit)
        )
        history: List[Dict[str, Any]] = []
        for document in documents:
            lesson_progress = dict(document.get("lesson_progress") or {})
            total_lessons = len(lesson_progress)
            completed_lessons = sum(
                1 for status in lesson_progress.values() if self._status(status) == "completed"
            )
            history.append(
                {
                    "path_id": str(document.get("path_id") or ""),
                    "subject_id": str(document.get("subject_id") or ""),
                    "goal": str(document.get("goal") or ""),
                    "level": str(document.get("level") or "beginner"),
                    "completion_rate": round((completed_lessons / total_lessons) if total_lessons else 0.0, 4),
                    "completed_lessons": completed_lessons,
                    "total_lessons": total_lessons,
                    "updated_at": self._resolve_generated_at(document).isoformat(),
                }
            )
        return history

    def analyze_profile(
        self,
        *,
        user_id: Optional[str],
        subject_id: Optional[str],
        goal: Optional[str],
        level: Optional[str],
    ) -> Dict[str, Any]:
        profile = self._user_profile(user_id)
        latest_path = self._latest_path(user_id=user_id)
        resolved_subject_id = self._subject_id(
            subject_id=subject_id,
            goal=goal,
            profile=profile,
            latest_path=latest_path,
        )
        resolved_goal = (
            str(goal or "").strip()
            or str(profile.get("learning_goal") or "").strip()
            or f"Learn {get_subject_label(resolved_subject_id) or 'this subject'}"
        )
        resolved_level = (
            str(level or "").strip().lower()
            or str(profile.get("level") or "").strip().lower()
            or "beginner"
        )
        matching_path = self._latest_path(
            user_id=user_id,
            subject_id=resolved_subject_id,
            goal=resolved_goal,
            level=resolved_level,
        )
        completion_history = self._completion_history(user_id)
        source_path = matching_path or latest_path
        source_path_id = str((source_path or {}).get("path_id") or "").strip() or None
        snapshot = {
            "mastery_by_concept": {},
            "completion_rate": 0.0,
            "avg_session_duration": 0.0,
            "recent_active_days": 0,
            "current_focus_concepts": [],
            "learning_velocity": 0.0,
            "risk_level": "low",
            "preferred_time_window": "evening",
        }
        if str(user_id or "").strip():
            try:
                snapshot.update(
                    self.learner_state_service.compute_snapshot(
                        user_id=str(user_id),
                        path_id=source_path_id,
                    )
                )
            except Exception:
                logger.debug("Learner snapshot unavailable", exc_info=True)
        mastery_values = [self._safe_float(v, 0.0) for v in snapshot.get("mastery_by_concept", {}).values()]
        current_mastery = round(sum(mastery_values) / len(mastery_values), 4) if mastery_values else 0.0
        weak_concepts = self._dedupe(list(snapshot.get("current_focus_concepts") or []), limit=4)
        subject_prior_knowledge = str(
            (profile.get("prior_knowledge_by_subject") or {}).get(resolved_subject_id)
            or profile.get("level")
            or resolved_level
        )
        diagnostic_summary = dict(
            (profile.get("diagnostic_summary_by_subject") or {}).get(
                resolved_subject_id, {}
            )
        )
        diagnostic_scores = dict(
            (profile.get("diagnostic_scores_by_subject") or {}).get(
                resolved_subject_id, {}
            )
        )
        time_budget = int(profile.get("time_budget_minutes") or 0)
        if time_budget <= 0:
            avg_session = max(int(round(self._safe_float(snapshot.get("avg_session_duration"), 0.0))), 15)
            active_days = max(int(snapshot.get("recent_active_days") or 0), 2)
            time_budget = max(45, min(avg_session * min(active_days, 5), 300))
        learner_model = self._build_learner_model(
            profile=profile,
            resolved_subject_id=resolved_subject_id,
            resolved_level=resolved_level,
            snapshot=snapshot,
            current_mastery=current_mastery,
            weak_concepts=weak_concepts,
            time_budget_minutes=time_budget,
            diagnostic_scores=diagnostic_scores,
            diagnostic_summary=diagnostic_summary,
        )
        planning_context = {
            "time_budget_minutes": time_budget,
            "preferred_resource_type": str(
                profile.get("preferred_resource_type") or "mixed"
            ),
            "learning_pace": str(profile.get("learning_pace") or "steady"),
            "target_role": profile.get("target_role"),
            "target_outcome": profile.get("target_outcome"),
            "desired_deadline": profile.get("desired_deadline"),
            "prior_knowledge_level": subject_prior_knowledge,
            "diagnostic_average_score": round(
                self._safe_float(diagnostic_summary.get("average_score"), 0.0), 4
            ),
            "diagnostic_recommended_level": str(
                diagnostic_summary.get("recommended_level") or resolved_level
            ),
            "diagnostic_scores": diagnostic_scores,
        }
        signals = {
            "recent_active_days": int(snapshot.get("recent_active_days") or 0),
            "preferred_time_window": str(
                snapshot.get("preferred_time_window") or "evening"
            ),
            "learning_velocity": round(
                self._safe_float(snapshot.get("learning_velocity"), 0.0), 4
            ),
            "risk_level": str(snapshot.get("risk_level") or "low"),
            "completion_rate": round(
                self._safe_float(snapshot.get("completion_rate"), 0.0), 4
            ),
        }
        return {
            "user_profile": profile,
            "subject_id": resolved_subject_id,
            "goal": resolved_goal,
            "level": resolved_level,
            "latest_path_id": source_path_id,
            "learner_snapshot": snapshot,
            "planner_input": {
                "version": "planner_input_v2",
                "goal": resolved_goal,
                "level": resolved_level,
                "subject_id": resolved_subject_id,
                "learner_model": learner_model,
                "planning_context": planning_context,
                "signals": signals,
                "current_mastery": current_mastery,
                "weak_concepts": list(learner_model.get("weak_concepts") or []),
                "current_focus_concepts": list(learner_model.get("weak_concepts") or []),
                "completion_rate": round(self._safe_float(snapshot.get("completion_rate"), 0.0), 4),
                "progress_history": completion_history,
                "time_budget_minutes": time_budget,
                "preferred_resource_type": planning_context["preferred_resource_type"],
                "learning_pace": planning_context["learning_pace"],
                "target_role": planning_context["target_role"],
                "target_outcome": planning_context["target_outcome"],
                "desired_deadline": planning_context["desired_deadline"],
                "prior_knowledge_level": planning_context["prior_knowledge_level"],
                "diagnostic_average_score": planning_context["diagnostic_average_score"],
                "diagnostic_recommended_level": planning_context["diagnostic_recommended_level"],
                "diagnostic_scores": diagnostic_scores,
                "recent_active_days": signals["recent_active_days"],
                "preferred_time_window": signals["preferred_time_window"],
                "learning_velocity": signals["learning_velocity"],
                "risk_level": signals["risk_level"],
            },
        }

    def _generate_curriculum(self, *, subject_id: str, subject_label: str, goal: str, level: str, planner_input: Dict[str, Any]) -> Dict[str, Any]:
        fallback = build_fallback_curriculum(
            subject_id, goal, level, planner_input=planner_input
        )
        llm_status = self.llm_client.status()
        if not self.llm_client.is_available() or bool(llm_status.get("cooldown_active")):
            return {"chapters": fallback, "source": "fallback", "llm_status": llm_status}

        generation_mode = self._curriculum_generation_mode(planner_input)
        if generation_mode == "legacy_strict":
            strict_curriculum = self._generate_curriculum_legacy_strict(
                subject_label=subject_label,
                goal=goal,
                level=level,
                planner_input=planner_input,
                fallback=fallback,
            )
            if strict_curriculum:
                llm_status = self.llm_client.status()
                logger.info(
                    "Unified curriculum legacy strict plan succeeded: subject_id=%s chapters=%s lessons=%s",
                    subject_id,
                    len(strict_curriculum),
                    sum(len(chapter.get("lessons", []) or []) for chapter in strict_curriculum),
                )
                return {
                    "chapters": strict_curriculum,
                    "source": "ai_legacy_strict",
                    "llm_status": llm_status,
                }
        else:
            dynamic_curriculum = self._generate_curriculum_dynamic_plan(
                subject_label=subject_label,
                goal=goal,
                level=level,
                planner_input=planner_input,
                fallback=fallback,
            )
            if dynamic_curriculum:
                llm_status = self.llm_client.status()
                logger.info(
                    "Unified curriculum dynamic plan succeeded: subject_id=%s chapters=%s lessons=%s",
                    subject_id,
                    len(dynamic_curriculum),
                    sum(len(chapter.get("lessons", []) or []) for chapter in dynamic_curriculum),
                )
                return {
                    "chapters": dynamic_curriculum,
                    "source": "ai",
                    "llm_status": llm_status,
                }

        enriched_curriculum = self._generate_curriculum_enrichment(
            subject_label=subject_label,
            goal=goal,
            level=level,
            planner_input=planner_input,
            fallback=fallback,
        )
        if enriched_curriculum:
            llm_status = self.llm_client.status()
            logger.info(
                "Unified curriculum enrichment succeeded: subject_id=%s chapters=%s lessons=%s",
                subject_id,
                len(enriched_curriculum),
                sum(len(chapter.get("lessons", []) or []) for chapter in enriched_curriculum),
            )
            return {
                "chapters": enriched_curriculum,
                "source": "ai",
                "llm_status": llm_status,
            }

        llm_status = self.llm_client.status()
        logger.info(
            "Unified curriculum enrichment unavailable; using fallback for subject_id=%s",
            subject_id,
        )
        return {"chapters": fallback, "source": "fallback", "llm_status": llm_status}

    @staticmethod
    def _curriculum_generation_mode(planner_input: Optional[Dict[str, Any]]) -> str:
        requested = str(
            (planner_input or {}).get("curriculum_generation_mode")
            or UNIFIED_CURRICULUM_GENERATION_MODE
            or "legacy_strict"
        ).strip().lower()
        if requested in {"legacy", "strict", "legacy_strict"}:
            return "legacy_strict"
        return "adaptive"

    def _generate_curriculum_legacy_strict(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]] | None:
        outline = self._generate_curriculum_outline(
            subject_label=subject_label,
            goal=goal,
            level=level,
            planner_input=planner_input,
            fallback=fallback,
        )
        if not outline:
            return None

        chapter_drafts: List[Dict[str, Any]] = []
        prior_titles: List[str] = []
        total_chapters = len(fallback or outline or [])
        for chapter_index, fallback_chapter in enumerate(fallback or [], start=1):
            outline_item = (
                outline[chapter_index - 1]
                if chapter_index - 1 < len(outline)
                else {
                    "title": str(fallback_chapter.get("title") or "").strip(),
                    "focus": str(
                        ((fallback_chapter.get("lessons") or [{}])[0].get("summary") or "")
                    ).strip(),
                    "lesson_count": len(fallback_chapter.get("lessons") or []) or 3,
                }
            )
            generated_chapter = self._generate_curriculum_chapter(
                subject_label=subject_label,
                goal=goal,
                level=level,
                planner_input=planner_input,
                outline_item=outline_item,
                chapter_index=chapter_index,
                total_chapters=total_chapters,
                prior_chapter_titles=prior_titles,
                fallback_chapter=fallback_chapter,
            )
            chosen_title = str(
                generated_chapter.get("title")
                or outline_item.get("title")
                or fallback_chapter.get("title")
                or ""
            ).strip()
            if chosen_title:
                prior_titles.append(chosen_title)
            chapter_drafts.append(
                {
                    "title": chosen_title or f"Chapter {chapter_index}",
                    "lessons": list(generated_chapter.get("lessons") or []),
                }
            )

        normalized = normalize_curriculum(
            {"chapters": chapter_drafts},
            goal=goal,
            planner_input=planner_input,
        )
        if not normalized:
            return None
        rejection_reason = self._validate_curriculum_enrichment(
            base_chapters=fallback,
            enriched_chapters=normalized,
        )
        if rejection_reason:
            logger.info(
                "Unified curriculum legacy strict plan rejected: %s",
                rejection_reason,
            )
            return None
        merged = self._merge_curriculum_enrichment(
            base_chapters=fallback,
            enriched_chapters=normalized,
        )
        strict_curriculum = merged or normalized
        if not self._curriculum_meets_minimum_shape(
            chapters=strict_curriculum,
            fallback=fallback,
        ):
            logger.info(
                "Unified curriculum legacy strict plan rejected as too sparse: chapters=%s lessons=%s",
                len(strict_curriculum),
                sum(len(chapter.get("lessons", []) or []) for chapter in strict_curriculum),
            )
            return None
        return strict_curriculum

    def _generate_curriculum_dynamic_plan(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]] | None:
        prompt = build_learning_path_prompt(
            subject_label=subject_label,
            goal=goal,
            level=level,
            planner_input=planner_input,
            target_chapter_count=None,
        )
        payload = self._generate_curriculum_json_payload(
            prompt=prompt,
            max_output_tokens=UNIFIED_CURRICULUM_DYNAMIC_PLAN_MAX_OUTPUT_TOKENS,
        )
        if not isinstance(payload, dict):
            return None
        normalized = normalize_curriculum(
            payload,
            goal=goal,
            planner_input=planner_input,
        )
        if not normalized:
            return None
        normalized = self._rebalance_sparse_curriculum_chapters(
            chapters=normalized,
            fallback=fallback,
        )
        if not self._curriculum_meets_minimum_shape(
            chapters=normalized,
            fallback=fallback,
        ):
            logger.info(
                "Unified curriculum dynamic plan rejected as too sparse: chapters=%s lessons=%s",
                len(normalized),
                sum(len(chapter.get("lessons", []) or []) for chapter in normalized),
            )
            return None
        if not self._curriculum_dynamic_shape_is_reasonable(
            chapters=normalized,
            planner_input=planner_input,
        ):
            logger.info(
                "Unified curriculum dynamic plan rejected as unreasonable shape: chapters=%s lessons=%s",
                len(normalized),
                sum(len(chapter.get("lessons", []) or []) for chapter in normalized),
            )
            return None
        return normalized

    @classmethod
    def _curriculum_dynamic_shape_is_reasonable(
        cls,
        *,
        chapters: List[Dict[str, Any]],
        planner_input: Dict[str, Any],
    ) -> bool:
        chapter_count = len(chapters or [])
        if chapter_count < 2 or chapter_count > 6:
            return False
        total_lessons = sum(len(chapter.get("lessons", []) or []) for chapter in (chapters or []))
        if total_lessons < 4 or total_lessons > 24:
            return False
        time_budget = int(cls._safe_float(planner_input.get("time_budget_minutes"), 0.0))
        if time_budget > 0:
            if time_budget <= 120 and total_lessons > 9:
                return False
            if time_budget >= 360 and total_lessons < 6:
                return False
        return True

    def _generate_curriculum_enrichment(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]] | None:
        prompt = build_learning_path_enrichment_prompt(
            subject_label=subject_label,
            goal=goal,
            level=level,
            chapters=fallback,
            planner_input=planner_input,
        )
        payload = self._generate_curriculum_json_payload(
            prompt=prompt,
            max_output_tokens=UNIFIED_CURRICULUM_ENRICH_MAX_OUTPUT_TOKENS,
        )
        if not isinstance(payload, dict):
            return None
        normalized = normalize_curriculum(
            payload,
            goal=goal,
            planner_input=planner_input,
        )
        if not normalized:
            return None
        enrichment_rejection_reason = self._validate_curriculum_enrichment(
            base_chapters=fallback,
            enriched_chapters=normalized,
        )
        if enrichment_rejection_reason:
            logger.info(
                "Unified curriculum enrichment rejected: %s",
                enrichment_rejection_reason,
            )
            return None
        merged = self._merge_curriculum_enrichment(
            base_chapters=fallback,
            enriched_chapters=normalized,
        )
        if not merged:
            return None
        if not self._curriculum_meets_minimum_shape(
            chapters=merged,
            fallback=fallback,
        ):
            logger.info(
                "Unified curriculum enrichment rejected as too sparse: chapters=%s lessons=%s",
                len(merged),
                sum(len(chapter.get("lessons", []) or []) for chapter in merged),
            )
            return None
        return merged

    @classmethod
    def _validate_curriculum_enrichment(
        cls,
        *,
        base_chapters: List[Dict[str, Any]],
        enriched_chapters: List[Dict[str, Any]],
    ) -> Optional[str]:
        if not enriched_chapters:
            return "empty_enrichment"

        matched_any_chapter = False
        for chapter_index, base_chapter in enumerate(base_chapters or []):
            enriched_chapter = (
                enriched_chapters[chapter_index]
                if chapter_index < len(enriched_chapters)
                and isinstance(enriched_chapters[chapter_index], dict)
                else {}
            )
            if enriched_chapter:
                matched_any_chapter = True
            base_lessons = list(base_chapter.get("lessons") or [])
            enriched_lessons = list(enriched_chapter.get("lessons") or [])
            if not enriched_chapter:
                continue
            if base_lessons and not enriched_lessons:
                return f"empty_lessons_at_chapter_{chapter_index + 1}"

        return None if matched_any_chapter else "no_matching_chapters"

    @staticmethod
    def _canonical_curriculum_text(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()

    @classmethod
    def _title_tokens(cls, value: Any) -> List[str]:
        canonical = cls._canonical_curriculum_text(value)
        return [token for token in canonical.split() if token]

    @classmethod
    def _is_generic_curriculum_title(cls, value: Any, *, kind: str) -> bool:
        canonical = cls._canonical_curriculum_text(value)
        tokens = cls._title_tokens(value)
        if not canonical or len(tokens) < 2:
            return True
        banned_exact = {
            "introduction",
            "overview",
            "basics",
            "basic",
            "practice",
            "review",
            "mini project",
            "project",
            "foundation",
            "foundations",
            "advanced",
            "goal application",
            "goal oriented practice",
            "foundational path",
            "core workflows",
        }
        if canonical in banned_exact:
            return True
        if re.fullmatch(r"(chapter|lesson)\s+\d+", canonical):
            return True
        generic_tokens = {
            "introduction",
            "overview",
            "basics",
            "basic",
            "practice",
            "review",
            "project",
            "mini",
            "core",
            "advanced",
            "foundation",
            "foundations",
            "goal",
            "application",
            "path",
        }
        non_generic_tokens = [token for token in tokens if token not in generic_tokens]
        minimum_specific_tokens = 1
        return len(non_generic_tokens) < minimum_specific_tokens

    @classmethod
    def _is_weak_summary(cls, *, summary: Any, lesson_title: Any) -> bool:
        summary_text = str(summary or "").strip()
        if not summary_text:
            return True
        canonical_summary = cls._canonical_curriculum_text(summary_text)
        canonical_title = cls._canonical_curriculum_text(lesson_title)
        if canonical_summary == canonical_title:
            return True
        weak_prefixes = (
            "study the key ideas in",
            "learn about",
            "understand",
        )
        lowered = summary_text.lower()
        if any(lowered.startswith(prefix) for prefix in weak_prefixes):
            return True
        return len(cls._title_tokens(summary_text)) < 4

    @classmethod
    def _lesson_alignment_is_reasonable(
        cls,
        *,
        base_lesson: Dict[str, Any],
        enriched_lesson: Dict[str, Any],
    ) -> bool:
        enriched_title_tokens = set(cls._title_tokens(enriched_lesson.get("title")))
        concept_tokens: set[str] = set()
        for field in ("target_concepts", "prerequisite_concepts"):
            for item in (base_lesson.get(field) or []):
                concept_tokens.update(cls._title_tokens(item))
        if not concept_tokens:
            return True
        if enriched_title_tokens & concept_tokens:
            return True
        base_title_tokens = set(cls._title_tokens(base_lesson.get("title")))
        return bool(enriched_title_tokens & base_title_tokens)

    @staticmethod
    def _merge_curriculum_enrichment(
        *,
        base_chapters: List[Dict[str, Any]],
        enriched_chapters: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]] | None:
        merged: List[Dict[str, Any]] = []
        changed = False
        chapter_titles_seen: set[str] = set()
        lesson_titles_seen: set[str] = set()

        for chapter_index, base_chapter in enumerate(base_chapters or []):
            chapter_out = dict(base_chapter)
            enriched_chapter = (
                enriched_chapters[chapter_index]
                if chapter_index < len(enriched_chapters)
                and isinstance(enriched_chapters[chapter_index], dict)
                else {}
            )

            enriched_title = str(enriched_chapter.get("title") or "").strip()
            base_chapter_title = str(base_chapter.get("title") or "").strip()
            chosen_chapter_title = base_chapter_title
            if (
                enriched_title
                and not UnifiedLearningPathService._is_generic_curriculum_title(
                    enriched_title, kind="chapter"
                )
                and UnifiedLearningPathService._canonical_curriculum_text(enriched_title)
                not in chapter_titles_seen
                and enriched_title != base_chapter_title
            ):
                chapter_out["title"] = enriched_title
                chosen_chapter_title = enriched_title
                changed = True
            chapter_titles_seen.add(
                UnifiedLearningPathService._canonical_curriculum_text(chosen_chapter_title)
            )

            base_lessons = list(base_chapter.get("lessons") or [])
            enriched_lessons = list(enriched_chapter.get("lessons") or [])
            lessons_out: List[Dict[str, Any]] = []

            for lesson_index, base_lesson in enumerate(base_lessons):
                lesson_out = dict(base_lesson)
                enriched_lesson = (
                    enriched_lessons[lesson_index]
                    if lesson_index < len(enriched_lessons)
                    and isinstance(enriched_lessons[lesson_index], dict)
                    else {}
                )

                base_lesson_title = str(base_lesson.get("title") or "").strip()
                enriched_lesson_title = str(enriched_lesson.get("title") or "").strip()
                chosen_lesson_title = base_lesson_title
                title_is_reasonable = UnifiedLearningPathService._lesson_alignment_is_reasonable(
                    base_lesson=base_lesson,
                    enriched_lesson=enriched_lesson,
                )
                if (
                    enriched_lesson_title
                    and not UnifiedLearningPathService._is_generic_curriculum_title(
                        enriched_lesson_title, kind="lesson"
                    )
                    and title_is_reasonable
                    and UnifiedLearningPathService._canonical_curriculum_text(
                        enriched_lesson_title
                    )
                    not in lesson_titles_seen
                    and enriched_lesson_title != base_lesson_title
                ):
                    lesson_out["title"] = enriched_lesson_title
                    chosen_lesson_title = enriched_lesson_title
                    changed = True

                enriched_summary = str(enriched_lesson.get("summary") or "").strip()
                base_summary = str(base_lesson.get("summary") or "").strip()
                if (
                    enriched_summary
                    and not UnifiedLearningPathService._is_weak_summary(
                        summary=enriched_summary,
                        lesson_title=chosen_lesson_title,
                    )
                    and enriched_summary != base_summary
                ):
                    lesson_out["summary"] = enriched_summary
                    changed = True

                lesson_titles_seen.add(
                    UnifiedLearningPathService._canonical_curriculum_text(chosen_lesson_title)
                )

                for list_field in ("objectives", "prerequisites"):
                    enriched_list = [
                        str(item or "").strip()
                        for item in (enriched_lesson.get(list_field) or [])
                        if str(item or "").strip()
                    ]
                    if (
                        enriched_list
                        and title_is_reasonable
                        and enriched_list != list(base_lesson.get(list_field) or [])
                    ):
                        lesson_out[list_field] = enriched_list[:3]
                        changed = True

                for fallback_field in (
                    "target_concepts",
                    "prerequisite_concepts",
                    "difficulty",
                    "lesson_kind",
                ):
                    if lesson_out.get(fallback_field) not in (None, "", []):
                        continue
                    enriched_value = enriched_lesson.get(fallback_field)
                    if enriched_value not in (None, "", []):
                        lesson_out[fallback_field] = enriched_value

                lessons_out.append(lesson_out)

            chapter_out["lessons"] = lessons_out
            merged.append(chapter_out)

        return merged if changed else None

    @staticmethod
    def _rebalance_sparse_curriculum_chapters(
        *,
        chapters: List[Dict[str, Any]],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if len(chapters) != 1:
            return chapters

        only_chapter = dict(chapters[0] or {})
        lessons = list(only_chapter.get("lessons") or [])
        fallback_titles = [
            str(item.get("title") or "").strip()
            for item in (fallback or [])
            if str(item.get("title") or "").strip()
        ]
        target_chapter_count = max(2, len(fallback_titles) or 3)
        if len(lessons) < max(5, target_chapter_count * 2):
            return chapters

        chunk_size = int(math.ceil(len(lessons) / float(target_chapter_count)))
        rebalanced: List[Dict[str, Any]] = []
        cursor = 0
        for chapter_index in range(target_chapter_count):
            lesson_slice = lessons[cursor : cursor + chunk_size]
            cursor += chunk_size
            if not lesson_slice:
                continue
            chapter_title = (
                fallback_titles[chapter_index]
                if chapter_index < len(fallback_titles)
                else f"Chapter {chapter_index + 1}"
            )
            rebalanced.append({"title": chapter_title, "lessons": lesson_slice})
        return rebalanced or chapters

    @staticmethod
    def _curriculum_meets_minimum_shape(
        *,
        chapters: List[Dict[str, Any]],
        fallback: List[Dict[str, Any]],
    ) -> bool:
        chapter_count = len(chapters or [])
        total_lessons = sum(len(chapter.get("lessons", []) or []) for chapter in (chapters or []))
        fallback_chapter_count = max(2, len(fallback or []) or 3)
        fallback_total_lessons = sum(
            len(chapter.get("lessons", []) or []) for chapter in (fallback or [])
        )
        minimum_lessons = max(4, min(fallback_total_lessons or 6, fallback_chapter_count * 2))
        return chapter_count >= 2 and total_lessons >= minimum_lessons

    def _generate_curriculum_json_payload(
        self,
        *,
        prompt: str,
        max_output_tokens: int,
    ) -> Dict[str, Any] | None:
        raw_text = self.llm_client.generate(
            prompt,
            max_output_tokens=max_output_tokens,
            temperature=0.1,
        )
        json_text = extract_json_object(raw_text)
        if not json_text and raw_text:
            repaired_text = self.llm_client.repair_json(raw_text)
            repaired_json = extract_json_object(repaired_text)
            if repaired_json:
                raw_text = repaired_text
                json_text = repaired_json
        if not json_text:
            return None
        try:
            parsed = json.loads(json_text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            repaired_text = self.llm_client.repair_json(raw_text)
            repaired_json = extract_json_object(repaired_text)
            if not repaired_json:
                return None
            try:
                parsed = json.loads(repaired_json)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    def _generate_curriculum_outline(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        prompt = build_learning_path_outline_prompt(
            subject_label,
            goal,
            level,
            target_chapter_count=max(2, len(fallback) or 3),
            planner_input=planner_input,
        )
        payload = self._generate_curriculum_json_payload(
            prompt=prompt,
            max_output_tokens=900,
        )
        chapter_items = payload.get("chapters", []) if isinstance(payload, dict) else []
        outline: List[Dict[str, Any]] = []
        for index, fallback_chapter in enumerate(fallback):
            item = (
                chapter_items[index]
                if index < len(chapter_items) and isinstance(chapter_items[index], dict)
                else {}
            )
            fallback_lessons = list(fallback_chapter.get("lessons") or [])
            lesson_count = len(fallback_lessons) or 3
            try:
                lesson_count = int(item.get("lesson_count") or lesson_count)
            except Exception:
                lesson_count = len(fallback_lessons) or 3
            outline.append(
                {
                    "title": str(item.get("title") or fallback_chapter.get("title") or "").strip()
                    or f"Chapter {index + 1}",
                    "focus": str(
                        item.get("focus")
                        or (fallback_lessons[0].get("summary") if fallback_lessons else "")
                        or fallback_chapter.get("title")
                        or ""
                    ).strip(),
                    "lesson_count": max(2, min(4, lesson_count)),
                }
            )
        return outline

    def _generate_curriculum_chapter(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        outline_item: Dict[str, Any],
        chapter_index: int,
        total_chapters: int,
        prior_chapter_titles: List[str],
        fallback_chapter: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt = build_learning_path_chapter_prompt(
            subject_label,
            goal,
            level,
            chapter_title=str(outline_item.get("title") or fallback_chapter.get("title") or "").strip(),
            chapter_focus=str(outline_item.get("focus") or "").strip(),
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            target_lesson_count=max(
                2,
                min(
                    4,
                    int(
                        outline_item.get("lesson_count")
                        or len(fallback_chapter.get("lessons") or [])
                        or 3
                    ),
                ),
            ),
            prior_chapter_titles=prior_chapter_titles,
            planner_input=planner_input,
        )
        payload = self._generate_curriculum_json_payload(
            prompt=prompt,
            max_output_tokens=1600,
        )
        lessons = payload.get("lessons", []) if isinstance(payload, dict) else []
        if not isinstance(lessons, list) or not lessons:
            return {
                "title": str(
                    outline_item.get("title") or fallback_chapter.get("title") or ""
                ).strip(),
                "lessons": list(fallback_chapter.get("lessons") or []),
                "_source": "fallback",
            }
        return {
            "title": str(
                outline_item.get("title")
                or payload.get("title")
                or fallback_chapter.get("title")
                or ""
            ).strip(),
            "lessons": lessons,
            "_source": "ai",
        }

    def _resource_payload(self, resource_ids: List[str]) -> List[Dict[str, Any]]:
        payload: List[Dict[str, Any]] = []
        for resource_id in [str(item or "").strip() for item in resource_ids]:
            if not resource_id:
                continue
            resource = None
            if ObjectId.is_valid(resource_id):
                try:
                    resource = self.resource_repository.get(resource_id)
                except Exception:
                    resource = None
            if not resource:
                resource = self.resource_repository.collection.find_one({"resource_id": resource_id})
            if not resource:
                continue
            metadata = resource.get("metadata") or {}
            payload.append(
                {
                    "resource_id": str(resource.get("_id") or resource_id),
                    "title": str(resource.get("title") or ""),
                    "type": str(resource.get("type") or "text"),
                    "source": str(resource.get("source") or ""),
                    "topic": str(resource.get("topic") or ""),
                    "level": str(metadata.get("level") or ""),
                    "url": metadata.get("url"),
                }
            )
            if len(payload) >= 4:
                break
        return payload

    def _adaptation_metadata(self, *, planner_input: Dict[str, Any], snapshot: Dict[str, Any], lesson_order: int, total_lessons: int) -> Dict[str, Any]:
        learner_model = (
            planner_input.get("learner_model")
            if isinstance(planner_input.get("learner_model"), dict)
            else {}
        )
        mastery = self._safe_float(
            learner_model.get("current_mastery", planner_input.get("current_mastery")),
            0.0,
        )
        completion = self._safe_float(planner_input.get("completion_rate"), 0.0)
        weak_concepts = self._dedupe(
            list(
                learner_model.get("weak_concepts")
                or planner_input.get("weak_concepts")
                or []
            ),
            limit=3,
        )
        mode = "continue_learning"
        if weak_concepts and mastery < 0.6:
            mode = "reinforce_weaknesses"
        elif mastery >= 0.8 and completion >= 0.7:
            mode = "learn_new"
        remaining = max(total_lessons - lesson_order + 1, 1)
        time_budget = int(planner_input.get("time_budget_minutes") or 0)
        return {
            "current_mastery": round(mastery, 4),
            "weak_concepts": weak_concepts,
            "completion_rate": round(completion, 4),
            "suggested_mode": mode,
            "time_budget_minutes": time_budget,
            "preferred_resource_type": str(
                planner_input.get("preferred_resource_type") or "mixed"
            ),
            "learning_pace": str(planner_input.get("learning_pace") or "steady"),
            "target_role": planner_input.get("target_role"),
            "target_outcome": planner_input.get("target_outcome"),
            "desired_deadline": planner_input.get("desired_deadline"),
            "prior_knowledge_level": planner_input.get("prior_knowledge_level"),
            "diagnostic_average_score": round(
                self._safe_float(planner_input.get("diagnostic_average_score"), 0.0), 4
            ),
            "recommended_session_minutes": max(10, min(int(round(time_budget / remaining)) if time_budget else 20, 45)),
            "risk_level": str(snapshot.get("risk_level") or "low"),
            "preferred_time_window": str(snapshot.get("preferred_time_window") or "evening"),
            "recent_active_days": int(snapshot.get("recent_active_days") or 0),
            "learner_model_version": str(learner_model.get("version") or "learner_model_v1"),
            "pace_score": round(self._safe_float(learner_model.get("pace_score"), 0.0), 4),
            "time_budget_score": round(
                self._safe_float(learner_model.get("time_budget_score"), 0.0), 4
            ),
            "engagement_score": round(
                self._safe_float(learner_model.get("engagement_score"), 0.0), 4
            ),
            "friction_score": round(
                self._safe_float(learner_model.get("friction_score"), 0.0), 4
            ),
        }

    @staticmethod
    def _stable_concept_numeric_id(value: str, *, order: int) -> int:
        normalized = str(value or "").strip()
        if normalized.isdigit():
            return int(normalized)
        return 900000 + order

    def generate_learning_path(self, *, subject_id: str, goal: str, level: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        analysis = self.analyze_profile(user_id=user_id, subject_id=subject_id, goal=goal, level=level)
        subject_id = analysis["subject_id"]
        goal = analysis["goal"]
        level = analysis["level"]
        planner_input = dict(analysis["planner_input"])
        snapshot = dict(analysis["learner_snapshot"])
        self._validate_inputs(subject_id=subject_id, goal=goal, level=level)
        subject_label = get_subject_label(subject_id) or ""
        curriculum = self._generate_curriculum(subject_id=subject_id, subject_label=subject_label, goal=goal, level=level, planner_input=planner_input)
        planned_curriculum = concept_graph_service.enrich_curriculum(
            subject_id=subject_id,
            goal=goal,
            level=level,
            chapters=curriculum.get("chapters", []),
        )
        prioritized_chapters = self._prioritize_curriculum(
            chapters=list(planned_curriculum.get("chapters") or []),
            learner_model=dict(planner_input.get("learner_model") or {}),
        )
        planned_curriculum["chapters"] = prioritized_chapters
        curriculum_source = "ai" if curriculum.get("source") == "ai" else "fallback"
        llm_status = curriculum.get("llm_status")
        path_id = uuid.uuid4().hex
        subject = self._ensure_subject(subject_id=subject_id, subject_label=subject_label, level=level)
        total_lessons = sum(
            len(chapter.get("lessons", []) or [])
            for chapter in planned_curriculum.get("chapters", [])
        )
        chapters_out: List[Dict[str, Any]] = []
        lesson_progress: Dict[str, str] = {}
        lesson_confidence_log: Dict[str, Dict[str, Any]] = {}
        used_resource_ids: set[str] = set()
        lesson_order = 0
        lesson_concept_map: Dict[str, Dict[str, List[str]]] = {}
        concept_graph = list(planned_curriculum.get("concept_graph") or [])
        for chapter_index, chapter_payload in enumerate(planned_curriculum.get("chapters", []), start=1):
            chapter = self.chapter_repository.create({
                "subject_id": subject["_id"],
                "title": chapter_payload["title"],
                "description": f"Unified learning path chapter for goal: {goal}",
                "order": chapter_index,
                "topic": subject_id,
                "metadata": {"learning_path_id": path_id, "subject_key": subject_id, "goal": goal, "level": level, "generated_by": "unified_learning_path_service"},
            })
            lessons_out: List[Dict[str, Any]] = []
            for lesson_index, lesson_payload in enumerate(chapter_payload.get("lessons", []), start=1):
                lesson_order += 1
                objectives = self._dedupe(list(lesson_payload.get("objectives") or []) + [lesson_payload.get("summary")], limit=3)
                target_concepts = self._dedupe(
                    list(lesson_payload.get("target_concepts") or []),
                    limit=5,
                )
                prerequisite_concepts = self._dedupe(
                    list(lesson_payload.get("prerequisite_concepts") or []),
                    limit=5,
                )
                prerequisites = self._dedupe(
                    list(lesson_payload.get("prerequisites") or []),
                    limit=4,
                )
                lesson_difficulty = max(1, min(int(lesson_payload.get("difficulty") or lesson_order), 10))
                lesson_kind = str(lesson_payload.get("lesson_kind") or "core").strip().lower() or "core"
                lesson_keywords = self._build_keywords(subject_label=subject_label, chapter_title=chapter_payload["title"], lesson_title=lesson_payload["title"], lesson_summary=lesson_payload["summary"], goal=goal)
                seed_resource_ids = self._select_resource_ids_for_lesson(subject_id=subject_id, subject_label=subject_label, chapter_title=chapter_payload["title"], lesson_title=lesson_payload["title"], lesson_summary=lesson_payload["summary"], goal=goal, level=level, limit=self.max_seed_resources_per_lesson, avoid_resource_ids=list(used_resource_ids))
                adaptation_metadata = self._adaptation_metadata(planner_input=planner_input, snapshot=snapshot, lesson_order=lesson_order, total_lessons=total_lessons)
                adaptation_metadata.update(
                    {
                        "target_concepts": target_concepts,
                        "prerequisite_concepts": prerequisite_concepts,
                        "difficulty": lesson_difficulty,
                        "lesson_kind": lesson_kind,
                        "priority_score": round(
                            self._safe_float(lesson_payload.get("priority_score"), 0.0), 4
                        ),
                        "priority_reasons": list(lesson_payload.get("priority_reasons") or []),
                        "why_this_lesson_now": str(
                            lesson_payload.get("why_this_lesson_now")
                            or "Sequenced by learner model and prerequisite readiness."
                        ),
                    }
                )
                lesson = self.lesson_repository.create({
                    "subject_id": subject["_id"],
                    "chapter_id": chapter["_id"],
                    "title": lesson_payload["title"],
                    "summary": lesson_payload["summary"],
                    "order": lesson_index,
                    "topic": subject_id,
                    "level": level,
                    "learning_objectives": objectives,
                    "keywords": lesson_keywords,
                    "resource_ids": seed_resource_ids,
                    "metadata": {
                        "learning_path_id": path_id,
                        "subject_key": subject_id,
                        "goal": goal,
                        "level": level,
                        "generated_by": "unified_learning_path_service",
                        "curriculum_source": curriculum_source,
                        "prerequisites": prerequisites,
                        "target_concepts": target_concepts,
                        "prerequisite_concepts": prerequisite_concepts,
                        "difficulty": lesson_difficulty,
                        "lesson_kind": lesson_kind,
                        "unlock_strategy": "concept_mastery",
                        "prerequisite_mastery_threshold": self.PREREQUISITE_MASTERY_THRESHOLD,
                        "adaptation_metadata": adaptation_metadata,
                    },
                })
                recommended_chunk_ids: List[str] = []
                recommended_resource_ids = [str(item) for item in seed_resource_ids]
                recommended_resources = self._resource_payload(recommended_resource_ids)
                if self.precompute_recommendations_on_generate:
                    recommendation = self._recommend_chunks_for_lesson(
                        lesson=lesson,
                        chapter=chapter,
                        subject=subject,
                        goal=goal,
                        level=level,
                        path_id=path_id,
                    )
                    recommended_chunk_ids = [
                        str(item) for item in (recommendation.get("chunk_ids") or [])
                    ]
                    recommended_resource_ids = [
                        str(item)
                        for item in (
                            recommendation.get("resource_ids") or seed_resource_ids
                        )
                    ]
                    recommended_resources = self._resource_payload(
                        recommended_resource_ids
                    )
                self.lesson_repository.update(
                    lesson["_id"],
                    {
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "recommended_resource_ids": recommended_resource_ids,
                    },
                )
                used_resource_ids.update(recommended_resource_ids)
                lesson_id = str(lesson["_id"])
                lesson_progress[lesson_id] = "not_started"
                lesson_confidence_log[lesson_id] = {"confidence": 0.0, "updated_at": None}
                lesson_concept_map[lesson_id] = {
                    "target_concepts": target_concepts,
                    "prerequisite_concepts": prerequisite_concepts,
                }
                lessons_out.append(
                    {
                        "lesson_id": lesson_id,
                        "title": lesson["title"],
                        "summary": lesson.get("summary"),
                        "objectives": objectives,
                        "prerequisites": prerequisites,
                        "target_concepts": target_concepts,
                        "prerequisite_concepts": prerequisite_concepts,
                        "difficulty": lesson_difficulty,
                        "lesson_kind": lesson_kind,
                        "unlock_strategy": "concept_mastery",
                        "recommended_resources": recommended_resources,
                        "adaptation_metadata": adaptation_metadata,
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "status": "not_started",
                    }
                )
            chapters_out.append({"chapter_id": str(chapter["_id"]), "title": chapter["title"], "lessons": lessons_out})
        self.learning_path_repository.create(
            {
                "path_id": path_id,
                "user_id": user_id,
                "subject_id": subject_id,
                "subject_ref_id": subject["_id"],
                "subject_label": subject_label,
                "goal": goal,
                "level": level,
                "chapters": chapters_out,
                "concept_graph": concept_graph,
                "curriculum_source": curriculum_source,
                "llm_status": llm_status,
                "lesson_progress": lesson_progress,
                "lesson_confidence_log": lesson_confidence_log,
                "concept_mastery": {},
                "metadata": {
                    "pipeline": "unified_learning_path_v2_concept_graph",
                    "layers": {
                        "profile_analysis": "learner_snapshot_v1",
                        "path_planning": "concept_graph_planner_v1 + learner_model_v1",
                        "path_refinement": "lesson_adaptation_v2",
                    },
                    "chapter_count": len(chapters_out),
                    "lesson_count": total_lessons,
                    "concept_count": len(concept_graph),
                    "planner_input": planner_input,
                    "concept_graph": concept_graph,
                    "lesson_concept_map": lesson_concept_map,
                    "mastery_threshold": self.PREREQUISITE_MASTERY_THRESHOLD,
                    "profile_analysis": {
                        "current_mastery": planner_input.get("current_mastery"),
                        "weak_concepts": planner_input.get("weak_concepts"),
                        "progress_history": planner_input.get("progress_history"),
                        "time_budget_minutes": planner_input.get("time_budget_minutes"),
                        "preferred_resource_type": planner_input.get("preferred_resource_type"),
                        "learning_pace": planner_input.get("learning_pace"),
                        "target_role": planner_input.get("target_role"),
                        "target_outcome": planner_input.get("target_outcome"),
                        "desired_deadline": planner_input.get("desired_deadline"),
                        "prior_knowledge_level": planner_input.get("prior_knowledge_level"),
                        "diagnostic_average_score": planner_input.get("diagnostic_average_score"),
                        "diagnostic_recommended_level": planner_input.get("diagnostic_recommended_level"),
                        "risk_level": planner_input.get("risk_level"),
                        "learner_model": planner_input.get("learner_model"),
                        "planning_context": planner_input.get("planning_context"),
                        "signals": planner_input.get("signals"),
                    },
                },
            }
        )
        return {
            "path_id": path_id,
            "user_id": user_id,
            "subject_id": subject_id,
            "goal": goal,
            "level": level,
            "generated_at": datetime.utcnow(),
            "chapters": chapters_out,
            "concept_graph": concept_graph,
            "concept_mastery": {},
            "mastery_threshold": self.PREREQUISITE_MASTERY_THRESHOLD,
            "curriculum_source": curriculum_source,
            "llm_status": llm_status,
            "message": f"Unified learning path generated with {len(chapters_out)} chapters and {total_lessons} lessons.",
        }

    def _serialize_learning_path(self, document: Dict[str, Any]) -> Dict[str, Any]:
        payload = super()._serialize_learning_path(document)
        payload["user_id"] = str(document.get("user_id") or "")
        payload["concept_graph"] = list(
            document.get("concept_graph")
            or (document.get("metadata") or {}).get("concept_graph")
            or []
        )
        payload["concept_mastery"] = dict(document.get("concept_mastery") or {})
        payload["mastery_threshold"] = self._safe_float(
            (document.get("metadata") or {}).get("mastery_threshold"),
            self.PREREQUISITE_MASTERY_THRESHOLD,
        )
        return payload

    @staticmethod
    def _normalize_chapters(*, chapters: List[Dict[str, Any]], lesson_progress: Dict[str, str], lesson_confidence_log: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for chapter in chapters or []:
            lessons_out = []
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "")
                confidence_entry = lesson_confidence_log.get(lesson_id) or {}
                lessons_out.append({"lesson_id": lesson_id, "title": lesson.get("title", ""), "summary": lesson.get("summary"), "objectives": list(lesson.get("objectives") or []), "prerequisites": list(lesson.get("prerequisites") or []), "target_concepts": list(lesson.get("target_concepts") or []), "prerequisite_concepts": list(lesson.get("prerequisite_concepts") or []), "difficulty": int(lesson.get("difficulty") or 1), "lesson_kind": str(lesson.get("lesson_kind") or "core"), "unlock_strategy": str(lesson.get("unlock_strategy") or "concept_mastery"), "recommended_resources": list(lesson.get("recommended_resources") or []), "adaptation_metadata": dict(lesson.get("adaptation_metadata") or {}), "refinement": dict(lesson.get("refinement") or {}), "recommended_chunk_ids": [str(item) for item in lesson.get("recommended_chunk_ids", []) or []], "status": lesson_progress.get(lesson_id, lesson.get("status", "not_started")), "last_confidence": float(confidence_entry.get("confidence", 0.0) or 0.0), "confidence_updated_at": confidence_entry.get("updated_at")})
            normalized.append({"chapter_id": str(chapter.get("chapter_id") or ""), "title": chapter.get("title", ""), "lessons": lessons_out})
        return normalized

    def build_recommended_path(self, path: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        order = 0
        for chapter in path.get("chapters", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                order += 1
                adaptation_metadata = dict(lesson.get("adaptation_metadata") or {})
                target_concepts = list(lesson.get("target_concepts") or [])
                primary_concept = target_concepts[0] if target_concepts else str(order)
                items.append({"concept_id": self._stable_concept_numeric_id(primary_concept, order=order), "concept_name": str(lesson.get("title") or f"Lesson {order}"), "difficulty": int(lesson.get("difficulty") or min(10, 1 + ((order - 1) // 2))), "bloom_level": "understand" if order <= 2 else "apply", "mode": str(adaptation_metadata.get("suggested_mode") or "continue_learning"), "priority_score": round(self._safe_float(adaptation_metadata.get("priority_score"), max(0.2, 1.0 - ((order - 1) * 0.06))), 4), "resources": [{"title": str(item.get("title") or ""), "url": item.get("url"), "source": item.get("source")} for item in (lesson.get("recommended_resources") or []) if isinstance(item, dict)], "status": self._status(lesson.get("status")), "order": order, "lesson_id": str(lesson.get("lesson_id") or ""), "subject_id": path.get("subject_id"), "topic": path.get("subject_id"), "target_concepts": target_concepts, "prerequisite_concepts": list(lesson.get("prerequisite_concepts") or []), "objectives": list(lesson.get("objectives") or []), "prerequisites": list(lesson.get("prerequisites") or []), "recommended_resources": list(lesson.get("recommended_resources") or []), "adaptation_metadata": adaptation_metadata})
        items.sort(
            key=lambda item: (
                0 if item.get("status") != "completed" else 1,
                -self._safe_float(item.get("priority_score"), 0.0),
                int(item.get("order") or 0),
            )
        )
        return items

    def recommend_next_concepts(self, *, user_id: str, limit: int = 5, goal: Optional[str] = None, level: Optional[str] = None, subject_id: Optional[str] = None, allow_generate: bool = True) -> List[Dict[str, Any]]:
        analysis = self.analyze_profile(user_id=user_id, subject_id=subject_id, goal=goal, level=level)
        existing = self._latest_path(user_id=user_id, subject_id=analysis["subject_id"], goal=analysis["goal"], level=analysis["level"])
        if existing:
            path = self._serialize_learning_path(existing)
        elif allow_generate:
            path = self.generate_learning_path(user_id=user_id, subject_id=analysis["subject_id"], goal=analysis["goal"], level=analysis["level"])
        else:
            return []
        return self.build_recommended_path(path)[:limit]

    @staticmethod
    def _get_subject_label_helper(subject_id: str) -> str:
        return get_subject_label(subject_id)

    @staticmethod
    def _build_learning_path_outline_prompt_helper(*args: Any, **kwargs: Any) -> str:
        return build_learning_path_outline_prompt(*args, **kwargs)

    @staticmethod
    def _build_learning_path_chapter_prompt_helper(*args: Any, **kwargs: Any) -> str:
        return build_learning_path_chapter_prompt(*args, **kwargs)

    def _build_learner_model(
        self,
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
        return build_learning_path_learner_model(
            self,
            profile=profile,
            resolved_subject_id=resolved_subject_id,
            resolved_level=resolved_level,
            snapshot=snapshot,
            current_mastery=current_mastery,
            weak_concepts=weak_concepts,
            time_budget_minutes=time_budget_minutes,
            diagnostic_scores=diagnostic_scores,
            diagnostic_summary=diagnostic_summary,
        )

    def _lesson_priority_score(
        self,
        *,
        lesson: Dict[str, Any],
        learner_model: Dict[str, Any],
        planned_concepts: set[str],
        order_index: int,
    ) -> Dict[str, Any]:
        return score_learning_path_lesson_priority(
            self,
            lesson=lesson,
            learner_model=learner_model,
            planned_concepts=planned_concepts,
            order_index=order_index,
        )

    def _prioritize_curriculum(
        self,
        *,
        chapters: List[Dict[str, Any]],
        learner_model: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        return prioritize_learning_path_curriculum(
            self,
            chapters=chapters,
            learner_model=learner_model,
        )

    def _user_profile(self, user_id: Optional[str]) -> Dict[str, Any]:
        return resolve_learning_path_user_profile(self, user_id)

    def _latest_path(
        self,
        *,
        user_id: Optional[str],
        subject_id: Optional[str] = None,
        goal: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return resolve_latest_learning_path(
            self,
            user_id=user_id,
            subject_id=subject_id,
            goal=goal,
            level=level,
        )

    def _subject_id(
        self,
        *,
        subject_id: Optional[str],
        goal: Optional[str],
        profile: Dict[str, Any],
        latest_path: Optional[Dict[str, Any]],
    ) -> str:
        return resolve_learning_path_subject_id(
            self,
            subject_id=subject_id,
            goal=goal,
            profile=profile,
            latest_path=latest_path,
        )

    def _completion_history(
        self, user_id: Optional[str], *, limit: int = 3
    ) -> List[Dict[str, Any]]:
        return collect_learning_path_completion_history(
            self,
            user_id,
            limit=limit,
        )

    def _generate_curriculum_outline(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        fallback: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return generate_learning_path_outline(
            self,
            subject_label=subject_label,
            goal=goal,
            level=level,
            planner_input=planner_input,
            fallback=fallback,
        )

    def _generate_curriculum_chapter(
        self,
        *,
        subject_label: str,
        goal: str,
        level: str,
        planner_input: Dict[str, Any],
        outline_item: Dict[str, Any],
        chapter_index: int,
        total_chapters: int,
        prior_chapter_titles: List[str],
        fallback_chapter: Dict[str, Any],
    ) -> Dict[str, Any]:
        return generate_learning_path_chapter(
            self,
            subject_label=subject_label,
            goal=goal,
            level=level,
            planner_input=planner_input,
            outline_item=outline_item,
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            prior_chapter_titles=prior_chapter_titles,
            fallback_chapter=fallback_chapter,
        )

    def _resource_payload(self, resource_ids: List[str]) -> List[Dict[str, Any]]:
        return build_learning_path_resource_payload(self, resource_ids)

    def _adaptation_metadata(
        self,
        *,
        planner_input: Dict[str, Any],
        snapshot: Dict[str, Any],
        lesson_order: int,
        total_lessons: int,
    ) -> Dict[str, Any]:
        return build_lesson_adaptation_metadata(
            self,
            planner_input=planner_input,
            snapshot=snapshot,
            lesson_order=lesson_order,
            total_lessons=total_lessons,
        )

    @staticmethod
    def _stable_concept_numeric_id(value: str, *, order: int) -> int:
        return build_stable_concept_numeric_id(value, order=order)

    def _serialize_learning_path(self, document: Dict[str, Any]) -> Dict[str, Any]:
        base_payload = super()._serialize_learning_path(document)
        return serialize_unified_learning_path(
            self,
            document=document,
            base_payload=base_payload,
        )

    @staticmethod
    def _normalize_chapters(
        *,
        chapters: List[Dict[str, Any]],
        lesson_progress: Dict[str, str],
        lesson_confidence_log: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return normalize_learning_path_chapters(
            chapters=chapters,
            lesson_progress=lesson_progress,
            lesson_confidence_log=lesson_confidence_log,
        )

    def build_recommended_path(self, path: Dict[str, Any]) -> List[Dict[str, Any]]:
        return build_learning_path_recommended_path(self, path)


learning_path_service = UnifiedLearningPathService()
