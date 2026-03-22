"""MongoDB repository for lesson -> recommended chunk mappings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class LessonRecommendedChunkRepository:
    """Repository for `lesson_recommended_chunks` collection."""

    collection_name = "lesson_recommended_chunks"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("lesson_id", 1)], unique=True)
        self.collection.create_index([("subject_id", 1), ("chapter_id", 1)])
        self.collection.create_index([("created_at", -1)])

    def upsert_for_lesson(self, lesson_id: str | ObjectId, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        payload = dict(document)
        created_at = payload.pop("created_at", now)
        payload["updated_at"] = now
        self.collection.update_one(
            {"lesson_id": self._to_object_id(lesson_id)},
            {"$set": payload, "$setOnInsert": {"created_at": created_at}},
            upsert=True,
        )
        return self.get_by_lesson(lesson_id) or payload

    def get_by_lesson(self, lesson_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"lesson_id": self._to_object_id(lesson_id)})
