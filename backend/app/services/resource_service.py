import os
import shutil
from fastapi import UploadFile

from backend.app.services.embedding_service import (
    store_resource,
    semantic_search
)
from backend.app.services.resource_importer import import_resources
from backend.app.services.pdf_importer import import_pdf
from backend.app.services.youtube_importer import import_youtube
from backend.app.api.schemas import (
    ResourceCreate,
    ResourceImportRequest
)

# =========================
# CONFIG
# =========================
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "backend/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =========================
# ADD SINGLE RESOURCE
# =========================
def add_resource_service(resource: ResourceCreate):
    """
    Thêm 1 học liệu đơn lẻ vào hệ thống (manual input).
    Có tạo embedding để phục vụ RAG.
    """

    content = resource.content.strip() if resource.content else resource.title

    doc = store_resource(
        title=resource.title,
        content=content,
        topic=resource.topic,
        level=resource.level,
        source=resource.source or "manual"
    )

    return {
        "message": "Resource added successfully",
        "resource": doc
    }


# =========================
# IMPORT MULTIPLE RESOURCES
# =========================
def import_resources_service(data: ResourceImportRequest):
    """
    Import nhiều học liệu cùng lúc (batch import).
    """
    return import_resources(
        resources=[r.dict() for r in data.resources]
    )


# =========================
# SEMANTIC SEARCH
# =========================
def search_resources_service(query: str):
    """
    Tìm kiếm học liệu theo ngữ nghĩa (cosine similarity).
    """
    return semantic_search(query)


# =========================
# IMPORT PDF
# =========================
def import_pdf_service(
    file: UploadFile,
    topic: str,
    level: str
):
    """
    Import học liệu từ file PDF:
    - Lưu file
    - Chunking
    - Embedding
    """

    filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return import_pdf(
        file_path=file_path,
        topic=topic,
        level=level
    )


# =========================
# IMPORT YOUTUBE
# =========================
def import_youtube_service(
    youtube_url: str,
    topic: str,
    concept_id: int,
    level: str
):
    return import_youtube(
        youtube_url=youtube_url,
        topic=topic,
        concept_id=concept_id,
        level=level
    )
