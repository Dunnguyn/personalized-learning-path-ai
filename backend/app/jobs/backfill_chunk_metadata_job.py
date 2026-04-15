"""Batch job to backfill chunk semantic metadata and resource chunk profiles."""

from __future__ import annotations

from typing import Any, Dict, Optional

from bson import ObjectId
from pymongo import UpdateOne

from backend.app.repositories import ResourceChunkRepository, ResourceRepository
from backend.app.services.chunk_service import (
    aggregate_chunk_profile,
    derive_chunk_metadata,
)


class BackfillChunkMetadataJob:
    """Populate chunk-level semantic metadata for legacy ingested resources."""

    REQUIRED_CHUNK_FIELDS = (
        "chunk_summary",
        "chunk_keywords",
        "instruction_role",
        "content_kind",
        "questionability_score",
        "token_count",
        "sentence_count",
        "has_code",
    )

    def __init__(self) -> None:
        self.resource_repository = ResourceRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.resources = self.resource_repository.collection
        self.chunks = self.chunk_repository.collection

    def _resource_query(
        self,
        *,
        resource_id: Optional[str],
        full: bool,
    ) -> Dict[str, Any]:
        base_query: Dict[str, Any] = {
            "status": "done",
            "chunks_count": {"$gt": 0},
        }
        if resource_id:
            clauses = []
            if ObjectId.is_valid(str(resource_id)):
                clauses.append({"_id": ObjectId(str(resource_id))})
            clauses.append({"resource_id": str(resource_id)})
            return {**base_query, "$or": clauses}
        if full:
            return base_query
        return {
            **base_query,
            "$or": [
                {"metadata.chunk_profile": {"$exists": False}},
                {"metadata.chunk_profile.top_keywords": {"$exists": False}},
            ]
        }

    def _chunk_needs_backfill(self, chunk: Dict[str, Any], *, full: bool) -> bool:
        if full:
            return True
        metadata = chunk.get("metadata") or {}
        for field in self.REQUIRED_CHUNK_FIELDS:
            if field not in metadata:
                return True
        return False

    def run(
        self,
        *,
        full: bool = False,
        resource_id: Optional[str] = None,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        query = self._resource_query(resource_id=resource_id, full=full)
        cursor = self.resources.find(query).sort("updated_at", -1)
        if limit and limit > 0:
            cursor = cursor.limit(int(limit))

        processed_resources = 0
        updated_resources = 0
        processed_chunks = 0
        updated_chunks = 0
        sample_items = []

        for resource in cursor:
            processed_resources += 1
            resource_chunks = self.chunk_repository.get_by_resource_ids([resource["_id"]])
            if not resource_chunks:
                continue

            chunk_updates = []
            refreshed_chunks = []
            for chunk in resource_chunks:
                processed_chunks += 1
                metadata = dict(chunk.get("metadata") or {})
                if self._chunk_needs_backfill(chunk, full=full):
                    derived = derive_chunk_metadata(
                        str(chunk.get("content") or ""),
                        base_metadata=metadata,
                    )
                    merged_metadata = {**metadata, **derived}
                    refreshed_chunk = {**chunk, "metadata": merged_metadata}
                    refreshed_chunks.append(refreshed_chunk)
                    updated_chunks += 1
                    if not dry_run:
                        chunk_updates.append(
                            UpdateOne(
                                {"_id": chunk["_id"]},
                                {"$set": {"metadata": merged_metadata}},
                            )
                        )
                else:
                    refreshed_chunks.append(chunk)

            chunk_profile = aggregate_chunk_profile(refreshed_chunks)
            resource_metadata = dict(resource.get("metadata") or {})
            previous_profile = resource_metadata.get("chunk_profile") or {}
            resource_changed = full or chunk_profile != previous_profile
            if resource_changed:
                updated_resources += 1
                resource_metadata["chunk_profile"] = chunk_profile
                if not dry_run:
                    self.resources.update_one(
                        {"_id": resource["_id"]},
                        {"$set": {"metadata": resource_metadata}},
                    )

            if chunk_updates and not dry_run:
                self.chunks.bulk_write(chunk_updates, ordered=False)

            sample_items.append(
                {
                    "resource_id": str(resource.get("_id")),
                    "title": str(resource.get("title") or ""),
                    "chunk_count": len(resource_chunks),
                    "chunk_updates": len(chunk_updates),
                    "profile_keywords": chunk_profile.get("top_keywords", [])[:6],
                }
            )

        return {
            "job": "chunk_metadata_backfill",
            "processed_resources": processed_resources,
            "updated_resources": 0 if dry_run else updated_resources,
            "processed_chunks": processed_chunks,
            "updated_chunks": 0 if dry_run else updated_chunks,
            "dry_run": dry_run,
            "mode": "full" if full else "targeted",
            "items": sample_items[:5],
        }


backfill_chunk_metadata_job = BackfillChunkMetadataJob()
