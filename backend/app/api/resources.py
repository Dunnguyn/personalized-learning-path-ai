from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Query,
    Depends,
    HTTPException,
    status
)
from typing import Optional, List
from datetime import datetime
import logging

from backend.app.api.schemas import (
    ResourceCreate,
    ResourceResponse,
    ResourceImportRequest,
    LevelEnum,
    SourceEnum
)
from backend.app.services.resource_service import (
    add_resource_service,
    import_resources_service,
    search_resources_service,
    import_pdf_service,
    import_youtube_service
)
from backend.app.api.auth import get_current_user
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
MAX_PDF_SIZE = 10 * 1024 * 1024  # 10MB
MAX_YOUTUBE_TIMEOUT = 30  # seconds
SEARCH_DEFAULT_PAGE_SIZE = 10
SEARCH_MAX_PAGE_SIZE = 100

router = APIRouter(
    prefix="/resources",
    tags=["Learning Resources"]
)


# =========================
# RESPONSE SCHEMAS
# =========================
class ResourceAddResponse(BaseModel):
    resource_id: int
    title: str
    source: str
    created_at: datetime


class ResourceImportResponse(BaseModel):
    imported_count: int
    failed_count: int
    message: str


class SearchResult(BaseModel):
    resource_id: int
    title: str
    topic: str
    level: str
    source: str
    snippet: Optional[str] = None
    score: Optional[float] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    page: int
    size: int


# =========================
# HELPER: CONVERT ENUM TO STRING
# =========================
def enum_to_string(value) -> str:
    """Convert Enum to string value safely"""
    if hasattr(value, "value"):
        return value.value
    return str(value)


# =========================
# ADD SINGLE RESOURCE (JSON BODY)
# =========================
@router.post(
    "/",
    response_model=ResourceAddResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a learning resource"
)
def add_resource(
    resource: ResourceCreate,
    current_user=Depends(get_current_user)
):
    """
    Add a single learning resource manually.
    
    Requires: authenticated user
    
    JSON body example:
    ```json
    {
        "title": "Python OOP Basics",
        "content": "Intro to OOP",
        "source": "youtube",
        "topic": "python",
        "level": "beginner",
        "concept_id": 1,
        "url": "https://youtube.com/..."
    }
    ```
    """
    try:
        result = add_resource_service(resource)
        logger.info(f"Resource added by user {current_user['user_id']}: {result.get('resource_id')}")
        return result
    except ValueError as e:
        logger.warning(f"Validation error adding resource: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"Error adding resource: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not add resource. Please check your input and try again."
        )


# =========================
# IMPORT MULTIPLE RESOURCES (BATCH)
# =========================
@router.post(
    "/import",
    response_model=ResourceImportResponse,
    summary="Import multiple learning resources"
)
def import_learning_resources(
    payload: ResourceImportRequest,
    current_user=Depends(get_current_user)
):
    """
    Import multiple learning resources in batch.
    
    Requires: authenticated user
    
    Request body:
    ```json
    {
        "resources": [
            {
                "title": "Resource 1",
                "content": "...",
                "source": "pdf",
                "topic": "python",
                "level": "beginner",
                "concept_id": 1
            }
        ]
    }
    ```
    """
    if not payload.resources:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resources list cannot be empty")
    
    if len(payload.resources) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Too many resources (max 100 per request)"
        )
    
    try:
        result = import_resources_service(payload)
        logger.info(
            f"Batch import by user {current_user['user_id']}: "
            f"{result.get('imported_count', 0)} imported, "
            f"{result.get('failed_count', 0)} failed"
        )
        return result
    except ValueError as e:
        logger.warning(f"Validation error in batch import: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"Error in batch import: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Batch import failed. Please check your resources and try again."
        )


