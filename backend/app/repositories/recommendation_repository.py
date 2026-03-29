"""Repository for recommendation candidates, learner state, and interaction signals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, Iterable, List, Tuple

from bson import ObjectId

from backend.app.database.mongo import get_db


class RecommendationRepository:
    """MongoDB access helpers for recommendation pipeline."""

    def __init__(self) -> None:
        self.db = get_db()
        self.resources = self.db.resources
        self.progress = self.db.progress
        self.concepts = self.db.concepts
        self.event_logs = self.db.event_logs
        self.lesson_recommended_chunks = self.db.lesson_recommended_chunks
        self.lesson_study_time = self.db.lesson_study_time
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create indexes for hybrid and collaborative retrieval queries."""
        try:
            self.event_logs.create_index(
                [("user_id", 1), ("timestamp", -1), ("event_type", 1)]
            )
            self.event_logs.create_index(
                [("resource_id", 1), ("timestamp", -1), ("event_type", 1)]
            )
            self.event_logs.create_index(
                [("lesson_id", 1), ("timestamp", -1), ("event_type", 1)]
            )
            self.lesson_recommended_chunks.create_index([("lesson_id", 1)])
            self.lesson_recommended_chunks.create_index([("resource_ids", 1)])
            self.lesson_study_time.create_index(
                [("user_id", 1), ("updated_at", -1), ("lesson_id", 1)]
            )
        except Exception:
            # Recommendation endpoints must stay available even if index creation fails.
            pass

    @staticmethod
    def _user_variants(user_id: str | int) -> List[Any]:
        variants: List[Any] = [str(user_id)]
        try:
            variants.append(int(user_id))
        except Exception:
            pass
        return variants

    @staticmethod
    def _to_object_id(value: Any) -> ObjectId | None:
        if isinstance(value, ObjectId):
            return value
        try:
            return ObjectId(str(value))
        except Exception:
            return None

    @staticmethod
    def _append_weight(target: Dict[str, float], key: str, value: float) -> None:
        if not key:
            return
        target[key] = float(target.get(key, 0.0)) + float(value)

    def _load_lesson_resource_map(self, lesson_ids: List[Any]) -> Dict[str, List[str]]:
        object_ids = [
            oid
            for oid in (self._to_object_id(item) for item in lesson_ids)
            if oid is not None
        ]
        if not object_ids:
            return {}

        docs = list(
            self.lesson_recommended_chunks.find(
                {"lesson_id": {"$in": object_ids}},
                {"lesson_id": 1, "resource_ids": 1},
            )
        )
        lesson_map: Dict[str, List[str]] = {}
        for doc in docs:
            lesson_key = str(doc.get("lesson_id"))
            resource_ids = [
                str(item) for item in doc.get("resource_ids", []) if item is not None
            ]
            if resource_ids:
                lesson_map[lesson_key] = resource_ids
        return lesson_map

    def get_user_progress(self, user_id: str | int) -> List[Dict[str, Any]]:
        return list(
            self.progress.find(
                {"user_id": {"$in": self._user_variants(user_id)}},
                {"concept_id": 1, "mastery": 1, "confidence": 1, "last_updated": 1},
            )
        )

    def find_goal_concepts(self, goal: str, limit: int = 50) -> List[Dict[str, Any]]:
        return list(
            self.concepts.find(
                {"topic": {"$regex": goal, "$options": "i"}},
                {"concept_id": 1, "concept_name": 1, "difficulty": 1, "topic": 1},
            )
            .sort("difficulty", 1)
            .limit(limit)
        )

    def find_resources_for_concepts(
        self,
        *,
        concept_ids: List[int],
        preferred_levels: List[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if not concept_ids:
            return []

        concept_query = {
            "$or": [
                {"concept_id": {"$in": concept_ids}},
                {"metadata.concept_id": {"$in": concept_ids}},
            ]
        }
        level_query = {
            "$or": [
                {"level": {"$in": preferred_levels}},
                {"metadata.level": {"$in": preferred_levels}},
            ]
        }

        docs = list(
            self.resources.find(
                {
                    "$and": [
                        concept_query,
                        level_query,
                    ]
                }
            ).limit(max(limit, 1))
        )

        if len(docs) < limit:
            seen_ids = {str(item.get("_id")) for item in docs}
            fallback_docs = list(
                self.resources.find(concept_query).limit(limit * 2)
            )
            for item in fallback_docs:
                key = str(item.get("_id"))
                if key in seen_ids:
                    continue
                docs.append(item)
                seen_ids.add(key)
                if len(docs) >= limit:
                    break

        return docs

    @staticmethod
    def get_resource_key(resource: Dict[str, Any]) -> str:
        if resource.get("resource_id") is not None:
            return str(resource.get("resource_id"))
        return str(resource.get("_id"))

    def get_resource_popularity(
        self, resource_keys: Iterable[str], days: int = 60
    ) -> Dict[str, float]:
        keys = [str(item) for item in resource_keys if item is not None]
        if not keys:
            return {}

        since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
        pipeline = [
            {
                "$match": {
                    "timestamp": {"$gte": since},
                    "event_type": {
                        "$in": [
                            "resource_clicked",
                            "resource_completed",
                            "recommendation_clicked",
                        ]
                    },
                    "resource_id": {"$exists": True, "$ne": None},
                }
            },
            {
                "$project": {
                    "resource_key": {"$toString": "$resource_id"},
                    "event_type": 1,
                }
            },
            {"$match": {"resource_key": {"$in": keys}}},
            {
                "$group": {
                    "_id": "$resource_key",
                    "clicked": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$event_type", "resource_clicked"]},
                                1,
                                0,
                            ]
                        }
                    },
                    "completed": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$event_type", "resource_completed"]},
                                1,
                                0,
                            ]
                        }
                    },
                    "rec_clicked": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$event_type", "recommendation_clicked"]},
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]

        popularity: Dict[str, float] = {}
        for row in self.event_logs.aggregate(pipeline):
            key = str(row.get("_id"))
            score = (
                float(row.get("clicked", 0))
                + 2.0 * float(row.get("completed", 0))
                + 1.2 * float(row.get("rec_clicked", 0))
            )
            popularity[key] = score

        return popularity

    def get_user_resource_interactions(
        self,
        user_id: str | int,
        days: int = 120,
    ) -> Dict[str, float]:
        since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
        direct_weights = {
            "resource_clicked": 1.0,
            "recommendation_clicked": 1.2,
            "resource_completed": 3.0,
        }
        interactions: Dict[str, float] = {}

        direct_events = self.event_logs.find(
            {
                "user_id": {"$in": self._user_variants(user_id)},
                "timestamp": {"$gte": since},
                "event_type": {
                    "$in": [*direct_weights.keys(), "recommendation_feedback"]
                },
                "resource_id": {"$exists": True, "$ne": None},
            },
            {"resource_id": 1, "event_type": 1, "metadata": 1, "duration_ms": 1},
        )
        for row in direct_events:
            resource_key = str(row.get("resource_id"))
            event_type = str(row.get("event_type"))
            score = float(direct_weights.get(event_type, 0.0))

            if event_type == "recommendation_feedback":
                feedback_type = str(
                    (row.get("metadata") or {}).get("feedback_type") or ""
                ).lower()
                score += {
                    "helpful": 1.8,
                    "save_for_later": 0.8,
                    "not_helpful": -1.0,
                    "hide": -1.5,
                }.get(feedback_type, 0.0)

            duration_ms = float(row.get("duration_ms") or 0.0)
            if duration_ms > 0:
                score += min(duration_ms / 300000.0, 1.0) * 0.6

            if score != 0.0:
                self._append_weight(interactions, resource_key, score)

        lesson_events = list(
            self.event_logs.find(
                {
                    "user_id": {"$in": self._user_variants(user_id)},
                    "timestamp": {"$gte": since},
                    "event_type": {"$in": ["lesson_completed", "quiz_submitted"]},
                    "lesson_id": {"$exists": True, "$ne": None},
                },
                {"lesson_id": 1, "event_type": 1},
            )
        )
        lesson_ids = [
            row.get("lesson_id")
            for row in lesson_events
            if row.get("lesson_id") is not None
        ]
        lesson_map = self._load_lesson_resource_map(lesson_ids)

        lesson_weights = {
            "lesson_completed": 2.5,
            "quiz_submitted": 1.6,
        }
        for row in lesson_events:
            lesson_key = str(self._to_object_id(row.get("lesson_id")) or "")
            resource_keys = lesson_map.get(lesson_key, [])
            if not resource_keys:
                continue
            base_weight = float(lesson_weights.get(str(row.get("event_type")), 0.0))
            if base_weight <= 0:
                continue
            distributed = base_weight / max(len(resource_keys), 1)
            for resource_key in resource_keys:
                self._append_weight(interactions, resource_key, distributed)

        study_rows = list(
            self.lesson_study_time.find(
                {
                    "user_id": {"$in": self._user_variants(user_id)},
                    "updated_at": {"$gte": since},
                    "lesson_id": {"$exists": True, "$ne": None},
                },
                {"lesson_id": 1, "seconds_spent": 1},
            )
        )
        seconds_by_lesson: Dict[str, int] = {}
        for row in study_rows:
            lesson_key = str(self._to_object_id(row.get("lesson_id")) or "")
            if not lesson_key:
                continue
            seconds_by_lesson[lesson_key] = seconds_by_lesson.get(lesson_key, 0) + int(
                row.get("seconds_spent") or 0
            )

        for lesson_key, total_seconds in seconds_by_lesson.items():
            resource_keys = lesson_map.get(lesson_key, [])
            if not resource_keys:
                continue
            # Keep time-spent as a small supportive implicit signal.
            time_weight = min(math.log1p(max(total_seconds, 0)) / 6.0, 1.0) * 0.9
            if time_weight <= 0:
                continue
            distributed = time_weight / max(len(resource_keys), 1)
            for resource_key in resource_keys:
                self._append_weight(interactions, resource_key, distributed)

        return {key: value for key, value in interactions.items() if value > 0.0}

    def get_peers_for_resources(
        self,
        *,
        resource_keys: List[str],
        exclude_user_id: str | int,
        days: int = 120,
        limit_users: int = 200,
    ) -> Dict[str, Dict[str, float]]:
        if not resource_keys:
            return {}

        since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
        pipeline = [
            {
                "$match": {
                    "timestamp": {"$gte": since},
                    "event_type": {
                        "$in": [
                            "resource_clicked",
                            "recommendation_clicked",
                            "resource_completed",
                        ]
                    },
                    "resource_id": {"$exists": True, "$ne": None},
                }
            },
            {
                "$project": {
                    "user_key": {"$toString": "$user_id"},
                    "resource_key": {"$toString": "$resource_id"},
                    "event_type": 1,
                }
            },
            {
                "$match": {
                    "resource_key": {"$in": [str(item) for item in resource_keys]}
                }
            },
            {
                "$group": {
                    "_id": {
                        "user_key": "$user_key",
                        "resource_key": "$resource_key",
                        "event_type": "$event_type",
                    },
                    "count": {"$sum": 1},
                }
            },
            {
                "$group": {
                    "_id": {
                        "user_key": "$_id.user_key",
                        "resource_key": "$_id.resource_key",
                    },
                    "clicked": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.event_type", "resource_clicked"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                    "rec_clicked": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.event_type", "recommendation_clicked"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                    "completed": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$_id.event_type", "resource_completed"]},
                                "$count",
                                0,
                            ]
                        }
                    },
                }
            },
            {
                "$group": {
                    "_id": "$_id.user_key",
                    "items": {
                        "$push": {
                            "resource_key": "$_id.resource_key",
                            "clicked": "$clicked",
                            "rec_clicked": "$rec_clicked",
                            "completed": "$completed",
                        }
                    },
                }
            },
            {"$limit": max(limit_users, 1)},
        ]

        exclude_key = str(exclude_user_id)
        peers: Dict[str, Dict[str, float]] = {}
        for row in self.event_logs.aggregate(pipeline):
            user_key = str(row.get("_id"))
            if user_key == exclude_key:
                continue
            vector: Dict[str, float] = {}
            for item in row.get("items", []):
                resource_key = str(item.get("resource_key"))
                score = (
                    float(item.get("clicked", 0))
                    + 1.2 * float(item.get("rec_clicked", 0))
                    + 3.0 * float(item.get("completed", 0))
                )
                if score > 0:
                    vector[resource_key] = score
            if vector:
                peers[user_key] = vector

        key_set = {str(item) for item in resource_keys}
        candidate_object_ids = [
            oid
            for oid in (self._to_object_id(item) for item in key_set)
            if oid is not None
        ]
        if candidate_object_ids:
            lesson_docs = list(
                self.lesson_recommended_chunks.find(
                    {"resource_ids": {"$in": candidate_object_ids}},
                    {"lesson_id": 1, "resource_ids": 1},
                )
            )
            lesson_to_candidate_resources: Dict[str, List[str]] = {}
            for doc in lesson_docs:
                lesson_key = str(doc.get("lesson_id"))
                matched = [
                    str(item)
                    for item in doc.get("resource_ids", [])
                    if str(item) in key_set
                ]
                if matched:
                    lesson_to_candidate_resources[lesson_key] = matched

            if lesson_to_candidate_resources:
                lesson_object_ids = [
                    self._to_object_id(item)
                    for item in lesson_to_candidate_resources.keys()
                ]
                lesson_object_ids = [
                    item for item in lesson_object_ids if item is not None
                ]

                lesson_events = self.event_logs.find(
                    {
                        "timestamp": {"$gte": since},
                        "event_type": {"$in": ["lesson_completed", "quiz_submitted"]},
                        "lesson_id": {"$in": lesson_object_ids},
                        "user_id": {"$exists": True, "$ne": None},
                    },
                    {"user_id": 1, "lesson_id": 1, "event_type": 1},
                )

                lesson_weights = {"lesson_completed": 2.2, "quiz_submitted": 1.4}
                for row in lesson_events:
                    user_key = str(row.get("user_id"))
                    if user_key == exclude_key:
                        continue
                    lesson_key = str(row.get("lesson_id"))
                    matched_resources = lesson_to_candidate_resources.get(
                        lesson_key, []
                    )
                    if not matched_resources:
                        continue
                    weight = float(lesson_weights.get(str(row.get("event_type")), 0.0))
                    if weight <= 0:
                        continue
                    distributed = weight / max(len(matched_resources), 1)
                    peer_vector = peers.setdefault(user_key, {})
                    for resource_key in matched_resources:
                        peer_vector[resource_key] = (
                            float(peer_vector.get(resource_key, 0.0)) + distributed
                        )

                study_rows = self.lesson_study_time.find(
                    {
                        "updated_at": {"$gte": since},
                        "lesson_id": {"$in": lesson_object_ids},
                        "user_id": {"$exists": True, "$ne": None},
                    },
                    {"user_id": 1, "lesson_id": 1, "seconds_spent": 1},
                )
                for row in study_rows:
                    user_key = str(row.get("user_id"))
                    if user_key == exclude_key:
                        continue
                    lesson_key = str(row.get("lesson_id"))
                    matched_resources = lesson_to_candidate_resources.get(
                        lesson_key, []
                    )
                    if not matched_resources:
                        continue
                    seconds_spent = int(row.get("seconds_spent") or 0)
                    weight = min(math.log1p(max(seconds_spent, 0)) / 6.0, 1.0) * 0.6
                    if weight <= 0:
                        continue
                    distributed = weight / max(len(matched_resources), 1)
                    peer_vector = peers.setdefault(user_key, {})
                    for resource_key in matched_resources:
                        peer_vector[resource_key] = (
                            float(peer_vector.get(resource_key, 0.0)) + distributed
                        )

        peers = {user_key: vector for user_key, vector in peers.items() if vector}
        return peers

    def get_user_format_preference(
        self, user_id: str | int, days: int = 120
    ) -> Dict[str, float]:
        since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
        clicked_resource_ids = self.event_logs.distinct(
            "resource_id",
            {
                "user_id": {"$in": self._user_variants(user_id)},
                "timestamp": {"$gte": since},
                "event_type": {
                    "$in": [
                        "resource_clicked",
                        "resource_completed",
                        "recommendation_clicked",
                    ]
                },
                "resource_id": {"$exists": True, "$ne": None},
            },
        )
        if not clicked_resource_ids:
            return {}

        resources = list(
            self.resources.find(
                {"_id": {"$in": clicked_resource_ids}},
                {"source": 1, "type": 1, "metadata.pedagogy_type": 1},
            )
        )

        counts: Dict[str, float] = {}
        for resource in resources:
            fmt = str(
                resource.get("type") or resource.get("source") or "unknown"
            ).lower()
            counts[fmt] = counts.get(fmt, 0.0) + 1.0

        total = sum(counts.values())
        if total <= 0:
            return {}
        return {key: value / total for key, value in counts.items()}

    def get_recently_seen_resources(
        self, user_id: str | int, limit: int = 20
    ) -> List[str]:
        rows = list(
            self.event_logs.find(
                {
                    "user_id": {"$in": self._user_variants(user_id)},
                    "event_type": {
                        "$in": [
                            "resource_clicked",
                            "recommendation_clicked",
                            "recommendation_shown",
                        ]
                    },
                    "resource_id": {"$exists": True, "$ne": None},
                },
                {"resource_id": 1},
            )
            .sort("timestamp", -1)
            .limit(max(limit, 1))
        )
        return [
            str(item.get("resource_id"))
            for item in rows
            if item.get("resource_id") is not None
        ]
