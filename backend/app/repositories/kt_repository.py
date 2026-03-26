"""Repository for concept-level knowledge tracing states."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.app.database.mongo import get_db


class KnowledgeTracingRepository:
    """MongoDB repository for `concept_mastery_states` collection."""

    collection_name = "concept_mastery_states"

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db[self.collection_name]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        try:
            self.collection.create_index(
                [("user_id", 1), ("concept_id", 1), ("lesson_id", 1)],
                unique=True,
                name="uniq_user_concept_lesson",
            )
            self.collection.create_index([("user_id", 1), ("last_updated_at", -1)])
            self.collection.create_index([("lesson_id", 1), ("last_updated_at", -1)])
            self.collection.create_index([("concept_id", 1), ("last_updated_at", -1)])
            self.collection.create_index([("subject_id", 1), ("last_updated_at", -1)])
        except Exception:
            # Keep pipeline available even if index creation fails.
            pass

    def get_state(
        self, *, user_id: str, concept_id: int, lesson_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        query: Dict[str, Any] = {
            "user_id": str(user_id),
            "concept_id": int(concept_id),
            "lesson_id": str(lesson_id) if lesson_id is not None else None,
        }
        return self.collection.find_one(query)

    def upsert_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.utcnow()
        document = dict(state)
        document.setdefault("last_updated_at", now)
        document.setdefault("last_interaction_at", now)

        query = {
            "user_id": str(document.get("user_id")),
            "concept_id": int(document.get("concept_id", 0)),
            "lesson_id": document.get("lesson_id"),
        }
        self.collection.update_one(
            query,
            {
                "$set": document,
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        stored = self.collection.find_one(query)
        return stored or document

    def list_user_states(
        self, *, user_id: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id)})
            .sort("last_updated_at", -1)
            .limit(max(1, limit))
        )

    def list_user_lesson_states(
        self, *, user_id: str, lesson_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return list(
            self.collection.find({"user_id": str(user_id), "lesson_id": str(lesson_id)})
            .sort("last_updated_at", -1)
            .limit(max(1, limit))
        )
