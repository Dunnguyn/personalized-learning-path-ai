from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Query
)
from typing import Optional

from backend.app.api.schemas import (
    ResourceCreate,
    ResourceImportRequest
)
from backend.app.services.resource_service import (
    add_resource_service,
    import_resources_service,
    search_resources_service,
    import_pdf_service,
    import_youtube_service
)

router = APIRouter(
    prefix="/resources",
    tags=["Learning Resources"]
)

# =====================================================
# ADD SINGLE RESOURCE (JSON BODY)
# =====================================================
@router.post(
    "/",
    summary="Add a learning resource"
)
def add_resource(resource: ResourceCreate):
    """
    Thêm 1 learning resource thủ công

    JSON body example:
    {
        "title": "Python OOP Basics",
        "content": "Intro to OOP",
        "source": "youtube",
        "topic": "python",
        "level": "beginner",
        "concept_id": 1,
        "url": "https://youtube.com/..."
    }
    """
    return add_resource_service(resource)


# =====================================================
# IMPORT MULTIPLE RESOURCES (BATCH)
# =====================================================
@router.post(
    "/import",
    summary="Import multiple learning resources"
)
def import_learning_resources(payload: ResourceImportRequest):
    return import_resources_service(payload)


# =====================================================
# SEMANTIC SEARCH
# =====================================================
@router.get(
    "/search",
    summary="Semantic search learning resources"
)
def search_resources(
    q: str = Query(..., description="Search query")
):
    return search_resources_service(q)


# =====================================================
# IMPORT PDF (FORM-DATA)
# =====================================================
@router.post(
    "/import-pdf",
    summary="Import learning materials from PDF"
)
def import_pdf_resource(
    file: UploadFile = File(...),
    topic: str = Form(...),
    level: str = Form("beginner"),
    concept_id: Optional[int] = Form(None)
):
    return import_pdf_service(
        file=file,
        topic=topic,
        level=level,
        concept_id=concept_id
    )


# =====================================================
# IMPORT YOUTUBE
# =====================================================
@router.post(
    "/import-youtube",
    summary="Import Youtube Resource"
)
def import_youtube_resource(
    youtube_url: str = Query(...),
    topic: str = Query(...),
    level: str = Query("beginner"),
    concept_id: Optional[int] = Query(None)
):
    return import_youtube_service(
        youtube_url=youtube_url,
        topic=topic,
        level=level,
        concept_id=concept_id
    )
