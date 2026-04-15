"""Repository for user learning state used by adaptive loop."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
import logging


logger = logging.getLogger(__name__)


class UserLearningStateRepository:
    """Manage adaptive user learning state snapshots."""

    collection_name = "user_learning_state"
    _legacy_fallback_warnings: set[tuple[str, str, str, str]] = set()

    def __init__(self, db) -> None:
        self.collection = db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        try:
            self.collection.drop_index("user_id_1_subject_id_1_lesson_id_1")
        except Exception:
            logger.debug(
                "Adaptive learning state legacy index not dropped or missing.",
                exc_info=True,
            )
        self.collection.create_index(
            [("user_id", 1), ("subject_id", 1), ("lesson_id", 1), ("path_id", 1)],
            unique=True,
        )
        self.collection.create_index([("user_id", 1), ("updated_at", -1)])

    def get_state(
        self,
        *,
        user_id: str,
        subject_id: str,
        lesson_id: str,
        path_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        base_query = {
            "user_id": str(user_id),
            "subject_id": str(subject_id),
            "lesson_id": str(lesson_id),
        }
        if path_id is not None:
            scoped = self.collection.find_one({**base_query, "path_id": str(path_id)})
            if scoped:
                return scoped
            legacy = self.collection.find_one(
                {
                    **base_query,
                    "$or": [{"path_id": None}, {"path_id": {"$exists": False}}],
                }
            )
            if legacy:
                self._warn_legacy_fallback(
                    user_id=str(user_id),
                    lesson_id=str(lesson_id),
                    path_id=str(path_id),
                    source="learning_state",
                )
                return legacy
        return self.collection.find_one(base_query)

    def upsert_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("updated_at", datetime.utcnow())
        document["path_id"] = str(document.get("path_id") or "").strip() or None
        key = {
            "user_id": str(document["user_id"]),
            "subject_id": str(document["subject_id"]),
            "lesson_id": str(document["lesson_id"]),
            "path_id": document["path_id"],
        }
        self.collection.update_one(key, {"$set": document}, upsert=True)
        return self.collection.find_one(key) or document

    @classmethod
    def _warn_legacy_fallback(
        cls,
        *,
        user_id: str,
        lesson_id: str,
        path_id: str,
        source: str,
    ) -> None:
        warning_key = (user_id, lesson_id, path_id, source)
        if warning_key in cls._legacy_fallback_warnings:
            return
        cls._legacy_fallback_warnings.add(warning_key)
        logger.warning(
            "Adaptive legacy %s fallback used for user=%s lesson=%s path=%s because no path-scoped record exists.",
            source,
            user_id,
            lesson_id,
            path_id,
        )
