"""Resource-facing service layer built on repositories and ingestion pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from bson import ObjectId
from fastapi import BackgroundTasks, UploadFile

from backend.app.api.schemas import ResourceCreate, ResourceImportRequest
from backend.app.database.mongo import get_db
from backend.app.repositories import (
    LessonRecommendedChunkRepository,
    LessonRepository,
    LessonQuestionRepository,
    ResourceChunkRepository,
    ResourceRepository,
)
from backend.app.services.recommendation.normalization import extract_resource_keys
from backend.app.services.embedding_service import embedding_service, semantic_search
from backend.app.services.ingestion_service import ingestion_service
from backend.app.services.resource_quality_service import resource_quality_service

logger = logging.getLogger(__name__)

_resource_repository = ResourceRepository()
_chunk_repository = ResourceChunkRepository()
_lesson_repository = LessonRepository()
_lesson_recommended_chunk_repository = LessonRecommendedChunkRepository()
_question_repository = LessonQuestionRepository()


def _get_completed_lesson_ids(user_id: Optional[str]) -> Set[str]:
    """Collect lesson ids that are marked complete/completed for a given user."""
    if not user_id:
        return set()

    collection = get_db().learning_paths
    cursor = collection.find(
        {"user_id": str(user_id)},
        {"lesson_progress": 1},
    )

    completed_lesson_ids: Set[str] = set()
    for path in cursor:
        lesson_progress = path.get("lesson_progress") or {}
        if not isinstance(lesson_progress, dict):
            continue

        for lesson_id, status in lesson_progress.items():
            normalized_status = str(status or "").strip().lower()
            if normalized_status in {"complete", "completed"}:
                completed_lesson_ids.add(str(lesson_id))

    return completed_lesson_ids


def _get_completed_resource_identifiers(user_id: Optional[str]) -> Set[str]:
    """Collect completed resource identifiers for a user from learner signals."""
    if not user_id:
        return set()

    collection = get_db().learner_signals
    completed_lesson_ids = _get_completed_lesson_ids(user_id)
    cursor = collection.find(
        {
            "user_id": str(user_id),
            "signal_type": "resource_completed",
        },
        {
            "resource_id": 1,
            "metadata.resource_identifier": 1,
        },
    )

    identifiers: Set[str] = set()
    for signal in cursor:
        lesson_id = signal.get("lesson_id")
        metadata = signal.get("metadata") or {}
        lesson_identifier = lesson_id or metadata.get("lesson_id")

        # Lesson-scoped chunk resources are only completed when their lesson is complete.
        if lesson_identifier and str(lesson_identifier) not in completed_lesson_ids:
            continue

        identifiers.update(
            extract_resource_keys(
                {
                    "resource_id": signal.get("resource_id"),
                    "metadata": metadata,
                }
            )
        )

    return identifiers


def _is_resource_completed(
    resource_document: Dict[str, Any], completed_identifiers: Set[str]
) -> bool:
    if not completed_identifiers:
        return False

    return bool(extract_resource_keys(resource_document) & completed_identifiers)


def serialize_mongo(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB objects into JSON-friendly primitives."""
    def _json_safe(value: Any) -> Any:
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [_json_safe(item) for item in value]
        if isinstance(value, set):
            return [_json_safe(item) for item in value]
        return value

    return _json_safe(dict(document))


