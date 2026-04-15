"""Path refinement service for local patching interventions."""

from __future__ import annotations

from datetime import datetime
import uuid
from typing import Any, Dict, List, Optional

from backend.app.repositories.learning_path_repository import LearningPathRepository
from backend.app.repositories.path_refinement_repository import PathRefinementRepository
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.feedback_service import feedback_service
from backend.app.services.intervention_policy import intervention_policy
from backend.app.services.knowledge_tracing_service import knowledge_tracing_service
from backend.app.services.learner_state_service import learner_state_service


class PathRefinementService:
    """Apply local, non-destructive refinement to existing learning paths."""

    def __init__(self) -> None:
        self.learning_path_repository = LearningPathRepository()
        self.refinement_repository = PathRefinementRepository()

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _normalize_concept(value: Any) -> str:
        return str(value or "").strip().lower().replace(" ", "_")

    def _derive_trigger_interventions(
        self,
        *,
        snapshot: Dict[str, Any],
        kt_states: List[Dict[str, Any]],
        current_lesson: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        interventions: List[Dict[str, Any]] = []
        weak_concepts = [
            self._normalize_concept(item)
            for item in (snapshot.get("current_focus_concepts") or [])
            if self._normalize_concept(item)
        ]
        repeated_weak_concept = weak_concepts[0] if weak_concepts else ""
        fail_streak = int(snapshot.get("fail_streak") or snapshot.get("quiz_fail_streak") or 0)
        avg_confidence = 0.0
        if kt_states:
            avg_confidence = sum(
                self._safe_float(item.get("confidence_score"), 0.0)
                for item in kt_states
            ) / max(len(kt_states), 1)
        avg_mastery = 0.0
        if kt_states:
            avg_mastery = sum(
                self._safe_float(item.get("p_mastery"), 0.0)
                for item in kt_states
            ) / max(len(kt_states), 1)
        avg_time_spent = 0.0
        if kt_states:
            avg_time_spent = sum(
                self._safe_float(item.get("avg_time_spent"), 0.0)
                for item in kt_states
            ) / max(len(kt_states), 1)

        if fail_streak >= 3:
            interventions.append(
                {
                    "intervention_type": "reteach",
                    "trigger_reason": f"fail streak reached {fail_streak}",
                    "impact_scope": "current_lesson",
                    "action": {"add": "remedial_resource", "priority": "high"},
                    "priority": 110,
                }
            )

        if avg_confidence and avg_confidence < 0.45 and avg_mastery < 0.65:
            interventions.append(
                {
                    "intervention_type": "slow_down",
                    "trigger_reason": (
                        f"confidence stayed low at {avg_confidence:.2f} while mastery is {avg_mastery:.2f}"
                    ),
                    "impact_scope": "current_and_next_lesson",
                    "action": {"pace": "slow"},
                    "priority": 88,
                }
            )

        if repeated_weak_concept:
            interventions.append(
                {
                    "intervention_type": "prerequisite_bridge",
                    "trigger_reason": (
                        f"weak concept {repeated_weak_concept} repeated in learner state"
                    ),
                    "impact_scope": "before_current_lesson",
                    "action": {
                        "insert": "bridge_checkpoint",
                        "focus_concept": repeated_weak_concept,
                        "source_lesson_title": str(
                            (current_lesson or {}).get("title") or ""
                        ),
                    },
                    "priority": 96,
                }
            )

        if avg_time_spent > 1200 and avg_mastery < 0.55:
            interventions.append(
                {
                    "intervention_type": "format_shift",
                    "trigger_reason": (
                        f"study time is high ({avg_time_spent:.0f}s) but mastery is only {avg_mastery:.2f}"
                    ),
                    "impact_scope": "resource_recommendations",
                    "action": {"prefer_format": "video"},
                    "priority": 82,
                }
            )

        deduped: Dict[str, Dict[str, Any]] = {}
        for intervention in sorted(
            interventions,
            key=lambda item: int(item.get("priority", 0)),
            reverse=True,
        ):
            deduped.setdefault(str(intervention.get("intervention_type") or ""), intervention)
        return list(deduped.values())

    @staticmethod
    def _find_lesson_entry(
        chapters: List[Dict[str, Any]],
        lesson_id: str,
    ) -> tuple[Optional[Dict[str, Any]], Optional[int], Optional[int]]:
        for chapter_index, chapter in enumerate(chapters):
            for lesson_index, lesson in enumerate(chapter.get("lessons", []) or []):
                if str(lesson.get("lesson_id") or "") == str(lesson_id):
                    return lesson, chapter_index, lesson_index
        return None, None, None

    def _build_bridge_lesson(
        self,
        *,
        source_lesson: Dict[str, Any],
        focus_concept: str,
        interventions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        bridge_id = f"bridge_{uuid.uuid4().hex[:12]}"
        concept_label = str(focus_concept or "foundation").replace("_", " ").title()
        source_title = str(source_lesson.get("title") or "current lesson")
        return {
            "lesson_id": bridge_id,
            "title": f"Bridge: {concept_label}",
            "summary": (
                f"Review {concept_label} before returning to {source_title}. "
                "This lesson was inserted by the adaptive refinement loop."
            ),
            "objectives": [
                f"Rebuild working confidence in {concept_label}.",
                f"Prepare for {source_title} with a smaller prerequisite step.",
            ],
            "prerequisites": [],
            "target_concepts": [focus_concept] if focus_concept else [],
            "prerequisite_concepts": [],
            "difficulty": max(1, int(source_lesson.get("difficulty") or 2) - 1),
            "lesson_kind": "bridge",
            "unlock_strategy": "manual_bridge",
            "recommended_resources": list(source_lesson.get("recommended_resources") or [])[:2],
            "recommended_chunk_ids": list(source_lesson.get("recommended_chunk_ids") or [])[:4],
            "status": "not_started",
            "adaptation_metadata": {
                "suggested_mode": "reinforce_weaknesses",
                "focus_concept": focus_concept,
                "why_this_lesson_now": (
                    f"Inserted because {concept_label} is blocking progress in the current lesson."
                ),
                "priority_reasons": [
                    "inserted by refinement trigger",
                    "reinforces a repeated weak concept",
                ],
            },
            "refinement": {
                "bridge_required": True,
                "extra_practice": True,
                "inserted_by_refinement": True,
                "source_lesson_id": str(source_lesson.get("lesson_id") or ""),
                "actions": [
                    {
                        "type": str(item.get("intervention_type") or ""),
                        "action": item.get("action") or {},
                    }
                    for item in interventions
                ],
            },
        }

    def refine_path(
        self,
        *,
        path_id: str,
        user_id: str,
        lesson_id: Optional[str] = None,
        trigger_reason: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        document = self.learning_path_repository.get_by_path_id(path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found")

        chapters = list(document.get("chapters", []) or [])
        lesson_progress = dict(document.get("lesson_progress", {}) or {})
        target_lesson_id = lesson_id or self._pick_next_incomplete_lesson(
            chapters, lesson_progress
        )

        if not target_lesson_id:
            return {
                "path_id": path_id,
                "user_id": user_id,
                "lesson_id": lesson_id,
                "interventions": [],
                "updated": False,
                "message": "No target lesson available for refinement",
            }

        kt_states = knowledge_tracing_service.get_user_lesson_states(
            user_id=user_id, lesson_id=target_lesson_id, limit=20
        )
        learner_snapshot = learner_state_service.compute_snapshot(
            user_id=str(user_id),
            path_id=str(path_id),
            lesson_id=target_lesson_id,
        )
        signal_summary = feedback_service.summarize_user_signals(
            user_id=user_id, days=14
        )
        current_lesson, _chapter_index, _lesson_index = self._find_lesson_entry(
            chapters,
            target_lesson_id,
        )
        context = {
            "path_id": path_id,
            "lesson_id": target_lesson_id,
            "prerequisite_weak": self._has_weak_prerequisite(
                document=document, user_id=user_id, lesson_id=target_lesson_id
            ),
            "learner_snapshot": learner_snapshot,
        }

        interventions = intervention_policy.evaluate(
            kt_states=kt_states,
            signal_summary=signal_summary,
            context=context,
        )
        interventions.extend(
            self._derive_trigger_interventions(
                snapshot=learner_snapshot,
                kt_states=kt_states,
                current_lesson=current_lesson,
            )
        )
        deduped_interventions: Dict[str, Dict[str, Any]] = {}
        for intervention in sorted(
            interventions,
            key=lambda item: int(item.get("priority", 0)),
            reverse=True,
        ):
            key = str(intervention.get("intervention_type") or "")
            if key and key not in deduped_interventions:
                deduped_interventions[key] = intervention
        interventions = list(deduped_interventions.values())

        patch = self._build_local_patch(
            chapters=chapters,
            lesson_progress=lesson_progress,
            target_lesson_id=target_lesson_id,
            interventions=interventions,
        )

        action_id = str(uuid.uuid4())
        action_record = {
            "action_id": action_id,
            "user_id": str(user_id),
            "path_id": str(path_id),
            "lesson_id": target_lesson_id,
            "concept_id": kt_states[0].get("concept_id") if kt_states else None,
            "intervention_type": [
                item.get("intervention_type") for item in interventions
            ],
            "trigger_reason": trigger_reason or "auto_refinement",
            "old_path_snapshot": patch.get("old_snapshot", {}),
            "new_path_patch": patch.get("patch", {}),
            "summary": {
                "headline": patch.get("patch", {}).get("summary", {}).get("headline")
                or "Adaptive refinement applied",
                "intervention_count": len(interventions),
                "intervention_types": [
                    item.get("intervention_type") for item in interventions
                ],
            },
            "outcome_status": "planned" if dry_run else "applied",
            "created_at": datetime.utcnow(),
        }
        self.refinement_repository.create_refinement_action(action_record)

        for intervention in interventions:
            self.refinement_repository.create_intervention_log(
                {
                    "action_id": action_id,
                    "user_id": str(user_id),
                    "path_id": str(path_id),
                    "lesson_id": target_lesson_id,
                    "intervention_type": intervention.get("intervention_type"),
                    "trigger_reason": intervention.get("trigger_reason"),
                    "impact_scope": intervention.get("impact_scope"),
                    "action": intervention.get("action"),
                    "created_at": datetime.utcnow(),
                }
            )

        if not dry_run and patch.get("updated_chapters") is not None:
            self.learning_path_repository.collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        "chapters": patch["updated_chapters"],
                        "updated_at": datetime.utcnow(),
                        "metadata.last_refinement_at": datetime.utcnow(),
                        "metadata.last_refinement_action_id": action_id,
                    }
                },
            )

        event_logging_service.log_event(
            "path_refined",
            user_id=str(user_id),
            path_id=str(path_id),
            lesson_id=target_lesson_id,
            success=True,
            metadata={
                "action_id": action_id,
                "dry_run": dry_run,
                "intervention_types": [
                    item.get("intervention_type") for item in interventions
                ],
            },
        )

        return {
            "path_id": path_id,
            "user_id": str(user_id),
            "lesson_id": target_lesson_id,
            "action_id": action_id,
            "interventions": interventions,
            "updated": (not dry_run),
            "patch": patch.get("patch", {}),
        }

    def list_refinement_actions(
        self,
        *,
        user_id: str,
        limit: int = 100,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.refinement_repository.list_refinements(
            user_id=user_id,
            limit=limit,
            path_id=path_id,
            lesson_id=lesson_id,
        )

    def list_interventions(
        self,
        *,
        user_id: str,
        limit: int = 100,
        path_id: Optional[str] = None,
        lesson_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.refinement_repository.list_interventions(
            user_id=user_id,
            limit=limit,
            path_id=path_id,
            lesson_id=lesson_id,
        )

    @staticmethod
    def _snapshot_refinement_state(lesson: Dict[str, Any]) -> Dict[str, Any]:
        refinement = dict(lesson.get("refinement") or {})
        return {
            "preferred_format": refinement.get("preferred_format"),
            "pace": refinement.get("pace"),
            "bridge_required": bool(refinement.get("bridge_required", False)),
            "extra_practice": bool(refinement.get("extra_practice", False)),
            "skip_easy_content": bool(refinement.get("skip_easy_content", False)),
            "actions_count": len(list(refinement.get("actions") or [])),
        }

    @staticmethod
    def _build_effects_for_intervention(
        intervention_type: str, action: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        effects: List[Dict[str, Any]] = []
        if intervention_type == "format_shift":
            prefer_format = str(action.get("prefer_format") or "video")
            effects.append(
                {
                    "type": "resource_preference_changed",
                    "field": "refinement.preferred_format",
                    "label": f"Ưu tiên học liệu dạng {prefer_format}.",
                    "value": prefer_format,
                }
            )
        elif intervention_type == "slow_down":
            effects.append(
                {
                    "type": "pace_adjusted",
                    "field": "refinement.pace",
                    "label": "Giảm nhịp học để ưu tiên củng cố nền tảng.",
                    "value": "slow",
                }
            )
        elif intervention_type == "accelerate":
            effects.append(
                {
                    "type": "difficulty_unblocked",
                    "field": "refinement.skip_easy_content",
                    "label": "Có thể rút gọn phần dễ và chuyển nhanh hơn sang phần mới.",
                    "value": True,
                }
            )
        elif intervention_type == "prerequisite_bridge":
            effects.append(
                {
                    "type": "prerequisite_bridge_added",
                    "field": "refinement.bridge_required",
                    "label": "Chèn bước bắc cầu để vá khái niệm tiên quyết còn yếu.",
                    "value": True,
                }
            )
        elif intervention_type in {"reteach", "reinforce", "reroute"}:
            effects.append(
                {
                    "type": "extra_practice_added",
                    "field": "refinement.extra_practice",
                    "label": "Bổ sung luyện tập và ôn tập cho lesson hiện tại.",
                    "value": True,
                }
            )
        return effects

    @staticmethod
    def _build_recommendations_for_intervention(
        intervention_type: str, action: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        if intervention_type == "format_shift":
            prefer_format = str(action.get("prefer_format") or "video")
            return [
                {
                    "type": "review",
                    "label": f"Ôn lại lesson bằng học liệu {prefer_format} trước khi làm thêm quiz.",
                }
            ]
        if intervention_type == "slow_down":
            return [
                {
                    "type": "review",
                    "label": "Ôn lại từng phần nhỏ, chưa nên tăng độ khó ở lượt học kế tiếp.",
                }
            ]
        if intervention_type == "accelerate":
            return [
                {
                    "type": "increase_difficulty",
                    "label": "Có thể tiếp tục sang nội dung mới hoặc tăng độ khó nhẹ.",
                }
            ]
        if intervention_type == "prerequisite_bridge":
            return [
                {
                    "type": "review_prerequisite",
                    "label": "Ôn lại khái niệm tiên quyết trước khi mở bước tiếp theo.",
                }
            ]
        if intervention_type == "reteach":
            return [
                {
                    "type": "review",
                    "label": "Ôn lại lesson hiện tại với tài liệu bù lỗ hổng trước khi tiếp tục.",
                }
            ]
        if intervention_type == "reinforce":
            return [
                {
                    "type": "practice",
                    "label": "Làm thêm bài luyện tập ngắn để củng cố khái niệm vừa học.",
                }
            ]
        if intervention_type == "reroute":
            return [
                {
                    "type": "diagnostic",
                    "label": "Làm một lượt chẩn đoán ngắn để xác định đúng phần đang hổng.",
                }
            ]
        return []

    def _build_local_patch(
        self,
        *,
        chapters: List[Dict[str, Any]],
        lesson_progress: Dict[str, str],
        target_lesson_id: str,
        interventions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        updated_chapters = []
        patch_ops: List[Dict[str, Any]] = []
        affected_lesson_ids: List[str] = []
        bridge_lesson_id: Optional[str] = None

        for chapter in chapters:
            chapter_copy = dict(chapter)
            lessons_out = []
            for lesson in chapter.get("lessons", []) or []:
                lesson_copy = dict(lesson)
                lid = str(lesson_copy.get("lesson_id") or "")
                status = lesson_progress.get(
                    lid, lesson_copy.get("status", "not_started")
                )

                # Never mutate completed lessons.
                if lid == target_lesson_id and status != "completed":
                    before_refinement = self._snapshot_refinement_state(lesson_copy)
                    refinement = dict(lesson_copy.get("refinement") or {})
                    refinement_actions = list(refinement.get("actions", []) or [])
                    reasons: List[Dict[str, Any]] = []
                    effects: List[Dict[str, Any]] = []
                    recommendations: List[Dict[str, Any]] = []
                    focus_concept = ""
                    for item in interventions:
                        intervention_type = str(item.get("intervention_type") or "")
                        action = item.get("action") or {}
                        focus_concept = focus_concept or str(
                            action.get("focus_concept") or ""
                        )
                        refinement_actions.append(
                            {"type": intervention_type, "action": action}
                        )
                        reasons.append(
                            {
                                "intervention_type": intervention_type,
                                "trigger_reason": item.get("trigger_reason"),
                                "impact_scope": item.get("impact_scope"),
                            }
                        )
                        effects.extend(
                            self._build_effects_for_intervention(
                                intervention_type, action
                            )
                        )
                        recommendations.extend(
                            self._build_recommendations_for_intervention(
                                intervention_type, action
                            )
                        )

                        if intervention_type == "format_shift":
                            refinement["preferred_format"] = action.get(
                                "prefer_format", "video"
                            )
                        if intervention_type == "slow_down":
                            refinement["pace"] = "slow"
                        if intervention_type == "accelerate":
                            refinement["skip_easy_content"] = True
                        if intervention_type == "prerequisite_bridge":
                            refinement["bridge_required"] = True
                        if intervention_type in {"reteach", "reinforce", "reroute"}:
                            refinement["extra_practice"] = True
                            refinement["question_difficulty"] = "beginner"
                        if intervention_type == "slow_down":
                            refinement["question_difficulty"] = "beginner"
                        if intervention_type == "accelerate":
                            refinement["question_difficulty"] = "intermediate"

                    if refinement_actions:
                        refinement["actions"] = refinement_actions[-8:]
                        lesson_copy["refinement"] = refinement
                        lesson_copy["adaptation_metadata"] = {
                            **dict(lesson_copy.get("adaptation_metadata") or {}),
                            "why_this_lesson_now": (
                                "; ".join(
                                    recommendation.get("label") or ""
                                    for recommendation in recommendations[:2]
                                )
                                or "The lesson was refined based on the latest learner state."
                            ),
                            "priority_reasons": [
                                reason.get("trigger_reason")
                                for reason in reasons
                                if reason.get("trigger_reason")
                            ][:3],
                            "refinement_action_mode": (
                                "reinforce_weaknesses"
                                if any(
                                    item.get("intervention_type")
                                    in {"reteach", "reinforce", "reroute", "prerequisite_bridge"}
                                    for item in interventions
                                )
                                else "continue_learning"
                            ),
                        }
                        after_refinement = self._snapshot_refinement_state(lesson_copy)
                        affected_lesson_ids.append(lid)
                        patch_ops.append(
                            {
                                "op": "lesson_refinement_updated",
                                "lesson_id": lid,
                                "applied_interventions": [
                                    item.get("intervention_type")
                                    for item in interventions
                                ],
                                "reasons": reasons,
                                "effects": effects,
                                "recommendations": recommendations,
                                "before": before_refinement,
                                "after": after_refinement,
                            }
                        )

                        needs_bridge = any(
                            item.get("intervention_type") in {"prerequisite_bridge", "reteach", "reroute"}
                            for item in interventions
                        )
                        if needs_bridge and not any(
                            str(existing.get("lesson_kind") or "") == "bridge"
                            and str((existing.get("refinement") or {}).get("source_lesson_id") or "")
                            == lid
                            for existing in lessons_out
                        ):
                            bridge_lesson = self._build_bridge_lesson(
                                source_lesson=lesson_copy,
                                focus_concept=focus_concept or (
                                    (lesson_copy.get("target_concepts") or [""])[0]
                                ),
                                interventions=interventions,
                            )
                            bridge_lesson_id = bridge_lesson["lesson_id"]
                            lessons_out.append(bridge_lesson)
                            affected_lesson_ids.append(bridge_lesson_id)
                            patch_ops.append(
                                {
                                    "op": "bridge_lesson_inserted",
                                    "lesson_id": bridge_lesson_id,
                                    "source_lesson_id": lid,
                                    "applied_interventions": [
                                        item.get("intervention_type")
                                        for item in interventions
                                    ],
                                    "reasons": reasons,
                                    "effects": [
                                        {
                                            "type": "bridge_lesson_added",
                                            "field": "chapters.lessons",
                                            "label": "Inserted a bridge lesson before continuing the current lesson.",
                                            "value": bridge_lesson.get("title"),
                                        }
                                    ],
                                    "recommendations": recommendations,
                                    "before": {"bridge_lesson_present": False},
                                    "after": {
                                        "bridge_lesson_present": True,
                                        "bridge_lesson_id": bridge_lesson_id,
                                    },
                                }
                            )

                lessons_out.append(lesson_copy)

            chapter_copy["lessons"] = lessons_out
            updated_chapters.append(chapter_copy)

        return {
            "updated_chapters": updated_chapters,
            "patch": {
                "ops": patch_ops,
                "affected_lesson_ids": affected_lesson_ids,
                "summary": {
                    "target_lesson_id": target_lesson_id,
                    "intervention_count": len(interventions),
                    "intervention_types": [
                        item.get("intervention_type") for item in interventions
                    ],
                    "bridge_lesson_id": bridge_lesson_id,
                    "headline": (
                        "Bridge lesson inserted and lesson refined"
                        if bridge_lesson_id
                        else "Lesson refinement applied from learner state"
                    ),
                },
            },
            "old_snapshot": {
                "target_lesson_id": target_lesson_id,
                "existing_status": lesson_progress.get(target_lesson_id),
            },
        }

    @staticmethod
    def _pick_next_incomplete_lesson(
        chapters: List[Dict[str, Any]], lesson_progress: Dict[str, str]
    ) -> Optional[str]:
        for chapter in chapters:
            for lesson in chapter.get("lessons", []) or []:
                lid = str(lesson.get("lesson_id") or "")
                if not lid:
                    continue
                if (
                    lesson_progress.get(lid, lesson.get("status", "not_started"))
                    != "completed"
                ):
                    return lid
        return None

    def _has_weak_prerequisite(
        self, *, document: Dict[str, Any], user_id: str, lesson_id: str
    ) -> bool:
        # Practical fallback: infer weak prerequisites from any lesson-level KT state below threshold.
        states = knowledge_tracing_service.get_user_lesson_states(
            user_id=user_id, lesson_id=lesson_id, limit=20
        )
        if not states:
            return False
        return any(float(item.get("p_mastery", 0.0) or 0.0) < 0.35 for item in states)


path_refinement_service = PathRefinementService()
