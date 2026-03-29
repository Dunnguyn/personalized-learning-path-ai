"""Batch job to precompute resource quality stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.services.resource_quality_service import resource_quality_service


class ComputeResourceQualityJob:
    """Precompute and upsert quality stats for resources."""

    def __init__(self) -> None:
        self.db = get_db()
        self.resources = self.db.resources
        self.quality_stats = self.db.resource_quality_stats

    def run(
        self,
        *,
        full: bool = False,
        incremental: bool = False,
        resource_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if resource_id:
            query["$or"] = [{"resource_id": resource_id}]
            if ObjectId.is_valid(str(resource_id)):
                query["$or"].append({"_id": ObjectId(str(resource_id))})

        if incremental and not full:
            since = datetime.utcnow() - timedelta(days=2)
            query["updated_at"] = {"$gte": since}

        processed = 0
        written = 0
        sample_items = []
        for resource in self.resources.find(query):
            processed += 1
            payload = resource_quality_service.get_resource_quality(resource)
            sample_size = int(payload.get("sample_size") or 0)
            payload["computed_at"] = datetime.now(timezone.utc)
            payload["sample_size"] = max(sample_size, 1 if payload.get("quality_score") else 0)
            sample_items.append(payload)
            if dry_run:
                continue
            self.quality_stats.update_one(
                {"resource_key": str(payload["resource_id"])},
                {"$set": payload},
                upsert=True,
            )
            written += 1

        return {
            "job": "quality",
            "processed": processed,
            "written": written if not dry_run else 0,
            "dry_run": dry_run,
            "mode": "full" if full else "incremental" if incremental else "targeted",
            "items": sample_items[:5],
        }


compute_resource_quality_job = ComputeResourceQualityJob()
