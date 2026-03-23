"""MongoDB repository for lessons."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class LessonRepository:
    """Repository for `lessons` collection."""

    collection_name = "lessons"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("chapter_id", 1), ("order", 1)])
        self.collection.create_index([("subject_id", 1), ("chapter_id", 1)])
        self.collection.create_index([("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        return self.collection.find_one({"_id": result.inserted_id}) or {**document, "_id": result.inserted_id}

    def get(self, lesson_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(lesson_id)})

    def list(self) -> List[Dict[str, Any]]:
        return list(
            self.collection.find().sort(
                [("subject_id", 1), ("chapter_id", 1), ("order", 1), ("created_at", -1)]
            )
        )

    def list_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        subject_id: Optional[str | ObjectId] = None,
        chapter_id: Optional[str | ObjectId] = None,
        q: Optional[str] = None,
        topic: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if subject_id:
            query["subject_id"] = self._to_object_id(subject_id)
        if chapter_id:
            query["chapter_id"] = self._to_object_id(chapter_id)
        if q:
            query["$or"] = [
                {"title": {"$regex": q, "$options": "i"}},
                {"summary": {"$regex": q, "$options": "i"}},
            ]
        if topic:
            query["topic"] = {"$regex": topic, "$options": "i"}
        if level:
            query["level"] = level

        total = self.collection.count_documents(query)
        skip = max(page - 1, 0) * size
        items = list(
            self.collection.find(query)
            .sort([("subject_id", 1), ("chapter_id", 1), ("order", 1), ("created_at", -1)])
            .skip(skip)
            .limit(size)
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": (total + size - 1) // size if size else 0,
        }

    def update(self, lesson_id: str | ObjectId, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.collection.update_one(
            {"_id": self._to_object_id(lesson_id)},
            {"$set": {**updates, "updated_at": datetime.utcnow()}},
        )
        return self.get(lesson_id)

    def update_many(self, lesson_ids: List[str | ObjectId], updates: Dict[str, Any]) -> int:
        if not lesson_ids:
            return 0
        object_ids = [self._to_object_id(item) for item in lesson_ids]
        result = self.collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {**updates, "updated_at": datetime.utcnow()}},
        )
        return result.modified_count

    def list_by_subject(self, subject_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"subject_id": self._to_object_id(subject_id)}).sort(
                [("chapter_id", 1), ("order", 1), ("created_at", -1)]
            )
        )

    def list_by_chapter(self, chapter_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"chapter_id": self._to_object_id(chapter_id)}).sort("order", 1)
        )

    def list_by_learning_path(self, learning_path_id: str) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"metadata.learning_path_id": learning_path_id}).sort(
                [("chapter_id", 1), ("order", 1), ("created_at", -1)]
            )
        )

    def delete_many(self, lesson_ids: List[str | ObjectId]) -> int:
        if not lesson_ids:
            return 0
        object_ids = [self._to_object_id(item) for item in lesson_ids]
        result = self.collection.delete_many({"_id": {"$in": object_ids}})
        return result.deleted_count
