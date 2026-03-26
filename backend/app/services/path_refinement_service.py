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


class PathRefinementService:
    """Apply local, non-destructive refinement to existing learning paths."""

    def __init__(self) -> None:
        self.learning_path_repository = LearningPathRepository()
        self.refinement_repository = PathRefinementRepository()

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
        signal_summary = feedback_service.summarize_user_signals(
            user_id=user_id, days=14
        )
        context = {
            "path_id": path_id,
            "lesson_id": target_lesson_id,
            "prerequisite_weak": self._has_weak_prerequisite(
                document=document, user_id=user_id, lesson_id=target_lesson_id
            ),
        }

        interventions = intervention_policy.evaluate(
            kt_states=kt_states,
            signal_summary=signal_summary,
            context=context,
        )

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
        self, *, user_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self.refinement_repository.list_refinements(user_id=user_id, limit=limit)

    def list_interventions(
        self, *, user_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self.refinement_repository.list_interventions(
            user_id=user_id, limit=limit
        )

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
                    refinement = dict(lesson_copy.get("refinement") or {})
                    refinement_actions = list(refinement.get("actions", []) or [])
                    for item in interventions:
                        intervention_type = str(item.get("intervention_type") or "")
                        action = item.get("action") or {}
                        refinement_actions.append(
                            {"type": intervention_type, "action": action}
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

                    if refinement_actions:
                        refinement["actions"] = refinement_actions[-8:]
                        lesson_copy["refinement"] = refinement
                        patch_ops.append(
                            {
                                "lesson_id": lid,
                                "applied_interventions": [
                                    item.get("intervention_type")
                                    for item in interventions
                                ],
                            }
                        )

                lessons_out.append(lesson_copy)

            chapter_copy["lessons"] = lessons_out
            updated_chapters.append(chapter_copy)

        return {
            "updated_chapters": updated_chapters,
            "patch": {"ops": patch_ops},
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
