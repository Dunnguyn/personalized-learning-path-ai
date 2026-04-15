"""Semantic memory store for active lesson questions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence

from backend.app.database.mongo import get_db


class QuestionSemanticMemoryRepository:
    """Persist active question embeddings for semantic deduplication."""

    collection_name = "question_semantic_memory"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index([("question_id", 1)], unique=True)
        self.collection.create_index([("lesson_id", 1), ("created_at", -1)])
        self.collection.create_index([("subject_id", 1), ("created_at", -1)])
        self.collection.create_index([("concept_ids", 1), ("created_at", -1)])

    def insert_many(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        now = datetime.utcnow()
        normalized: List[Dict[str, Any]] = []
        for item in records:
            document = dict(item)
            document["question_id"] = str(document.get("question_id") or "").strip()
            document["subject_id"] = str(document.get("subject_id") or "").strip()
            document["chapter_id"] = str(document.get("chapter_id") or "").strip()
            document["lesson_id"] = str(document.get("lesson_id") or "").strip()
            document["question_type"] = str(document.get("question_type") or "").strip()
            document["concept_ids"] = [
                str(value).strip()
                for value in (document.get("concept_ids") or [])
                if str(value).strip()
            ]
            document["semantic_text"] = str(document.get("semantic_text") or "").strip()
            document["embedding"] = [
                float(value)
                for value in (document.get("embedding") or [])
            ]
            document.setdefault("created_at", now)
            normalized.append(document)
        result = self.collection.insert_many(normalized, ordered=False)
        return len(result.inserted_ids)

    def delete_by_lesson(self, lesson_id: str) -> int:
        result = self.collection.delete_many({"lesson_id": str(lesson_id)})
        return int(result.deleted_count or 0)

    def find_candidates(
        self,
        *,
        subject_id: str,
        exclude_lesson_id: str | None = None,
        concept_ids: Sequence[str] | None = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"subject_id": str(subject_id)}
        if exclude_lesson_id:
            query["lesson_id"] = {"$ne": str(exclude_lesson_id)}
        normalized_concepts = [
            str(value).strip()
            for value in (concept_ids or [])
            if str(value).strip()
        ]
        if normalized_concepts:
            query["concept_ids"] = {"$in": normalized_concepts}
        return list(
            self.collection.find(
                query,
                {
                    "_id": 0,
                    "question_id": 1,
                    "lesson_id": 1,
                    "subject_id": 1,
                    "question_type": 1,
                    "concept_ids": 1,
                    "semantic_text": 1,
                    "embedding": 1,
                    "created_at": 1,
                },
            )
            .sort("created_at", -1)
            .limit(max(1, int(limit or 200)))
        )
