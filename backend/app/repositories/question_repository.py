"""MongoDB repository for lesson-scoped question bank."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId

from backend.app.database.mongo import get_db


class QuestionBankRepository:
    """Repository for `question_bank` collection."""

    collection_name = "question_bank"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        self.collection.create_index([("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("subject_id", 1), ("chapter_id", 1)])
        self.collection.create_index([("question_type", 1), ("difficulty", 1)])

    def insert_many(self, questions: List[Dict[str, Any]]) -> List[str]:
        if not questions:
            return []
        now = datetime.utcnow()
        payload = []
        for question in questions:
            item = dict(question)
            item.setdefault("created_at", now)
            payload.append(item)
        result = self.collection.insert_many(payload, ordered=False)
        return [str(item) for item in result.inserted_ids]

    def list_by_lesson(self, lesson_id: str | ObjectId) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"lesson_id": self._to_object_id(lesson_id)}).sort(
                "created_at", -1
            )
        )

    def delete_by_lesson(self, lesson_id: str | ObjectId) -> int:
        result = self.collection.delete_many(
            {"lesson_id": self._to_object_id(lesson_id)}
        )
        return result.deleted_count

    def delete_by_lesson_ids(self, lesson_ids: List[str | ObjectId]) -> int:
        if not lesson_ids:
            return 0
        object_ids = [self._to_object_id(item) for item in lesson_ids]
        result = self.collection.delete_many({"lesson_id": {"$in": object_ids}})
        return result.deleted_count

    def delete_by_resources_or_chunks(
        self,
        *,
        resource_ids: List[str | ObjectId],
        chunk_ids: List[str | ObjectId],
    ) -> int:
        clauses: List[Dict[str, Any]] = []
        if resource_ids:
            clauses.append(
                {
                    "resource_ids": {
                        "$in": [self._to_object_id(item) for item in resource_ids]
                    }
                }
            )
        if chunk_ids:
            clauses.append(
                {"chunk_ids": {"$in": [self._to_object_id(item) for item in chunk_ids]}}
            )
        if not clauses:
            return 0
        result = self.collection.delete_many({"$or": clauses})
        return result.deleted_count
