"""Batch job to precompute expected learning gain statistics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.app.database.mongo import get_db
from backend.app.repositories.expected_learning_gain_repository import (
    ExpectedLearningGainRepository,
)


class ComputeExpectedLearningGainJob:
    """Estimate resource-level learning gain from events with heuristic fallback."""

    def __init__(self) -> None:
        self.db = get_db()
        self.repository = ExpectedLearningGainRepository()
        self.learning_events = self.db.learning_events
        self.resource_quality_stats = self.db.resource_quality_stats
        self.resources = self.db.resources

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    def _quality_map(self) -> Dict[str, Dict[str, Any]]:
        return {
            str(item.get("resource_id") or item.get("resource_key")): item
            for item in self.resource_quality_stats.find()
        }

    def _completion_events(self, *, resource_id: Optional[str], incremental: bool) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"event_type": "resource_completed"}
        if resource_id:
            query["resource_id"] = str(resource_id)
        if incremental:
            query["created_at"] = {"$gte": datetime.utcnow() - timedelta(days=14)}
        return list(self.learning_events.find(query))

    def _quiz_event_map(self) -> Dict[str, List[Dict[str, Any]]]:
        result: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in self.learning_events.find({"event_type": "quiz_submitted"}).sort("created_at", 1):
            result[str(item.get("user_id") or "")].append(item)
        return result

    def run(
        self,
        *,
        resource_id: Optional[str] = None,
        incremental: bool = False,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        quality_map = self._quality_map()
        quiz_map = self._quiz_event_map()
        completion_events = self._completion_events(resource_id=resource_id, incremental=incremental)

        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for event in completion_events:
            resource_key = str(event.get("resource_id") or "").strip()
            if not resource_key:
                continue
            concept_ids = event.get("concept_ids") or ["general"]
            for concept_id in concept_ids:
                grouped[(resource_key, str(concept_id or "general"))].append(event)

        if not grouped and resource_id:
            grouped[(str(resource_id), "general")] = []

        written = 0
        payloads: List[Dict[str, Any]] = []
        for (resource_key, concept_id), events in grouped.items():
            quality = quality_map.get(resource_key, {})
            quality_score = self._safe_float(quality.get("quality_score"), 0.55)
            completion_scores: List[float] = []
            mastery_gains: List[float] = []
            confidence_gains: List[float] = []
            quiz_uplifts: List[float] = []

            for event in events:
                metadata = event.get("metadata") or {}
                completion_percent = self._clamp(
                    self._safe_float(metadata.get("completion_percent"), 100.0) / 100.0
                )
                dwell_ratio = self._clamp(
                    self._safe_float(metadata.get("dwell_time_seconds"), 300.0) / 900.0
                )
                user_id = str(event.get("user_id") or "")
                completion_scores.append(completion_percent)
                mastery_gains.append(
                    self._clamp(0.08 + 0.24 * quality_score + 0.20 * completion_percent + 0.12 * dwell_ratio)
                )
                confidence_gains.append(
                    self._clamp(0.06 + 0.18 * quality_score + 0.16 * completion_percent + 0.10 * dwell_ratio)
                )
                next_quiz_score = None
                for quiz_event in quiz_map.get(user_id, []):
                    if quiz_event.get("created_at") and event.get("created_at") and quiz_event["created_at"] >= event["created_at"]:
                        next_quiz_score = self._safe_float((quiz_event.get("metadata") or {}).get("score"), 0.0)
                        break
                quiz_uplifts.append(
                    self._clamp(
                        0.16 * quality_score
                        + 0.24 * completion_percent
                        + 0.22 * (next_quiz_score if next_quiz_score is not None else quality_score)
                    )
                )

            if not events:
                mastery_gains = [self._clamp(0.10 + 0.30 * quality_score)]
                confidence_gains = [self._clamp(0.08 + 0.22 * quality_score)]
                quiz_uplifts = [self._clamp(0.12 + 0.25 * quality_score)]

            payload = {
                "resource_id": resource_key,
                "concept_id": concept_id or "general",
                "avg_mastery_gain": round(sum(mastery_gains) / len(mastery_gains), 4),
                "avg_confidence_gain": round(sum(confidence_gains) / len(confidence_gains), 4),
                "avg_quiz_uplift": round(sum(quiz_uplifts) / len(quiz_uplifts), 4),
                "sample_size": len(events),
                "computed_at": datetime.now(timezone.utc),
            }
            payloads.append(payload)
            if dry_run:
                continue
            self.repository.upsert_stat(payload)
            written += 1

        return {
            "job": "expected_gain",
            "processed": len(grouped),
            "written": written if not dry_run else 0,
            "dry_run": dry_run,
            "items": payloads[:5],
        }


compute_expected_learning_gain_job = ComputeExpectedLearningGainJob()
