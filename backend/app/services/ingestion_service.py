"""Business logic for asynchronous resource ingestion."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from bson import ObjectId
from fastapi import BackgroundTasks, UploadFile

from backend.app.ai_module import (
    EmbeddingService,
    YouTubeSummaryService,
    compute_content_hash,
    compute_file_hash,
    cosine_similarity,
)
from backend.app.repositories import (
    IngestionJobRepository,
    ResourceChunkRepository,
    ResourceRepository,
)
from backend.app.services.chunk_service import build_chunk_documents, clean_text, split_into_chunks

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
SUMMARY_LENGTH = int(os.getenv("RESOURCE_SUMMARY_LENGTH", "800"))
MAX_STORED_CHUNKS = int(os.getenv("RESOURCE_MAX_STORED_CHUNKS", "250"))

try:
    import fitz

    PYMUPDF_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    fitz = None
    PYMUPDF_AVAILABLE = False

try:
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    PdfReader = None
    PYPDF_AVAILABLE = False

try:
    from pytube import YouTube

    PYTUBE_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    YouTube = None
    PYTUBE_AVAILABLE = False

try:
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )

    TRANSCRIPT_API_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    NoTranscriptFound = Exception
    TranscriptsDisabled = Exception
    YouTubeTranscriptApi = None
    TRANSCRIPT_API_AVAILABLE = False


class IngestionError(RuntimeError):
    """Raised when ingestion processing fails."""


class DuplicateResourceError(ValueError):
    """Raised when duplicate content is detected."""


class IngestionService:
    """Submit and process ingestion jobs for PDF, YouTube, and text content."""

    def __init__(self) -> None:
        self.resource_repository = ResourceRepository()
        self.chunk_repository = ResourceChunkRepository()
        self.job_repository = IngestionJobRepository()
        self.embedding_service = EmbeddingService()
        self.summary_service = YouTubeSummaryService()

        self.resource_repository.ensure_indexes()
        self.chunk_repository.ensure_indexes()
        self.job_repository.ensure_indexes()

    def submit_text_job(
        self,
        *,
        background_tasks: BackgroundTasks,
        title: str,
        content: str,
        topic: str,
        level: str,
        source: str = "manual",
        concept_id: Optional[int] = None,
        url: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create resource and schedule text ingestion."""
        normalized_content = clean_text(content)
        content_hash = compute_content_hash(normalized_content)
        duplicate = self.resource_repository.find_duplicate(content_hash=content_hash)
        if duplicate:
            return self._build_duplicate_response(duplicate)

        resource = self.resource_repository.create(
            {
                "title": title.strip(),
                "type": "text",
                "topic": topic.strip().lower(),
                "source": source,
                "content_summary": self._summarize_content(normalized_content),
                "metadata": {
                    "level": level,
                    "concept_id": concept_id,
                    "url": url,
                    "content_hash": content_hash,
                    "submitted_by": user_id,
                },
            }
        )
        job = self.job_repository.create(
            {
                "resource_id": resource["_id"],
                "resource_type": "text",
                "status": "pending",
            }
        )
        background_tasks.add_task(
            self.process_text_job,
            str(job["_id"]),
            str(resource["_id"]),
            normalized_content,
        )
        return self._build_submission_response(resource=resource, job=job)

    def submit_pdf_job(
        self,
        *,
        background_tasks: BackgroundTasks,
        file: UploadFile,
        topic: str,
        level: str,
        concept_id: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist uploaded PDF, register job, and schedule background processing."""
        safe_name = self._sanitize_filename(file.filename or "document.pdf")
        target_path = UPLOAD_DIR / safe_name
        with target_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)

        file_size = target_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            target_path.unlink(missing_ok=True)
            raise ValueError(f"PDF exceeds {MAX_FILE_SIZE_MB}MB limit.")

        file_hash = compute_file_hash(target_path)
        duplicate = self.resource_repository.find_duplicate(file_hash=file_hash)
        if duplicate:
            target_path.unlink(missing_ok=True)
            return self._build_duplicate_response(duplicate)

        resource = self.resource_repository.create(
            {
                "title": self._build_pdf_title(file.filename or safe_name),
                "type": "pdf",
                "topic": topic.strip().lower(),
                "source": "pdf",
                "content_summary": "",
                "metadata": {
                    "level": level,
                    "concept_id": concept_id,
                    "file_hash": file_hash,
                    "pdf_file_path": str(target_path),
                    "file_name": safe_name,
                    "file_size_bytes": file_size,
                    "submitted_by": user_id,
                },
            }
        )
        job = self.job_repository.create(
            {
                "resource_id": resource["_id"],
                "resource_type": "pdf",
                "status": "pending",
            }
        )
        background_tasks.add_task(
            self.process_pdf_job,
            str(job["_id"]),
            str(resource["_id"]),
            str(target_path),
        )
        return self._build_submission_response(resource=resource, job=job)

    def submit_youtube_job(
        self,
        *,
        background_tasks: BackgroundTasks,
        youtube_url: str,
        topic: str,
        level: str,
        title: Optional[str] = None,
        concept_id: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register YouTube ingestion job with duplicate detection on `video_id`."""
        video_id = self.extract_video_id(youtube_url)
        duplicate = self.resource_repository.find_duplicate(video_id=video_id)
        if duplicate:
            return self._build_duplicate_response(duplicate)

        resource = self.resource_repository.create(
            {
                "title": title.strip() if title else f"YouTube Video ({video_id})",
                "type": "youtube",
                "topic": topic.strip().lower(),
                "source": "youtube",
                "content_summary": "",
                "metadata": {
                    "level": level,
                    "concept_id": concept_id,
                    "video_id": video_id,
                    "youtube_url": youtube_url,
                    "submitted_by": user_id,
                },
            }
        )
        job = self.job_repository.create(
            {
                "resource_id": resource["_id"],
                "resource_type": "youtube",
                "status": "pending",
            }
        )
        background_tasks.add_task(
            self.process_youtube_job,
            str(job["_id"]),
            str(resource["_id"]),
            youtube_url,
            topic,
            level,
        )
        return self._build_submission_response(resource=resource, job=job)

    def process_text_job(self, job_id: str, resource_id: str, content: str) -> None:
        """Background processor for manual text ingestion."""
        self._run_job(
            job_id=job_id,
            resource_id=resource_id,
            resource_type="text",
            processing_fn=lambda: self._process_text_content(resource_id, content),
        )

    def process_pdf_job(self, job_id: str, resource_id: str, file_path: str) -> None:
        """Background processor for PDF ingestion."""
        self._run_job(
            job_id=job_id,
            resource_id=resource_id,
            resource_type="pdf",
            processing_fn=lambda: self._process_pdf_content(resource_id, file_path),
        )

    def process_youtube_job(
        self,
        job_id: str,
        resource_id: str,
        youtube_url: str,
        topic: str,
        level: str,
    ) -> None:
        """Background processor for YouTube ingestion."""
        self._run_job(
            job_id=job_id,
            resource_id=resource_id,
            resource_type="youtube",
            processing_fn=lambda: self._process_youtube_content(resource_id, youtube_url, topic, level),
        )

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Return serialized job status."""
        job = self.job_repository.get(job_id)
        if not job:
            raise ValueError("Ingestion job not found.")
        resource = self.resource_repository.get(job["resource_id"])
        return self._serialize_job(job=job, resource=resource)

    def _run_job(
        self,
        *,
        job_id: str,
        resource_id: str,
        resource_type: str,
        processing_fn,
    ) -> None:
        start = time.perf_counter()
        self.job_repository.update(
            job_id,
            {"status": "processing", "started_at": time.time()},
        )
        self.resource_repository.update(resource_id, {"status": "processing"})
        try:
            result = processing_fn()
            processing_time = round(time.perf_counter() - start, 3)
            self.job_repository.update(
                job_id,
                {
                    "status": "done",
                    "chunks_count": result["chunks_count"],
                    "processing_time": processing_time,
                    "completed_at": time.time(),
                },
            )
            self.resource_repository.update(
                resource_id,
                {
                    "status": "done",
                    "chunks_count": result["chunks_count"],
                    "processing_time": processing_time,
                    "content_summary": result["content_summary"],
                    "metadata": result["metadata"],
                },
            )
            logger.info(
                "Completed %s ingestion for resource %s with %s chunks in %.3fs",
                resource_type,
                resource_id,
                result["chunks_count"],
                processing_time,
            )
        except Exception as exc:
            processing_time = round(time.perf_counter() - start, 3)
            logger.exception("Ingestion job failed for resource %s: %s", resource_id, exc)
            self.job_repository.update(
                job_id,
                {
                    "status": "failed",
                    "processing_time": processing_time,
                    "error": str(exc),
                    "completed_at": time.time(),
                },
            )
            self.resource_repository.update(
                resource_id,
                {
                    "status": "failed",
                    "processing_time": processing_time,
                    "metadata.error": str(exc),
                },
            )

    def _process_text_content(self, resource_id: str, content: str) -> Dict[str, Any]:
        resource = self._require_resource(resource_id)
        chunks = split_into_chunks(content)
        return self._store_chunks(
            resource=resource,
            chunks=chunks,
            summary=self._summarize_content(content),
            metadata_updates=resource.get("metadata", {}),
        )

    def _process_pdf_content(self, resource_id: str, file_path: str) -> Dict[str, Any]:
        resource = self._require_resource(resource_id)
        pages, page_count = self.extract_pdf_pages(file_path)
        if not pages:
            raise IngestionError("No readable text extracted from PDF.")
        chunk_pages = pages
        cleaned_text = "\n\n".join(page_text for _, page_text in pages)
        page_chunks = [page_text for _, page_text in chunk_pages]
        page_chunk_indexes = [page_number - 1 for page_number, _ in chunk_pages]
        page_chunk_metadata = [{"page_number": page_number} for page_number, _ in chunk_pages]
        metadata = {
            **resource.get("metadata", {}),
            "pages": page_count,
            "stored_pages": len(chunk_pages),
            "chunking_strategy": "page",
            "content_hash": compute_content_hash(cleaned_text),
        }
        return self._store_chunks(
            resource=resource,
            chunks=page_chunks,
            summary=self._summarize_content(cleaned_text),
            metadata_updates=metadata,
            chunk_indexes=page_chunk_indexes,
            per_chunk_metadata_overrides=page_chunk_metadata,
        )

    def _process_youtube_content(
        self,
        resource_id: str,
        youtube_url: str,
        topic: str,
        level: str,
    ) -> Dict[str, Any]:
        resource = self._require_resource(resource_id)
        video_id = resource.get("metadata", {}).get("video_id") or self.extract_video_id(youtube_url)
        metadata = self.fetch_youtube_metadata(video_id=video_id, youtube_url=youtube_url)
        transcript_text, transcript_language = self.fetch_youtube_transcript(video_id)

        if transcript_text:
            cleaned_text = clean_text(transcript_text)
            content_kind = "transcript"
            ai_summary = None
        else:
            ai_summary = self.summary_service.generate_summary(
                video_title=metadata.get("title") or resource.get("title"),
                topic=topic,
                level=level,
                additional_context=metadata.get("channel"),
            )
            cleaned_text = clean_text(ai_summary["content"])
            content_kind = "ai_summary"

        raw_chunks = split_into_chunks(cleaned_text)
        ranked_chunks = self._rank_chunks_by_topic(raw_chunks, topic=topic, limit=MAX_STORED_CHUNKS)
        merged_metadata = {
            **resource.get("metadata", {}),
            **metadata,
            "transcript": {
                "available": transcript_text is not None,
                "language": transcript_language,
            },
            "ai_summary": ai_summary,
            "content_hash": compute_content_hash(cleaned_text),
        }
        return self._store_chunks(
            resource=resource,
            chunks=ranked_chunks,
            summary=self._summarize_content(cleaned_text),
            metadata_updates=merged_metadata,
            chunk_metadata_overrides={
                "content_kind": content_kind,
                "is_ai_generated": content_kind == "ai_summary",
            },
        )

    def _store_chunks(
        self,
        *,
        resource: Dict[str, Any],
        chunks: List[str],
        summary: str,
        metadata_updates: Dict[str, Any],
        chunk_indexes: Optional[List[int]] = None,
        chunk_metadata_overrides: Optional[Dict[str, Any]] = None,
        per_chunk_metadata_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if not chunks:
            raise IngestionError("No chunks were produced from the source content.")

        embeddings = self.embedding_service.embed_texts(chunks)
        resource_id = resource["_id"]
        base_chunk_metadata = {
            "topic": resource.get("topic"),
            "level": metadata_updates.get("level"),
            "source": resource.get("source"),
            "resource_type": resource.get("type"),
            **(chunk_metadata_overrides or {}),
        }
        documents = build_chunk_documents(
            resource_id=resource_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata=base_chunk_metadata,
            chunk_indexes=chunk_indexes,
            chunk_metadata_overrides=per_chunk_metadata_overrides,
        )
        inserted = self.chunk_repository.insert_many(documents)

        vector_records = []
        for document in documents:
            vector_records.append(
                {
                    "id": f"{resource_id}:{document['chunk_index']}",
                    "embedding": document["embedding"],
                    "content": document["content"],
                    "metadata": {
                        "topic": str(document["metadata"].get("topic") or ""),
                        "level": str(document["metadata"].get("level") or ""),
                        "resource_id": str(resource_id),
                        "chunk_index": document["chunk_index"],
                        "page_number": document["metadata"].get("page_number"),
                    },
                }
            )
        self.embedding_service.vector_store.upsert_chunks(vector_records)
        return {
            "chunks_count": inserted,
            "content_summary": summary,
            "metadata": metadata_updates,
        }

    def _rank_chunks_by_topic(self, chunks: List[str], *, topic: str, limit: int) -> List[str]:
        """Use embedding similarity instead of keyword maps to prioritize chunks."""
        if len(chunks) <= limit:
            return chunks
        chunk_embeddings = self.embedding_service.embed_texts(chunks)
        topic_embedding = self.embedding_service.embed_text(topic)
        topic_array = self._to_array(topic_embedding)
        scored: List[Tuple[float, str]] = []
        for chunk, embedding in zip(chunks, chunk_embeddings):
            score = cosine_similarity(topic_array, self._to_array(embedding))
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    @staticmethod
    def _to_array(values: List[float]):
        import numpy as np

        return np.array(values, dtype=float)

    def _build_submission_response(self, *, resource: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "resource_id": str(resource["_id"]),
            "job_id": str(job["_id"]),
            "status": job.get("status", "pending"),
            "chunks_count": int(resource.get("chunks_count", 0)),
            "processing_time": float(resource.get("processing_time", 0.0)),
        }

    def _build_duplicate_response(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "resource_id": str(resource["_id"]),
            "job_id": None,
            "status": resource.get("status", "done"),
            "chunks_count": int(resource.get("chunks_count", 0)),
            "processing_time": float(resource.get("processing_time", 0.0)),
            "duplicate": True,
        }

    def _serialize_job(
        self,
        *,
        job: Dict[str, Any],
        resource: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "job_id": str(job["_id"]),
            "resource_id": str(job["resource_id"]),
            "status": job.get("status"),
            "chunks_count": int(job.get("chunks_count", 0)),
            "processing_time": float(job.get("processing_time", 0.0)),
            "error": job.get("error"),
            "resource_status": resource.get("status") if resource else None,
        }

    def _require_resource(self, resource_id: str) -> Dict[str, Any]:
        resource = self.resource_repository.get(resource_id)
        if not resource:
            raise IngestionError("Resource not found for ingestion job.")
        return resource

    @staticmethod
    def _summarize_content(content: str) -> str:
        content = clean_text(content)
        return content[:SUMMARY_LENGTH].strip()

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        name = Path(filename).name
        safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in name)
        if not safe.lower().endswith(".pdf"):
            safe = f"{safe}.pdf"
        return safe

    @staticmethod
    def _build_pdf_title(filename: str) -> str:
        stem = Path(filename).stem.strip()
        if not stem:
            return "PDF document"

        normalized = stem.replace("_", " ").replace("-", " ")
        normalized = re.sub(r"([A-Za-z])(\d)", r"\1 \2", normalized)
        normalized = re.sub(r"(\d)([A-Za-z])", r"\1 \2", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized or "PDF document"

    @staticmethod
    def extract_video_id(url: str) -> str:
        """Extract YouTube `video_id` from common URL formats."""
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        if hostname in {"youtu.be", "www.youtu.be"}:
            candidate = parsed.path.lstrip("/").split("/")[0]
        elif "youtube.com" in hostname:
            if parsed.path == "/watch":
                candidate = parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
                candidate = parsed.path.strip("/").split("/")[1]
            else:
                candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            raise ValueError("Invalid YouTube URL.")

        if len(candidate) != 11 or not candidate.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid YouTube video identifier.")
        return candidate

    @staticmethod
    def extract_pdf_pages(file_path: str) -> Tuple[List[Tuple[int, str]], int]:
        """Extract normalized text for each readable page plus total page count."""
        if PYMUPDF_AVAILABLE and fitz is not None:
            document = fitz.open(file_path)
            try:
                pages: List[Tuple[int, str]] = []
                for page_number, page in enumerate(document, start=1):
                    page_text = clean_text(page.get_text())
                    if page_text:
                        pages.append((page_number, page_text))
                return pages, len(document)
            finally:
                document.close()
        if PYPDF_AVAILABLE and PdfReader is not None:
            reader = PdfReader(file_path)
            pages: List[Tuple[int, str]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = clean_text(page.extract_text() or "")
                if page_text:
                    pages.append((page_number, page_text))
            return pages, len(reader.pages)
        raise IngestionError("No PDF extraction library available.")

    @staticmethod
    def fetch_youtube_metadata(video_id: str, youtube_url: str) -> Dict[str, Any]:
        """Fetch metadata with graceful fallback."""
        fallback = {
            "video_id": video_id,
            "youtube_url": youtube_url,
            "duration": 0,
            "channel": "Unknown Channel",
            "views": 0,
            "thumbnail_url": None,
        }
        if not PYTUBE_AVAILABLE or YouTube is None:
            return fallback
        try:  # pragma: no cover - optional external integration
            video = YouTube(youtube_url, use_oauth=False, allow_oauth_cache=False)
            return {
                **fallback,
                "title": video.title or fallback.get("title"),
                "duration": video.length or 0,
                "channel": video.author or fallback["channel"],
                "views": video.views or 0,
                "publish_date": video.publish_date.isoformat() if video.publish_date else None,
                "thumbnail_url": video.thumbnail_url,
            }
        except Exception as exc:
            logger.warning("Failed to fetch YouTube metadata for %s: %s", video_id, exc)
            return fallback

    @staticmethod
    def fetch_youtube_transcript(video_id: str) -> Tuple[Optional[str], Optional[str]]:
        """Fetch transcript text and language."""
        if not TRANSCRIPT_API_AVAILABLE or YouTubeTranscriptApi is None:
            return None, None
        languages = ["en", "vi", "es", "fr"]
        for language in languages:
            try:  # pragma: no cover - optional external integration
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
                text = " ".join(entry.get("text", "") for entry in transcript).strip()
                if text:
                    return text, language
            except (TranscriptsDisabled, NoTranscriptFound):
                continue
            except Exception as exc:
                logger.debug("Transcript fetch failed for %s (%s): %s", video_id, language, exc)
                continue
        return None, None


ingestion_service = IngestionService()
