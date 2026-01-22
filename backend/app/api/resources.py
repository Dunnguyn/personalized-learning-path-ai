from fastapi import APIRouter
from backend.app.services.embedding_service import (
    store_resource,
    semantic_search
)
from backend.app.services.resource_importer import import_resources
from backend.app.api.schemas import Resource, ResourceImportRequest
from fastapi import UploadFile, File, Form
import shutil
import os
from backend.app.services.pdf_importer import import_pdf
from backend.app.services.youtube_importer import import_youtube

router = APIRouter()


# ===== Thêm 1 học liệu (có embedding) =====
@router.post("/", summary="Thêm học liệu (có embedding)")
def add_resource(resource: Resource):
    doc = store_resource(
        title=resource.title,
        content=resource.title,  # demo: dùng title làm content
        topic=resource.topic
    )
    return {"message": "Resource added", "resource": doc}


# ===== Import nhiều học liệu =====
@router.post("/import", summary="Import nhiều học liệu vào hệ thống")
def import_learning_resources(data: ResourceImportRequest):
    result = import_resources(
        resources=[r.dict() for r in data.resources]
    )
    return result


# ===== Tìm kiếm học liệu theo ngữ nghĩa =====
@router.get("/search", summary="Tìm kiếm học liệu theo ngữ nghĩa")
def search_resources(q: str):
    return semantic_search(q)


UPLOAD_DIR = "backend/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
@router.post("/import-pdf", summary="Import học liệu từ file PDF")
def import_pdf_resource(
    file: UploadFile = File(...),
    topic: str = Form(...),
    level: str = Form("beginner")
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = import_pdf(
        file_path=file_path,
        topic=topic,
        level=level
    )

    return result

    

@router.post("/import-youtube", summary="Import học liệu từ YouTube")
def import_youtube_resource(
    youtube_url: str,
    topic: str,
    level: str = "beginner"
):
    result = import_youtube(
        youtube_url=youtube_url,
        topic=topic,
        level=level
    )
    return result