"""
Lesson Completion Engine: Auto-completion & prerequisite enforcement.

Features:
- Auto-complete lessons when confidence score > 70%
- Lock subsequent lessons if prerequisite lesson not completed
- Validate and enforce lesson sequence
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.services.prerequisite_resolver import prerequisite_resolver

logger = logging.getLogger(__name__)

# Configuration
AUTO_COMPLETE_CONFIDENCE_THRESHOLD = 0.75  # Auto-complete when confidence >= 75%
COMPLETION_CONFIDENCE_THRESHOLD = 0.75  # Required confidence for manual completion


class LessonCompletionEngine:
    """Manage lesson completion states and prerequisite enforcement."""

    def __init__(self) -> None:
        self.db = get_db()

    def check_auto_completion(
        self, confidence: float, lesson_id: str
    ) -> Dict[str, Any]:
        """
        Check if lesson should be auto-completed based on confidence score.

        Args:
            confidence: Confidence score (0.0 - 1.0)
            lesson_id: Lesson ID string

        Returns:
            Dict with:
            - should_auto_complete: bool
            - reason: str
            - confidence: float
            - threshold: float
        """
        logger.debug(
            f"Checking auto-completion: lesson={lesson_id}, confidence={confidence:.2%}"
        )

        should_complete = confidence >= AUTO_COMPLETE_CONFIDENCE_THRESHOLD

        result = {
            "should_auto_complete": should_complete,
            "confidence": confidence,
            "threshold": AUTO_COMPLETE_CONFIDENCE_THRESHOLD,
            "reason": (
                f"Confidence {confidence:.2%} >= {AUTO_COMPLETE_CONFIDENCE_THRESHOLD:.2%}, "
                f"auto-completing lesson"
                if should_complete
                else f"Confidence {confidence:.2%} < {AUTO_COMPLETE_CONFIDENCE_THRESHOLD:.2%}, "
                f"manual completion required"
            ),
        }

        logger.info(f"Auto-completion check: {result}")
        return result

    def can_access_lesson(
        self,
        path_id: str,
        lesson_id: str,
        chapter_index: int,
        lesson_index: int,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if lesson can be accessed based on prerequisites.

        Args:
            path_id: Learning path ID
            lesson_id: Target lesson ID
            chapter_index: Chapter index (0-based)
            lesson_index: Lesson index within chapter (0-based)

        Returns:
            Dict with:
            - can_access: bool
            - is_locked: bool
            - reason: str
            - blocking_lesson_id: Optional[str]
        """
        logger.debug(
            f"Checking access: path={path_id}, lesson={lesson_id}, "
            f"chapter={chapter_index}, lesson={lesson_index}"
        )

        # First lesson in first chapter is always accessible
        if chapter_index == 0 and lesson_index == 0:
            return {
                "can_access": True,
                "is_locked": False,
                "reason": "First lesson is always accessible",
                "blocking_lesson_id": None,
            }

        # Get learning path
        path = self.db.learning_paths.find_one({"path_id": path_id})
        if not path:
            return {
                "can_access": False,
                "is_locked": True,
                "reason": "Learning path not found",
                "blocking_lesson_id": None,
            }

        if prerequisite_resolver.path_uses_concept_graph(path):
            return prerequisite_resolver.evaluate_lesson_access(
                path_document=path,
                lesson_id=lesson_id,
                user_id=user_id,
            )

        lesson_progress = path.get("lesson_progress", {})

        # Find prerequisite lesson
        blocking_lesson_id = None

        # First, check if it's the first lesson in a chapter
        if lesson_index == 0 and chapter_index > 0:
            # Must complete last lesson of previous chapter
            prev_chapter = path.get("chapters", [])[chapter_index - 1]
            prev_lessons = prev_chapter.get("lessons", [])
            if prev_lessons:
                blocking_lesson_id = prev_lessons[-1].get("lesson_id")
        elif lesson_index > 0:
            # Must complete previous lesson in same chapter
            curr_chapter = path.get("chapters", [])[chapter_index]
            curr_lessons = curr_chapter.get("lessons", [])
            if lesson_index > 0 and lesson_index - 1 < len(curr_lessons):
                blocking_lesson_id = curr_lessons[lesson_index - 1].get("lesson_id")

        # Check if blocking lesson is completed
        if blocking_lesson_id:
            status = lesson_progress.get(blocking_lesson_id, "not_started")
            if status != "completed":
                return {
                    "can_access": False,
                    "is_locked": True,
                    "reason": (
                        f"Prerequisite lesson not completed. "
                        f"Current status: {status}"
                    ),
                    "blocking_lesson_id": blocking_lesson_id,
                }

        return {
            "can_access": True,
            "is_locked": False,
            "reason": "All prerequisites satisfied",
            "blocking_lesson_id": None,
        }

    def get_lesson_lock_status(
        self,
        path_id: str,
        lesson_ids: List[str],
        user_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get lock status for multiple lessons in a path.

        Args:
            path_id: Learning path ID
            lesson_ids: List of lesson IDs to check

        Returns:
            Dict mapping lesson_id -> lock status dict
        """
        logger.debug(
            f"Getting lock status for {len(lesson_ids)} lessons in path {path_id}"
        )

        path = self.db.learning_paths.find_one({"path_id": path_id})
        if not path:
            return {
                lid: {
                    "is_locked": True,
                    "reason": "Learning path not found",
                    "blocking_lesson_id": None,
                }
                for lid in lesson_ids
            }

        if prerequisite_resolver.path_uses_concept_graph(path):
            resolved = prerequisite_resolver.lesson_lock_statuses(
                path_document=path,
                user_id=user_id,
            )
            return {
                lesson_id: resolved.get(
                    lesson_id,
                    {
                        "is_locked": True,
                        "reason": "Lesson not found in path",
                        "blocking_lesson_id": None,
                        "blocking_concepts": [],
                        "missing_prerequisite_concepts": [],
                        "prerequisite_mastery": {},
                        "bridge_recommendations": [],
                        "mastery_threshold": prerequisite_resolver.mastery_threshold,
                    },
                )
                for lesson_id in lesson_ids
            }

        # Build position map
        lesson_positions = {}  # lesson_id -> (chapter_idx, lesson_idx)
        for chapter_idx, chapter in enumerate(path.get("chapters", [])):
            for lesson_idx, lesson in enumerate(chapter.get("lessons", [])):
                lesson_id = lesson.get("lesson_id")
                if lesson_id:
                    lesson_positions[lesson_id] = (chapter_idx, lesson_idx)

        # Check each lesson
        result = {}
        for lesson_id in lesson_ids:
            if lesson_id in lesson_positions:
                chapter_idx, lesson_idx = lesson_positions[lesson_id]
                access_result = self.can_access_lesson(
                    path_id=path_id,
                    lesson_id=lesson_id,
                    chapter_index=chapter_idx,
                    lesson_index=lesson_idx,
                    user_id=user_id,
                )
                result[lesson_id] = {
                    "is_locked": access_result["is_locked"],
                    "reason": access_result["reason"],
                    "blocking_lesson_id": access_result["blocking_lesson_id"],
                }
            else:
                result[lesson_id] = {
                    "is_locked": True,
                    "reason": "Lesson not found in path",
                    "blocking_lesson_id": None,
                }

        logger.debug(
            f"Lock status result: {len([l for l in result.values() if l['is_locked']])} locked"
        )
        return result

    def update_lesson_status_with_confidence(
        self,
        path_id: str,
        user_id: str,
        lesson_id: str,
        confidence: float,
        manual_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update lesson status considering auto-completion rules.

        Args:
            path_id: Learning path ID
            user_id: User ID
            lesson_id: Lesson ID
            confidence: Confidence score (0.0 - 1.0)
            manual_status: Manually set status if provided

        Returns:
            Dict with:
            - path_id: str
            - lesson_id: str
            - final_status: str
            - auto_completed: bool
            - confidence: float
            - reason: str
        """
        logger.info(
            f"Updating lesson status: path={path_id}, lesson={lesson_id}, "
            f"user={user_id}, confidence={confidence:.2%}"
        )

        # Check auto-completion
        auto_complete_result = self.check_auto_completion(confidence, lesson_id)
        should_auto_complete = auto_complete_result["should_auto_complete"]

        # Determine final status
        if should_auto_complete:
            final_status = "completed"
            auto_completed = True
            reason = (
                f"Auto-completed: confidence {confidence:.2%} >= "
                f"{AUTO_COMPLETE_CONFIDENCE_THRESHOLD:.2%}"
            )
        elif manual_status:
            final_status = manual_status
            auto_completed = False
            reason = f"Manually set to: {manual_status}"
        else:
            final_status = "in_progress"
            auto_completed = False
            reason = (
                f"In progress: confidence {confidence:.2%} < "
                f"{AUTO_COMPLETE_CONFIDENCE_THRESHOLD:.2%}, "
                f"awaiting manual completion or higher confidence"
            )

        # Update path
        path = self.db.learning_paths.find_one({"path_id": path_id, "user_id": user_id})

        if not path:
            raise ValueError("Learning path not found")

        lesson_progress = path.get("lesson_progress", {})
        lesson_progress[lesson_id] = final_status

        now = datetime.utcnow()
        self.db.learning_paths.update_one(
            {"path_id": path_id, "user_id": user_id},
            {
                "$set": {
                    "lesson_progress": lesson_progress,
                    "updated_at": now,
                }
            },
        )

        result = {
            "path_id": path_id,
            "lesson_id": lesson_id,
            "final_status": final_status,
            "auto_completed": auto_completed,
            "confidence": confidence,
            "reason": reason,
            "updated_at": now,
        }

        logger.info(f"Lesson status updated: {result}")
        return result

    def unlock_next_lesson(
        self, path_id: str, completed_lesson_id: str
    ) -> Dict[str, Any]:
        """
        Find and validate the next lesson that should be unlocked after completion.

        Args:
            path_id: Learning path ID
            completed_lesson_id: Lesson ID that was just completed

        Returns:
            Dict with:
            - next_lesson_id: Optional[str]
            - next_chapter_idx: Optional[int]
            - next_lesson_idx: Optional[int]
            - message: str
        """
        logger.info(
            f"Finding next lesson to unlock: path={path_id}, after={completed_lesson_id}"
        )

        path = self.db.learning_paths.find_one({"path_id": path_id})
        if not path:
            return {
                "next_lesson_id": None,
                "next_chapter_idx": None,
                "next_lesson_idx": None,
                "message": "Learning path not found",
            }

        # Find current lesson position
        current_pos = None
        for chapter_idx, chapter in enumerate(path.get("chapters", [])):
            for lesson_idx, lesson in enumerate(chapter.get("lessons", [])):
                if lesson.get("lesson_id") == completed_lesson_id:
                    current_pos = (chapter_idx, lesson_idx)
                    break
            if current_pos:
                break

        if not current_pos:
            return {
                "next_lesson_id": None,
                "next_chapter_idx": None,
                "next_lesson_idx": None,
                "message": "Current lesson not found in path",
            }

        chapter_idx, lesson_idx = current_pos
        chapters = path.get("chapters", [])

        # Try next lesson in same chapter
        curr_chapter = chapters[chapter_idx]
        if lesson_idx + 1 < len(curr_chapter.get("lessons", [])):
            next_lesson = curr_chapter["lessons"][lesson_idx + 1]
            return {
                "next_lesson_id": next_lesson.get("lesson_id"),
                "next_chapter_idx": chapter_idx,
                "next_lesson_idx": lesson_idx + 1,
                "message": f"Next lesson in same chapter unlocked",
            }

        # Try first lesson in next chapter
        if chapter_idx + 1 < len(chapters):
            next_chapter = chapters[chapter_idx + 1]
            if next_chapter.get("lessons"):
                next_lesson = next_chapter["lessons"][0]
                return {
                    "next_lesson_id": next_lesson.get("lesson_id"),
                    "next_chapter_idx": chapter_idx + 1,
                    "next_lesson_idx": 0,
                    "message": f"First lesson in next chapter unlocked",
                }

        return {
            "next_lesson_id": None,
            "next_chapter_idx": None,
            "next_lesson_idx": None,
            "message": "No more lessons to unlock - learning path complete",
        }


# Singleton instance
lesson_completion_engine = LessonCompletionEngine()
