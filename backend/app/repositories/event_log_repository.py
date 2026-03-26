"""Repository for event-based logging and event queries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging
import uuid

logger = logging.getLogger(__name__)


class EventLogRepository:
    """Store and query event logs in MongoDB."""

    def __init__(self, db):
        self.db = db
        self.collection = db.event_logs
        self._create_indexes()

    def _create_indexes(self) -> None:
        try:
            self.collection.create_index([("event_id", 1)], unique=True)
            self.collection.create_index([("user_id", 1), ("timestamp", -1)])
            self.collection.create_index([("event_type", 1), ("timestamp", -1)])
            self.collection.create_index(
                [("path_id", 1), ("lesson_id", 1), ("timestamp", -1)]
            )
            self.collection.create_index([("session_id", 1), ("timestamp", -1)])
            self.collection.create_index([("timestamp", -1)])
        except Exception as exc:
            logger.warning("Failed to create event_logs indexes: %s", exc)

    def create_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event = dict(payload)
        event.setdefault("event_id", str(uuid.uuid4()))
        event.setdefault("timestamp", datetime.now(timezone.utc))

        result = self.collection.insert_one(event)
        event["_id"] = result.inserted_id
        return event

    def create_events(self, payloads: List[Dict[str, Any]]) -> int:
        documents = []
        now = datetime.now(timezone.utc)
        for payload in payloads:
            item = dict(payload)
            item.setdefault("event_id", str(uuid.uuid4()))
            item.setdefault("timestamp", now)
            documents.append(item)

        if not documents:
            return 0

        result = self.collection.insert_many(documents)
        return len(result.inserted_ids)

    def find_events(
        self,
        *,
        query: Dict[str, Any],
        limit: int = 500,
        sort: Optional[List[tuple[str, int]]] = None,
    ) -> List[Dict[str, Any]]:
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        return list(cursor.limit(limit))

    def count_events(self, query: Dict[str, Any]) -> int:
        return int(self.collection.count_documents(query))
