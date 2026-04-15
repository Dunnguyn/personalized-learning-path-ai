"""API routes for resource ingestion, listing, search, and job status."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from backend.app.api.auth import get_current_user, require_admin_user
from backend.app.api.schemas import (
    BatchResourceIngestionResponse,
    IngestionJobStatusResponse,
    LevelEnum,
    ResourceCreate,
    ResourceDetailResponse,
    ResourceDeleteResponse,
    ResourceImportRequest,
    ResourceIngestionResponse,
    ResourceTypeEnum,
    YouTubeImportRequest,
)
from backend.app.services.resource_service import (
    add_resource_service,
    delete_resource_service,
    get_ingestion_job_status_service,
    get_ingestion_health_service,
    get_pdf_file_path,
    get_admin_resource_curation_service,
    get_resource_by_id_service,
    get_resources_service,
    import_pdf_service,
    import_resources_service,
    import_youtube_service,
    search_resources_service,
    update_resource_curation_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resources", tags=["Learning Resources"])


@router.get("/admin/curation", summary="Admin resource curation snapshot")
def get_admin_resource_curation(
    limit: int = Query(20, ge=1, le=100),
    resource_status: Optional[str] = Query(None, alias="status"),
    quality_bucket: Optional[str] = Query(None, pattern="^(low|medium|high)?$"),
    current_user=Depends(require_admin_user),
):
    """Return quality/duplicate/concept mapping data for admin curation."""
    del current_user
    try:
        return get_admin_resource_curation_service(
            limit=limit,
            status=resource_status,
            quality_bucket=quality_bucket,
        )
    except Exception as exc:
        logger.exception("Failed to load admin curation snapshot: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load resource curation snapshot.",
        )


@router.patch("/admin/{resource_id}/curation", summary="Update resource curation metadata")
def update_resource_curation(
    resource_id: str,
    payload: dict = Body(...),
    current_user=Depends(require_admin_user),
):
    """Allow admin to update concept mapping, quality label, and visibility notes."""
    del current_user
    try:
        return update_resource_curation_service(
            resource_id,
            curated_concept_ids=payload.get("curated_concept_ids"),
            quality_label=payload.get("quality_label"),
            admin_notes=payload.get("admin_notes"),
            hidden_from_recommendation=payload.get("hidden_from_recommendation"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to update resource curation for %s: %s", resource_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update resource curation metadata.",
        )


@router.get("/admin/ingestion-health", summary="Admin ingestion health snapshot")
def get_admin_ingestion_health(
    recent_job_limit: int = Query(10, ge=1, le=50),
    current_user=Depends(require_admin_user),
):
    """Return ingestion/resource health grouped for admin debugging."""
    del current_user
    try:
        return get_ingestion_health_service(recent_job_limit=recent_job_limit)
    except Exception as exc:
        logger.exception("Failed to load ingestion health: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load ingestion health.",
        )


@router.get("/", summary="List resources")
def get_resources(
    page: int = Query(1, ge=1),
    size: int = Query(12, ge=1, le=100),
    topic: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    concept_id: Optional[int] = Query(None, ge=1),
    resource_type: Optional[ResourceTypeEnum] = Query(None, alias="type"),
    current_user=Depends(get_current_user),
):
    """Return top-level resources only; chunk documents live in `resource_chunks`."""
    try:
        return get_resources_service(
            page=page,
            size=size,
            topic=topic,
            level=level,
            source=source,
            concept_id=concept_id,
            resource_type=resource_type.value if resource_type else None,
            user_id=str(current_user.get("_id")),
        )
    except Exception as exc:
        logger.exception("Failed to list resources: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.post(
    "/",
    response_model=ResourceIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit manual resource ingestion",
)
def add_resource(
    resource: ResourceCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_admin_user),
):
    """Submit text/manual resource into background ingestion pipeline."""
    user_id = current_user.get("user_id") or current_user.get("_id")
    try:
        return add_resource_service(
            resource, background_tasks=background_tasks, user_id=str(user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to submit manual resource: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit resource.",
        )


@router.post(
    "/import",
    response_model=BatchResourceIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit batch resource ingestion",
)
def import_learning_resources(
    payload: ResourceImportRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_admin_user),
):
    """Submit multiple manual resources; each item becomes its own ingestion job."""
    user_id = current_user.get("user_id") or current_user.get("_id")
    try:
        return import_resources_service(
            payload, background_tasks=background_tasks, user_id=str(user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to submit batch ingestion: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit batch ingestion.",
        )


@router.get("/search", summary="Semantic search across resource chunks")
def search_resources(
    q: str = Query(..., min_length=1, max_length=500),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    topic: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    current_user=Depends(get_current_user),
):
    """Search via chunk embeddings and return parent resource hits."""
    try:
        return search_resources_service(
            q=q,
            page=page,
            size=size,
            filters={"topic": topic, "level": level},
            user_id=str(current_user.get("_id")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Search failed."
        )


@router.post(
    "/import-pdf",
    response_model=ResourceIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit PDF ingestion",
)
def import_pdf_resource(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    topic: str = Form(..., min_length=1, max_length=100),
    level: LevelEnum = Form(LevelEnum.beginner),
    concept_id: Optional[int] = Form(None),
    current_user=Depends(require_admin_user),
):
    """Upload a PDF and process it asynchronously."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported.",
        )
    user_id = current_user.get("user_id") or current_user.get("_id")
    try:
        return import_pdf_service(
            file,
            background_tasks=background_tasks,
            topic=topic,
            level=level.value,
            concept_id=concept_id,
            user_id=str(user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("PDF submission failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit PDF.",
        )


@router.post(
    "/import-youtube",
    response_model=ResourceIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit YouTube ingestion",
)
def import_youtube_resource(
    request: YouTubeImportRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_admin_user),
):
    """Queue a YouTube transcript or summary ingestion job."""
    user_id = current_user.get("user_id") or current_user.get("_id")
    try:
        return import_youtube_service(
            request.url,
            background_tasks=background_tasks,
            title=request.title,
            topic=request.topic,
            level=request.level.value,
            concept_id=request.concept_id,
            user_id=str(user_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("YouTube submission failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit YouTube ingestion.",
        )


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobStatusResponse,
    summary="Get ingestion job status",
)
def get_ingestion_job_status(
    job_id: str, current_user=Depends(require_admin_user)
):
    """Check background ingestion progress."""
    del current_user
    try:
        return get_ingestion_job_status_service(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to fetch job status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load job status.",
        )


@router.get("/pdf/{resource_id}", summary="Download stored PDF")
def download_pdf(resource_id: str):
    """Serve the uploaded PDF attached to a resource."""
    try:
        pdf_path = get_pdf_file_path(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Could not resolve PDF path for %s: %s", resource_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve PDF path.",
        )

    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PDF file no longer exists."
        )

    uploads_dir = Path("backend/uploads").resolve()
    try:
        pdf_path.resolve().relative_to(uploads_dir)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
        headers={"Content-Disposition": f'inline; filename="{pdf_path.name}"'},
    )


@router.get(
    "/{resource_id}",
    response_model=ResourceDetailResponse,
    summary="Get resource detail",
)
def get_resource_detail(resource_id: str):
    """Return a single top-level resource by id."""
    try:
        return get_resource_by_id_service(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to load resource %s: %s", resource_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load resource.",
        )


@router.delete(
    "/{resource_id}",
    response_model=ResourceDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a resource and its derived chunks",
)
def delete_resource(resource_id: str, current_user=Depends(require_admin_user)):
    """Delete a top-level resource plus generated chunk documents."""
    del current_user
    try:
        return delete_resource_service(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to delete resource %s: %s", resource_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete resource.",
        )