def get_resources_service(
    page: int = 1,
    size: int = 10,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
    resource_type: Optional[str] = None,
    concept_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """List top-level resources from the unified collection."""
    result = _resource_repository.list(
        page=page,
        size=size,
        topic=topic,
        level=level,
        source=source,
        resource_type=resource_type,
        concept_id=concept_id,
    )
    completed_identifiers = _get_completed_resource_identifiers(user_id)
    serialized_items = []
    for item in result["items"]:
        serialized = serialize_mongo(item)
        serialized["is_completed"] = _is_resource_completed(
            item, completed_identifiers
        )
        serialized_items.append(serialized)

    return {
        "resources": serialized_items,
        "total": result["total"],
        "page": result["page"],
        "size": result["size"],
        "pages": result["pages"],
    }


def add_resource_service(
    resource: ResourceCreate,
    *,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit manual text ingestion as a background job."""
    return ingestion_service.submit_text_job(
        background_tasks=background_tasks,
        title=resource.title,
        content=resource.content,
        topic=resource.topic,
        level=(
            resource.level.value
            if hasattr(resource.level, "value")
            else str(resource.level)
        ),
        source=(
            resource.source.value
            if hasattr(resource.source, "value")
            else str(resource.source)
        ),
        concept_id=resource.concept_id,
        url=resource.url,
        user_id=user_id,
    )


def import_resources_service(
    data: ResourceImportRequest,
    *,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit a batch of manual text ingestions."""
    submissions: List[Dict[str, Any]] = []
    for resource in data.resources:
        submissions.append(
            ingestion_service.submit_text_job(
                background_tasks=background_tasks,
                title=resource.title,
                content=resource.content,
                topic=resource.topic,
                level=(
                    resource.level.value
                    if hasattr(resource.level, "value")
                    else str(resource.level)
                ),
                source=(
                    resource.source.value
                    if hasattr(resource.source, "value")
                    else str(resource.source)
                ),
                concept_id=resource.concept_id,
                url=resource.url,
                user_id=user_id,
            )
        )

    return {
        "total": len(submissions),
        "submitted": len(submissions),
        "items": submissions,
    }


def search_resources_service(
    q: str,
    page: int = 1,
    size: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Search resources semantically over chunk collection."""
    if not q or not q.strip():
        raise ValueError("Search query cannot be empty.")
    filters = filters or {}
    results = semantic_search(
        query=q.strip(),
        k=max(page * size + 50, size),
        topic=filters.get("topic"),
        level=filters.get("level"),
        min_score=float(filters.get("min_score", 0.35)),
    )
    start = max(page - 1, 0) * size
    paged = results[start : start + size]
    completed_identifiers = _get_completed_resource_identifiers(user_id)
    enriched_results = []
    for item in paged:
        resource_identifier = item.get("resource_id")
        item_with_status = {
            **item,
            "is_completed": (
                resource_identifier is not None
                and str(resource_identifier) in completed_identifiers
            ),
        }
        enriched_results.append(item_with_status)

    return {
        "results": enriched_results,
        "total": len(results),
        "page": page,
        "size": size,
    }


def import_pdf_service(
    file: UploadFile,
    *,
    background_tasks: BackgroundTasks,
    topic: str,
    level: str,
    concept_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit PDF ingestion."""
    return ingestion_service.submit_pdf_job(
        background_tasks=background_tasks,
        file=file,
        topic=topic,
        level=level,
        concept_id=concept_id,
        user_id=user_id,
    )


def import_youtube_service(
    youtube_url: str,
    *,
    background_tasks: BackgroundTasks,
    title: Optional[str],
    topic: str,
    level: str,
    concept_id: Optional[int] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit YouTube ingestion."""
    return ingestion_service.submit_youtube_job(
        background_tasks=background_tasks,
        youtube_url=youtube_url,
        title=title,
        topic=topic,
        level=level,
        concept_id=concept_id,
        user_id=user_id,
    )


def get_ingestion_job_status_service(job_id: str) -> Dict[str, Any]:
    """Return background ingestion job status."""
    return ingestion_service.get_job_status(job_id)


def get_pdf_file_path(resource_id: str) -> Path:
    """Resolve the stored PDF path for a resource."""
    resource = _resource_repository.get(resource_id)
    if not resource:
        raise ValueError("Resource not found.")
    pdf_path = resource.get("metadata", {}).get("pdf_file_path")
    if not pdf_path:
        raise ValueError("Resource does not have an associated PDF file.")
    return Path(pdf_path)


def get_resource_by_id_service(resource_id: str) -> Dict[str, Any]:
    """Return a single top-level resource with flattened metadata."""
    resource = _resource_repository.get(resource_id)
    if not resource:
        raise ValueError("Resource not found.")

    metadata = resource.get("metadata", {}) or {}
    return {
        "resource_id": str(resource["_id"]),
        "title": str(resource.get("title") or ""),
        "source": str(resource.get("source") or "manual"),
        "type": str(resource.get("type") or "text"),
        "topic": str(resource.get("topic") or ""),
        "level": metadata.get("level"),
        "concept_id": metadata.get("concept_id"),
        "url": metadata.get("url"),
        "content_summary": resource.get("content_summary"),
        "status": resource.get("status"),
        "chunks_count": int(resource.get("chunks_count", 0)),
        "processing_time": float(resource.get("processing_time", 0.0)),
        "metadata": metadata,
        "created_at": resource.get("created_at"),
        "updated_at": resource.get("updated_at"),
    }


def delete_resource_service(resource_id: str) -> Dict[str, Any]:
    """Delete a top-level resource and its derived chunk documents."""
    resource = _resource_repository.get(resource_id)
    if not resource:
        raise ValueError("Resource not found.")

    chunks = _chunk_repository.get_by_resource_ids([resource_id])
    chunk_ids = [str(chunk["_id"]) for chunk in chunks]
    vector_ids = [
        f"{resource_id}:{int(chunk.get('chunk_index', 0))}" for chunk in chunks
    ]

    affected_recommendations = (
        _lesson_recommended_chunk_repository.find_by_resources_or_chunks(
            resource_ids=[resource_id],
            chunk_ids=chunk_ids,
        )
    )
    affected_lesson_ids = [
        str(item["lesson_id"])
        for item in affected_recommendations
        if item.get("lesson_id")
    ]

    recommendation_ids = [
        item["_id"] for item in affected_recommendations if item.get("_id")
    ]
    if recommendation_ids:
        _lesson_recommended_chunk_repository.delete_many_by_ids(recommendation_ids)

    if affected_lesson_ids:
        _lesson_repository.update_many(
            affected_lesson_ids,
            {
                "recommended_chunk_ids": [],
                "recommended_resource_ids": [],
            },
        )

    removed_lesson_questions = _question_repository.delete_by_resources_or_chunks(
        resource_ids=[resource_id],
        chunk_ids=chunk_ids,
    )

    if vector_ids:
        embedding_service.vector_store.delete_chunks(vector_ids)

    _chunk_repository.delete_for_resource(resource_id)

    pdf_path = resource.get("metadata", {}).get("pdf_file_path")
    if pdf_path:
        try:
            path = Path(pdf_path)
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning(
                "Could not delete stored PDF for resource %s",
                resource_id,
                exc_info=True,
            )

    deleted_count = _resource_repository.delete(resource_id)
    if deleted_count == 0:
        raise ValueError("Resource not found.")

    return {
        "resource_id": str(resource_id),
        "deleted": True,
        "removed_chunks": len(chunk_ids),
        "removed_recommendations": len(recommendation_ids),
        "removed_lesson_questions": removed_lesson_questions,
    }


def get_resource_stats(user_id: Optional[str] = None) -> Dict[str, Any]:
    """Basic analytics for top-level resources."""
    query = {}
    if user_id:
        query["metadata.submitted_by"] = user_id
    collection = _resource_repository.collection
    total = collection.count_documents(query)
    pipeline = [
        {"$match": query},
        {
            "$facet": {
                "by_source": [{"$group": {"_id": "$source", "count": {"$sum": 1}}}],
                "by_type": [{"$group": {"_id": "$type", "count": {"$sum": 1}}}],
                "recent": [
                    {"$sort": {"created_at": -1}},
                    {"$limit": 10},
                ],
            }
        },
    ]
    aggregated = list(collection.aggregate(pipeline))
    if not aggregated:
        return {
            "total_resources": total,
            "by_source": {},
            "by_type": {},
            "recent_resources": [],
        }
    facet = aggregated[0]
    return {
        "total_resources": total,
        "by_source": {
            item["_id"]: item["count"] for item in facet.get("by_source", [])
        },
        "by_type": {item["_id"]: item["count"] for item in facet.get("by_type", [])},
        "recent_resources": [serialize_mongo(item) for item in facet.get("recent", [])],
    }


def _normalize_curated_concept_ids(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    normalized: List[str] = []
    seen: Set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _build_resource_curation_item(
    resource: Dict[str, Any],
    *,
    duplicate_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    metadata = resource.get("metadata") or {}
    quality = resource_quality_service.get_resource_quality(resource)
    resource_id = str(resource.get("_id") or "")
    duplicate_info = duplicate_map.get(resource_id) or {}
    curated_concept_ids = _normalize_curated_concept_ids(
        metadata.get("curated_concept_ids")
    )
    fallback_concept_id = metadata.get("concept_id")
    if fallback_concept_id is not None and str(fallback_concept_id) not in curated_concept_ids:
        curated_concept_ids.append(str(fallback_concept_id))

    problem_flags: List[str] = []
    if quality.get("quality_score", 0.0) < 0.6:
        problem_flags.append("low_quality")
    if duplicate_info.get("duplicate_count", 0) > 1:
        problem_flags.append("duplicate_candidate")
    if str(resource.get("status") or "").lower() in {"failed", "error"}:
        problem_flags.append("ingestion_failed")
    if int(resource.get("chunks_count") or 0) <= 0:
        problem_flags.append("missing_chunks")

    return {
        "resource_id": resource_id,
        "title": str(resource.get("title") or ""),
        "topic": str(resource.get("topic") or ""),
        "source": str(resource.get("source") or ""),
        "type": str(resource.get("type") or ""),
        "status": str(resource.get("status") or ""),
        "chunks_count": int(resource.get("chunks_count") or 0),
        "quality_score": round(float(quality.get("quality_score", 0.0) or 0.0), 4),
        "quality_label": str(metadata.get("quality_label") or ""),
        "quality_breakdown": quality,
        "curated_concept_ids": curated_concept_ids,
        "admin_notes": str(metadata.get("admin_notes") or ""),
        "hidden_from_recommendation": bool(
            metadata.get("hidden_from_recommendation", False)
        ),
        "duplicate_key": duplicate_info.get("duplicate_key"),
        "duplicate_count": int(duplicate_info.get("duplicate_count") or 0),
        "problem_flags": problem_flags,
        "updated_at": resource.get("updated_at"),
    }


def get_admin_resource_curation_service(
    *,
    limit: int = 20,
    status: Optional[str] = None,
    quality_bucket: Optional[str] = None,
) -> Dict[str, Any]:
    query: Dict[str, Any] = {}
    if status:
        query["status"] = str(status).strip().lower()

    resources = list(
        _resource_repository.collection.find(query).sort("updated_at", -1).limit(max(1, limit))
    )
    duplicate_groups = _resource_repository.find_latest_duplicate_groups()
    duplicate_map: Dict[str, Dict[str, Any]] = {}
    formatted_duplicate_groups: List[Dict[str, Any]] = []
    for group in duplicate_groups:
        duplicate_key = str(group.get("_id") or "")
        count = int(group.get("count") or 0)
        resource_ids = [str(item.get("_id")) for item in group.get("resources", []) if item.get("_id")]
        formatted_duplicate_groups.append(
            {
                "duplicate_key": duplicate_key,
                "resource_ids": resource_ids,
                "duplicate_count": count,
            }
        )
        for resource_id in resource_ids:
            duplicate_map[resource_id] = {
                "duplicate_key": duplicate_key,
                "duplicate_count": count,
            }

    items = [
        _build_resource_curation_item(resource, duplicate_map=duplicate_map)
        for resource in resources
    ]

    normalized_bucket = str(quality_bucket or "").strip().lower()
    if normalized_bucket == "low":
        items = [item for item in items if item["quality_score"] < 0.6]
    elif normalized_bucket == "medium":
        items = [item for item in items if 0.6 <= item["quality_score"] < 0.8]
    elif normalized_bucket == "high":
        items = [item for item in items if item["quality_score"] >= 0.8]

    status_pipeline = [
        {"$group": {"_id": {"$ifNull": ["$status", "unknown"]}, "count": {"$sum": 1}}},
    ]
    status_counts = {
        str(item.get("_id") or "unknown"): int(item.get("count") or 0)
        for item in _resource_repository.collection.aggregate(status_pipeline)
    }

    low_quality_count = sum(1 for item in items if item["quality_score"] < 0.6)
    return {
        "items": items,
        "status_counts": status_counts,
        "duplicate_groups": formatted_duplicate_groups[:10],
        "low_quality_count": low_quality_count,
        "total_items": len(items),
    }


def update_resource_curation_service(
    resource_id: str,
    *,
    curated_concept_ids: Optional[List[str]] = None,
    quality_label: Optional[str] = None,
    admin_notes: Optional[str] = None,
    hidden_from_recommendation: Optional[bool] = None,
) -> Dict[str, Any]:
    resource = _resource_repository.get(resource_id)
    if not resource:
        raise ValueError("Resource not found.")

    updates: Dict[str, Any] = {}
    if curated_concept_ids is not None:
        normalized = _normalize_curated_concept_ids(curated_concept_ids)
        updates["metadata.curated_concept_ids"] = normalized
        if normalized:
            first = normalized[0]
            updates["metadata.concept_id"] = int(first) if first.isdigit() else first
    if quality_label is not None:
        updates["metadata.quality_label"] = str(quality_label).strip()
    if admin_notes is not None:
        updates["metadata.admin_notes"] = str(admin_notes).strip()
    if hidden_from_recommendation is not None:
        updates["metadata.hidden_from_recommendation"] = bool(hidden_from_recommendation)

    if not updates:
        duplicate_info = {}
        return _build_resource_curation_item(resource, duplicate_map=duplicate_info)

    updated = _resource_repository.update(resource_id, updates)
    if not updated:
        raise ValueError("Resource not found.")
    return _build_resource_curation_item(updated, duplicate_map={})


def get_ingestion_health_service(*, recent_job_limit: int = 10) -> Dict[str, Any]:
    status_counts = {
        str(item.get("_id") or "unknown"): int(item.get("count") or 0)
        for item in _resource_repository.collection.aggregate(
            [{"$group": {"_id": {"$ifNull": ["$status", "unknown"]}, "count": {"$sum": 1}}}]
        )
    }
    total_chunks = _chunk_repository.count_total()
    chunk_backend_counts = _chunk_repository.count_by_embedding_backend()
    recent_jobs = [
        serialize_mongo(item)
        for item in ingestion_service.job_repository.collection.find({}, {
            "resource_id": 1,
            "resource_type": 1,
            "status": 1,
            "chunks_count": 1,
            "processing_time": 1,
            "error": 1,
            "created_at": 1,
            "updated_at": 1,
        }).sort("created_at", -1).limit(max(1, recent_job_limit))
    ]

    return {
        "resource_status_counts": status_counts,
        "chunk_totals": {
            "total": total_chunks,
            "with_embeddings": _chunk_repository.count_with_embeddings(),
            "without_embeddings": _chunk_repository.count_without_embeddings(),
            "by_backend": chunk_backend_counts,
        },
        "embedding": embedding_service.backend_status(),
        "vector_store": {"available": embedding_service.vector_store.available},
        "recent_jobs": recent_jobs,
    }
