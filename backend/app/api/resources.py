from fastapi import APIRouter, UploadFile, File, Form
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


# =========================
# ADD SINGLE RESOURCE
# =========================
@router.post("/", summary="Add a learning resource")
def add_resource(resource: ResourceCreate):
    return add_resource_service(resource)


# =========================
# IMPORT MULTIPLE RESOURCES
# =========================
@router.post("/import", summary="Import multiple learning resources")
def import_learning_resources(data: ResourceImportRequest):
    return import_resources_service(data)


# =========================
# SEMANTIC SEARCH
# =========================
@router.get("/search", summary="Semantic search learning resources")
def search_resources(q: str):
    return search_resources_service(q)


# =========================
# IMPORT PDF
# =========================
@router.post("/import-pdf", summary="Import learning materials from PDF")
def import_pdf_resource(
    file: UploadFile = File(...),
    topic: str = Form(...),
    level: str = Form("beginner")
):
    return import_pdf_service(
        file=file,
        topic=topic,
        level=level
    )


# =========================
# IMPORT YOUTUBE
# =========================
@router.post("/import-youtube", summary="Import learning materials from YouTube")
def import_youtube_resource(
    youtube_url: str,
    topic: str,
    level: str = "beginner"
):
    return import_youtube_service(
        youtube_url=youtube_url,
        topic=topic,
        level=level
    )
