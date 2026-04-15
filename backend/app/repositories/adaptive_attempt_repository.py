"""Repository for adaptive lesson quiz attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


class AdaptiveAttemptRepository:
    """Persist and query adaptive quiz attempts."""

    collection_name = "lesson_quiz_attempts"
    _legacy_fallback_warnings: set[tuple[str, str, str, str]] = set()

    def __init__(self, db) -> None:
        self.collection = db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("user_id", 1), ("lesson_id", 1), ("submitted_at", -1)])
        self.collection.create_index([("attempt_id", 1)], unique=True)
        self.collection.create_index([("path_id", 1), ("lesson_id", 1), ("submitted_at", -1)])
        self.collection.create_index([("attempt_type", 1), ("submitted_at", -1)])

    def create_attempt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        document = dict(payload)
        document.setdefault("submitted_at", datetime.utcnow())
        result = self.collection.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def list_attempts(
        self,
        *,
        user_id: str,
        lesson_id: str,
        path_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        query = {"user_id": str(user_id), "lesson_id": str(lesson_id)}
        if path_id is not None:
            query["path_id"] = str(path_id)
        return list(
            self.collection.find(query)
            .sort("submitted_at", -1)
            .limit(max(1, int(limit)))
        )

    def latest_attempt(
        self,
        *,
        user_id: str,
        lesson_id: str,
        path_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        base_query = {"user_id": str(user_id), "lesson_id": str(lesson_id)}
        if path_id is not None:
            scoped = self.collection.find_one(
                {**base_query, "path_id": str(path_id)},
                sort=[("submitted_at", -1)],
            )
            if scoped:
                return scoped
            legacy = self.collection.find_one(
                {
                    **base_query,
                    "$or": [{"path_id": None}, {"path_id": {"$exists": False}}],
                },
                sort=[("submitted_at", -1)],
            )
            if legacy:
                self._warn_legacy_fallback(
                    user_id=str(user_id),
                    lesson_id=str(lesson_id),
                    path_id=str(path_id),
                    source="latest_attempt",
                )
                return legacy
        return self.collection.find_one(base_query, sort=[("submitted_at", -1)])

    def get_recent_attempts(
        self,
        *,
        user_id: str,
        lesson_id: str,
        path_id: Optional[str] = None,
        k: int = 3,
    ) -> List[Dict[str, Any]]:
        """Return the most recent k attempts in descending time order."""
        base_query = {
            "user_id": str(user_id),
            "lesson_id": str(lesson_id),
        }
        if path_id is not None:
            scoped = list(
                self.collection.find({**base_query, "path_id": str(path_id)})
                .sort("submitted_at", -1)
                .limit(max(1, int(k)))
            )
            if scoped:
                return scoped
            legacy = list(
                self.collection.find(
                    {
                        **base_query,
                        "$or": [{"path_id": None}, {"path_id": {"$exists": False}}],
                    }
                )
                .sort("submitted_at", -1)
                .limit(max(1, int(k)))
            )
            if legacy:
                self._warn_legacy_fallback(
                    user_id=str(user_id),
                    lesson_id=str(lesson_id),
                    path_id=str(path_id),
                    source="recent_attempts",
                )
                return legacy
        return list(
            self.collection.find(
                base_query
            )
            .sort("submitted_at", -1)
            .limit(max(1, int(k)))
        )

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
            "Adaptive legacy %s fallback used for user=%s lesson=%s path=%s because no path-scoped attempt exists.",
            source,
            user_id,
            lesson_id,
            path_id,
        )