# =========================
# SEMANTIC SEARCH
# =========================
@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Semantic search learning resources"
)
def search_resources(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(SEARCH_DEFAULT_PAGE_SIZE, ge=1, le=SEARCH_MAX_PAGE_SIZE, description="Results per page")
):
    """
    Perform semantic search on learning resources.
    
    No authentication required (public search).
    
    Query parameters:
    - `q`: search query (1-500 chars)
    - `page`: page number (default 1)
    - `size`: results per page (1-100, default 10)
    """
    try:
        result = search_resources_service(q, page=page, size=size)
        logger.debug(f"Search executed: query='{q}', page={page}, size={size}")
        return result
    except ValueError as e:
        logger.warning(f"Search validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception(f"Search error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed. Please try again."
        )


# =========================
# IMPORT PDF (FORM-DATA)
# =========================
@router.post(
    "/import-pdf",
    response_model=ResourceAddResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import learning materials from PDF"
)
def import_pdf_resource(
    file: UploadFile = File(..., description="PDF file (max 10MB)"),
    topic: str = Form(..., min_length=1, max_length=100, description="Learning topic"),
    level: LevelEnum = Form(LevelEnum.beginner, description="Difficulty level"),
    concept_id: Optional[int] = Form(None, description="Associated concept ID"),
    current_user=Depends(get_current_user)
):
    """
    Import learning materials from a PDF file.
    
    Requires: authenticated user
    
    Form parameters:
    - `file`: PDF file (max 10MB)
    - `topic`: learning topic
    - `level`: beginner | intermediate | advanced
    - `concept_id`: optional concept ID
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name required")
    
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported"
        )
    
    # Read file content to check size
    try:
        file_content = file.file.read()
    except Exception as e:
        logger.exception(f"Error reading file: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read file")
    
    # Validate file size
    if len(file_content) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {MAX_PDF_SIZE // 1024 // 1024}MB)"
        )
    
    # Reset file pointer for service to read
    file.file.seek(0)
    
    try:
        result = import_pdf_service(
            file=file,
            topic=topic,
            level=enum_to_string(level),
            concept_id=concept_id
        )
        logger.info(
            f"PDF imported by user {current_user['user_id']}: "
            f"topic={topic}, size={len(file_content)} bytes, "
            f"resource_id={result.get('resource_id')}"
        )
        return result
    except ValueError as e:
        logger.warning(f"PDF import validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TimeoutError as e:
        logger.warning(f"PDF import timeout: {e}")
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="PDF processing took too long. Try a smaller file."
        )
    except Exception as e:
        logger.exception(f"PDF import error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not process PDF: {str(e)[:100]}"
        )


# =========================
# IMPORT YOUTUBE
# =========================
@router.post(
    "/import-youtube",
    response_model=ResourceAddResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import learning resource from YouTube"
)
def import_youtube_resource(
    youtube_url: str = Query(..., min_length=10, max_length=500, description="YouTube video URL"),
    topic: str = Query(..., min_length=1, max_length=100, description="Learning topic"),
    level: LevelEnum = Query(LevelEnum.beginner, description="Difficulty level"),
    concept_id: Optional[int] = Query(None, description="Associated concept ID"),
    current_user=Depends(get_current_user)
):
    """
    Import a learning resource from a YouTube video.
    
    Requires: authenticated user
    
    Query parameters:
    - `youtube_url`: full YouTube video URL
    - `topic`: learning topic
    - `level`: beginner | intermediate | advanced
    - `concept_id`: optional concept ID
    """
    # Validate YouTube URL format
    if not ("youtube.com" in youtube_url or "youtu.be" in youtube_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid YouTube URL"
        )
    
    try:
        result = import_youtube_service(
            youtube_url=youtube_url,
            topic=topic,
            level=enum_to_string(level),
            concept_id=concept_id
        )
        logger.info(
            f"YouTube imported by user {current_user['user_id']}: "
            f"url={youtube_url[:50]}..., topic={topic}, "
            f"resource_id={result.get('resource_id')}"
        )
        return result
    except ValueError as e:
        logger.warning(f"YouTube import validation error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except TimeoutError as e:
        logger.warning(f"YouTube import timeout: {e}")
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=f"YouTube processing took too long (timeout {MAX_YOUTUBE_TIMEOUT}s). Try another video."
        )
    except Exception as e:
        logger.exception(f"YouTube import error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not import YouTube video: {str(e)[:100]}"
        )