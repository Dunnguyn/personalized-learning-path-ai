"""MongoDB repository for chapters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db


class ChapterRepository:
    """Repository for `chapters` collection."""

    collection_name = "chapters"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("subject_id", 1), ("order", 1)])
        self.collection.create_index([("created_at", -1)])

    def create(self, document: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document.setdefault("created_at", now)
        document.setdefault("updated_at", now)
        result = self.collection.insert_one(document)
        return self.collection.find_one({"_id": result.inserted_id}) or {
            **document,
            "_id": result.inserted_id,
        }

    def get(self, chapter_id: str | ObjectId) -> Optional[Dict[str, Any]]:
        return self.collection.find_one({"_id": self._to_object_id(chapter_id)})

    def list(self) -> List[Dict[str, Any]]:
        return list(
            self.collection.find().sort(
                [("subject_id", 1), ("order", 1), ("created_at", -1)]
            )
        )

    def list_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        subject_id: Optional[str | ObjectId] = None,
        q: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if subject_id:
            query["subject_id"] = self._to_object_id(subject_id)
        if q:
            query["$or"] = [
                {"title": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        if topic:
            query["topic"] = {"$regex": topic, "$options": "i"}

        total = self.collection.count_documents(query)
        skip = max(page - 1, 0) * size
        items = list(
            self.collection.find(query)
            .sort([("subject_id", 1), ("order", 1), ("created_at", -1)])
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

    def list_by_subject(self, subject_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"subject_id": self._to_object_id(subject_id)}).sort(
                "order", 1
            )
        )

    def list_by_learning_path(self, learning_path_id: str) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"metadata.learning_path_id": learning_path_id}).sort(
                "order", 1
            )
        )

    def delete_many(self, chapter_ids: List[str | ObjectId]) -> int:
        if not chapter_ids:
            return 0
        object_ids = [self._to_object_id(item) for item in chapter_ids]
        result = self.collection.delete_many({"_id": {"$in": object_ids}})
        return result.deleted_count
