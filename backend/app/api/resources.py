from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Query,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import FileResponse
from typing import Optional, List, Dict
from datetime import datetime
import logging
from pathlib import Path

from backend.app.api.schemas import (
    ResourceCreate,
    ResourceResponse,
    ResourceImportRequest,
    YouTubeImportRequest,
    LevelEnum,
    SourceEnum
)
from backend.app.services.resource_service import (
    add_resource_service,
    import_resources_service,
    search_resources_service,
    import_pdf_service,
    import_youtube_service,
    get_resources_service
)
from backend.app.api.auth import get_current_user
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================
MAX_PDF_SIZE = 30 * 1024 * 1024  # 30MB
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
    resource_id: str  # MongoDB ObjectId as string
    title: str
    source: str
    created_at: datetime


class ResourceImportResponse(BaseModel):
    imported_count: int
    failed_count: int
    message: str


class SearchResult(BaseModel):
    resource_id: str  # MongoDB ObjectId as string
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


class ResourceListItem(BaseModel):
    """Single resource in list view"""
    resource_id: Optional[int] = None
    title: str
    topic: str
    level: str
    source: str
    created_at: Optional[datetime] = None
    url: Optional[str] = None


class ResourceListResponse(BaseModel):
    """Response for GET /api/resources/"""
    resources: List[Dict]
    total: int
    page: int
    size: int
    pages: int


# =========================
# HELPER: CONVERT ENUM TO STRING
# =========================
def enum_to_string(value) -> str:
    """Convert Enum to string value safely"""
    if hasattr(value, "value"):
        return value.value
    return str(value)


# =========================
# GET ALL RESOURCES (LIST WITH PAGINATION)
# =========================
@router.get(
    "/",
    response_model=ResourceListResponse,
    summary="List all learning resources"
)
def get_resources(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(12, ge=1, le=100, description="Items per page"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    level: Optional[str] = Query(None, description="Filter by level"),
    source: Optional[str] = Query(None, description="Filter by source")
):
    """
    Get paginated list of all learning resources.
    
    No authentication required (public listing).
    
    Query parameters:
    - `page`: page number (default 1)
    - `size`: items per page (1-100, default 12)
    - `topic`: optional topic filter
    - `level`: optional level filter (beginner/intermediate/advanced)
    - `source`: optional source filter (pdf/youtube/web)
    
    Returns:
    - List of resources with metadata
    - Total count and pagination info
    """
    try:
        result = get_resources_service(
            page=page,
            size=size,
            topic=topic,
            level=level,
            source=source
        )
        return result
    
    except Exception as e:
        logger.exception(f"Error in get_resources endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve resources: {str(e)}"
        )


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
    file: UploadFile = File(..., description="PDF file (max 30MB)"),
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
            f"PDF imported by user {current_user.get('_id', 'unknown')}: "
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
    request: YouTubeImportRequest,
    current_user=Depends(get_current_user)
):
    """
    Import a learning resource from a YouTube video.
    
    Requires: authenticated user
    
    Request body:
    - `url`: full YouTube video URL
    - `title`: resource title
    - `topic`: learning topic
    - `level`: beginner | intermediate | advanced (default: beginner)
    - `concept_id`: optional concept ID
    
    Example:
    ```json
    {
        "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
        "title": "Learn Python - Full Course for Beginners",
        "topic": "python",
        "level": "beginner",
        "concept_id": 1
    }
    ```
    """
    # Validate YouTube URL format
    if not ("youtube.com" in request.url or "youtu.be" in request.url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid YouTube URL. Must be a youtube.com or youtu.be link"
        )
    
    try:
        result = import_youtube_service(
            youtube_url=request.url,
            title=request.title,
            topic=request.topic,
            level=enum_to_string(request.level),
            concept_id=request.concept_id
        )
        
        logger.info(
            f"YouTube imported by user {current_user.get('_id', 'unknown')}: "
            f"url={request.url[:50]}..., topic={request.topic}, "
            f"resource_id={result.get('resource_id')}"
        )
        
        return result
        
    except ValueError as e:
        logger.warning(f"YouTube import validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
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


# =========================
# SERVE PDF FILE
# =========================
@router.get(
    "/pdf/{resource_id}",
    summary="Download PDF file"
)
def download_pdf(resource_id: str):
    """
    Serve a PDF file for viewing/downloading.
    
    Parameters:
    - resource_id: MongoDB resource ID
    
    Returns:
    - PDF file as attachment
    """
    try:
        from backend.app.database.mongo import db
        from bson import ObjectId
        
        logger.info(f"PDF request for resource_id: {resource_id}")
        
        # Get resource document to find PDF file path
        try:
            doc_id = ObjectId(resource_id)
            logger.info(f"Parsed ObjectId: {doc_id}")
        except Exception as e:
            logger.error(f"Invalid ObjectId format: {resource_id}, error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid resource ID"
            )
        
        resource = db.resources.find_one({"_id": doc_id})
        if not resource:
            logger.error(f"Resource not found in database: {resource_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Resource not found: {resource_id}"
            )
        
        logger.info(f"Found resource: {resource.get('title', 'No title')}")
        
        logger.info(f"Found resource: {resource.get('title', 'No title')}")
        
        pdf_file_path = resource.get("pdf_file_path")
        logger.info(f"PDF file path from resource: {pdf_file_path}")
        
        if not pdf_file_path:
            # Fallback: try to resolve PDF path from another chunk
            base_title = (resource.get("title") or "").split(" | Chunk ", 1)[0].strip()
            logger.info(f"Attempting fallback with base_title: {base_title}")
            
            if base_title:
                alt = db.resources.find_one({
                    "source": "pdf",
                    "title": {"$regex": f"^{base_title}\\s*\\|\\s*Chunk", "$options": "i"},
                    "pdf_file_path": {"$exists": True, "$ne": None}
                })
                if alt:
                    pdf_file_path = alt.get("pdf_file_path")
                    logger.info(f"Found fallback PDF path: {pdf_file_path}")
                else:
                    logger.warning(f"No fallback found for base_title: {base_title}")
                    
            if not pdf_file_path:
                logger.error(f"No PDF file path found for resource {resource_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="PDF file path not found for this resource"
                )
        
        # Verify file exists
        pdf_path = Path(pdf_file_path)
        if not pdf_path.exists():
            logger.error(f"PDF file not found at: {pdf_path}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="PDF file has been deleted or moved"
            )
        
        # Security check: ensure path is within uploads directory
        uploads_dir = Path("backend/uploads").resolve()
        try:
            pdf_path.resolve().relative_to(uploads_dir)
        except ValueError:
            logger.warning(f"Path traversal attempt: {pdf_path}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        logger.info(f"Serving PDF: {pdf_path}, size: {pdf_path.stat().st_size} bytes")
        return FileResponse(
            path=pdf_path,
            media_type="application/pdf",
            filename=pdf_path.name,
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                "Content-Disposition": f"inline; filename=\"{pdf_path.name}\"",  # Display inline in browser
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error serving PDF: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error serving PDF: {str(e)[:100]}"
        )