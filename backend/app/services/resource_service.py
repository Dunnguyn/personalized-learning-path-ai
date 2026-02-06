import os
import shutil
from datetime import datetime
from typing import Optional

from fastapi import UploadFile
from bson import ObjectId

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
# HELPER
# =========================
def serialize_mongo(doc: dict) -> dict:
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


# =========================
# ADD SINGLE RESOURCE
# =========================
def add_resource_service(resource: ResourceCreate):
    """
    Thêm 1 học liệu đơn lẻ:
    - Lưu embedding (RAG)
    - Gắn metadata (concept_id, url)
    """

    content = resource.content.strip() if resource.content else resource.title

    # 1️⃣ CHỈ TRUYỀN CÁC FIELD MÀ store_resource HỖ TRỢ
    doc = store_resource(
        title=resource.title,
        content=content,
        topic=resource.topic,
        level=resource.level,
        source=resource.source or "manual"
    )

    # 2️⃣ GẮN METADATA Ở TẦNG SERVICE
    doc["concept_id"] = resource.concept_id
    doc["url"] = resource.url
    doc["created_at"] = datetime.utcnow()

    doc = serialize_mongo(doc)

    return {
        "message": "Resource added successfully",
        "resource": doc
    }


# =========================
# IMPORT MULTIPLE RESOURCES
# =========================
def import_resources_service(data: ResourceImportRequest):
    docs = import_resources(
        resources=[r.model_dump() for r in data.resources]
    )
    return [serialize_mongo(d) for d in docs]


# =========================
# SEMANTIC SEARCH
# =========================
def search_resources_service(query: str):
    results = semantic_search(query)
    return [serialize_mongo(r) for r in results]


# =========================
# IMPORT PDF
# =========================
def import_pdf_service(
    file: UploadFile,
    topic: str,
    level: str,
    concept_id: Optional[int] = None
):
    filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    docs = import_pdf(
        file_path=file_path,
        topic=topic,
        level=level,
        concept_id=concept_id
    )

    return [serialize_mongo(d) for d in docs]


# =========================
# IMPORT YOUTUBE
# =========================
def import_youtube_service(
    youtube_url: str,
    topic: str,
    level: str,
    concept_id: Optional[int] = None
):
    docs = import_youtube(
        youtube_url=youtube_url,
        topic=topic,
        level=level,
        concept_id=concept_id
    )

    return [serialize_mongo(d) for d in docs]
