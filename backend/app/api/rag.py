"""
RAG API: Minimal PDF upload + chat endpoints.

Endpoints:
- POST /rag/upload-pdf: upload PDF and run chunk+embed pipeline
- POST /rag/chat: ask questions against embedded content
"""

from typing import Optional
from pathlib import Path
import logging

from fastapi import APIRouter, File, UploadFile, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.services.resource_service import import_pdf_service
from backend.app.services.ai_tutor.rag import RAGPipeline

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/rag", tags=["RAG"])
rag = RAGPipeline()


class RagChatRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)
    goal: Optional[str] = Field(default="general", max_length=200)
    level: Optional[str] = Field(default="beginner", max_length=50)


@router.post(
    "/upload-pdf",
    status_code=status.HTTP_201_CREATED,
    summary="Upload PDF and build embeddings"
)
def upload_pdf(file: UploadFile = File(..., description="PDF file")):
    """
    Upload PDF and run the PDF processing pipeline in background.
    The process is hidden from the user; only success/failure is returned.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name required")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported"
        )

    try:
        # Use filename stem as a lightweight topic fallback
        topic = Path(file.filename).stem or "general"
        logger.info(f"RAG upload_pdf: file={file.filename}, topic={topic}")
        
        result = import_pdf_service(
            file=file,
            topic=topic,
            level="beginner"
        )
        
        logger.info(f"RAG upload_pdf successful: resource_id={result.get('resource_id')}")

        return {
            "success": True,
            "resource_id": result.get("resource_id"),
            "title": result.get("title"),
        }
    except ValueError as e:
        logger.warning("PDF upload validation error: %s", e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("PDF upload error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process PDF"
        )


@router.post(
    "/chat",
    status_code=status.HTTP_200_OK,
    summary="Chat with embedded PDF content"
)
def chat(request: RagChatRequest):
    if not request.question.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question cannot be empty")

    try:
        result = rag.run(
            question=request.question.strip(),
            goal=(request.goal or "general").strip(),
            level=(request.level or "beginner").strip(),
            completed=[]
        )

        return {
            "success": result.get("success", False),
            "answer": result.get("answer"),
            "sources": result.get("sources", []),
            "latency_ms": result.get("latency_ms")
        }
    except Exception as e:
        logger.exception("RAG chat error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RAG chat failed"
        )
