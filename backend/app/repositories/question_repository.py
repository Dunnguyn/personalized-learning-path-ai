"""MongoDB repository for lesson-scoped question storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId

from backend.app.database.mongo import get_db


class LessonQuestionRepository:
    """Repository for lesson-specific questions."""

    collection_name = "lesson_questions"
    legacy_collection_name = "question_bank"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.legacy_collection = self.db[self.legacy_collection_name]

    @staticmethod
    def _to_object_id(value: str | ObjectId) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        return ObjectId(value)

    def ensure_indexes(self) -> None:
        for collection in (self.collection, self.legacy_collection):
            collection.create_index([("lesson_id", 1), ("created_at", -1)])
            collection.create_index([("subject_id", 1), ("chapter_id", 1)])
            collection.create_index([("question_type", 1), ("difficulty", 1)])
            collection.create_index([("metadata.question_set_kind", 1), ("created_at", -1)])

    @staticmethod
    def _build_question_set_kind_clause(question_set_kind: str | None) -> Dict[str, Any]:
        normalized_kind = str(question_set_kind or "").strip().lower()
        if not normalized_kind:
            return {}
        if normalized_kind == "standard":
            return {
                "$or": [
                    {"metadata.question_set_kind": "standard"},
                    {"metadata.question_set_kind": {"$exists": False}},
                    {"metadata": {"$exists": False}},
                ]
            }
        return {"metadata.question_set_kind": normalized_kind}

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

    def list_by_lesson(
        self,
        lesson_id: str | ObjectId,
        question_set_kind: str | None = None,
    ) -> List[Dict[str, Any]]:
        query = {
            "lesson_id": self._to_object_id(lesson_id),
            **self._build_question_set_kind_clause(question_set_kind),
        }
        questions = list(self.collection.find(query).sort("created_at", -1))
        if questions:
            return questions
        return list(self.legacy_collection.find(query).sort("created_at", -1))

    def delete_by_lesson(
        self,
        lesson_id: str | ObjectId,
        question_set_kind: str | None = None,
    ) -> int:
        query = {
            "lesson_id": self._to_object_id(lesson_id),
            **self._build_question_set_kind_clause(question_set_kind),
        }
        removed_primary = self.collection.delete_many(query).deleted_count
        removed_legacy = self.legacy_collection.delete_many(query).deleted_count
        return removed_primary + removed_legacy

    def delete_by_lesson_ids(self, lesson_ids: List[str | ObjectId]) -> int:
        if not lesson_ids:
            return 0
        object_ids = [self._to_object_id(item) for item in lesson_ids]
        query = {"lesson_id": {"$in": object_ids}}
        removed_primary = self.collection.delete_many(query).deleted_count
        removed_legacy = self.legacy_collection.delete_many(query).deleted_count
        return removed_primary + removed_legacy

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
        query = {"$or": clauses}
        removed_primary = self.collection.delete_many(query).deleted_count
        removed_legacy = self.legacy_collection.delete_many(query).deleted_count
        return removed_primary + removed_legacy


QuestionBankRepository = LessonQuestionRepository
