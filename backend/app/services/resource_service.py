"""Resource-facing service layer built on repositories and ingestion pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import BackgroundTasks, UploadFile

from backend.app.api.schemas import ResourceCreate, ResourceImportRequest
from backend.app.repositories import ResourceRepository
from backend.app.services.embedding_service import semantic_search
from backend.app.services.ingestion_service import ingestion_service

logger = logging.getLogger(__name__)

_resource_repository = ResourceRepository()


def serialize_mongo(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert MongoDB objects into JSON-friendly primitives."""
    serialized = dict(document)
    if isinstance(serialized.get("_id"), ObjectId):
        serialized["_id"] = str(serialized["_id"])
    for key, value in list(serialized.items()):
        if isinstance(value, datetime):
            serialized[key] = value.isoformat()
    return serialized


def get_resources_service(
    page: int = 1,
    size: int = 10,
    topic: Optional[str] = None,
    level: Optional[str] = None,
    source: Optional[str] = None,
    resource_type: Optional[str] = None,
    concept_id: Optional[int] = None,
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
    return {
        "resources": [serialize_mongo(item) for item in result["items"]],
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
        level=resource.level.value if hasattr(resource.level, "value") else str(resource.level),
        source=resource.source.value if hasattr(resource.source, "value") else str(resource.source),
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
                level=resource.level.value if hasattr(resource.level, "value") else str(resource.level),
                source=resource.source.value if hasattr(resource.source, "value") else str(resource.source),
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
    return {
        "results": paged,
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
        "by_source": {item["_id"]: item["count"] for item in facet.get("by_source", [])},
        "by_type": {item["_id"]: item["count"] for item in facet.get("by_type", [])},
        "recent_resources": [serialize_mongo(item) for item in facet.get("recent", [])],
    }
