from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import cosine_similarity, embed_text

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 900
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_RETRIEVAL_K = 12
MIN_CHUNK_CHARS = 120


@dataclass(frozen=True)
class LessonDocument:
    document_id: str
    lesson_id: str
    title: str
    content: str
    source_type: str
    metadata: Dict[str, str]


@dataclass(frozen=True)
class LessonChunk:
    chunk_id: str
    lesson_id: str
    chunk_index: int
    text: str
    source_type: str
    source_title: str
    score: float = 0.0
    metadata: Dict[str, str] | None = None


class LessonContentRetrievalService:
    """
    MVP retrieval service for lesson-grounded question generation.

    Pipeline:
    1. Resolve lesson context.
    2. Collect lesson material from lesson summary + linked resources.
    3. Chunk content with overlap.
    4. Persist chunks for traceability.
    5. Retrieve top-k relevant chunks using embedding similarity.
    """

    def __init__(self) -> None:
        self.db = get_db()

    def build_query_text(self, lesson_id: str) -> str:
        context = self._resolve_lesson_context(lesson_id)
        concept_names = ", ".join(item["name"] for item in context.get("concept_list", []))
        lesson_title = str(context.get("lesson_title") or "Lesson")
        chapter_title = str(context.get("chapter_title") or "")
        query_parts = [lesson_title, chapter_title, concept_names]
        return " | ".join(part for part in query_parts if part).strip()

    def get_relevant_chunks(
        self,
        lesson_id: str,
        *,
        top_k: int = DEFAULT_RETRIEVAL_K,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[LessonChunk]:
        context = self._resolve_lesson_context(lesson_id)
        documents = self._load_lesson_documents(context)
        if not documents:
            raise ValueError(f"No lesson materials found for lesson_id={lesson_id}")

        chunks = self._chunk_documents(
            lesson_id=lesson_id,
            documents=documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        if not chunks:
            raise ValueError(f"Could not create chunks for lesson_id={lesson_id}")

        self._store_chunks(lesson_id=lesson_id, chunks=chunks)
        query_text = self.build_query_text(lesson_id)
        return self._rank_chunks(query_text=query_text, chunks=chunks, top_k=top_k)

    def _resolve_lesson_context(self, lesson_id: str) -> Dict:
        lessons_collection = getattr(self.db, "lessons", None)
        if lessons_collection is not None:
            lesson = lessons_collection.find_one({"lesson_id": lesson_id}, {"_id": 0})
            if lesson:
                return {
                    "lesson_id": lesson_id,
                    "lesson_title": lesson.get("title") or lesson.get("lesson_name") or "Lesson",
                    "lesson_summary": lesson.get("summary") or lesson.get("content") or "",
                    "chapter_id": str(lesson.get("chapter_id") or ""),
                    "chapter_title": str(lesson.get("chapter_title") or ""),
                    "lesson_resources": lesson.get("resources") or [],
                    "concept_list": list(lesson.get("concept_list") or []),
                }

        path = self.db.learning_paths.find_one(
            {"curriculum.lessons.lesson_id": lesson_id},
            {"curriculum": 1, "_id": 0},
        )
        if not path:
            raise ValueError(f"Lesson not found: {lesson_id}")

        for chapter in path.get("curriculum", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                if lesson.get("lesson_id") != lesson_id:
                    continue
                concept_list = list(lesson.get("concept_list") or chapter.get("concepts") or [])
                return {
                    "lesson_id": lesson_id,
                    "lesson_title": lesson.get("title") or "Lesson",
                    "lesson_summary": lesson.get("summary") or lesson.get("content") or "",
                    "chapter_id": str(chapter.get("chapter_id") or chapter.get("id") or ""),
                    "chapter_title": str(chapter.get("title") or ""),
                    "lesson_resources": lesson.get("resources") or [],
                    "concept_list": concept_list,
                }

        raise ValueError(f"Lesson not found: {lesson_id}")

    def _load_lesson_documents(self, context: Dict) -> List[LessonDocument]:
        lesson_id = str(context["lesson_id"])
        lesson_title = str(context.get("lesson_title") or "Lesson")
        summary = self._clean_text(str(context.get("lesson_summary") or ""))

        documents: List[LessonDocument] = []
        if summary:
            documents.append(
                LessonDocument(
                    document_id=f"{lesson_id}:summary",
                    lesson_id=lesson_id,
                    title=f"{lesson_title} Summary",
                    content=summary,
                    source_type="lesson_summary",
                    metadata={"lesson_title": lesson_title},
                )
            )

        concept_names = [str(item.get("name") or item.get("concept_name") or "").strip() for item in context.get("concept_list", [])]
        concept_names = [item for item in concept_names if item]
        resource_titles = [str(item).strip() for item in context.get("lesson_resources", []) if str(item).strip()]

        resource_query = {"$or": []}
        if concept_names:
            resource_query["$or"].append({"topic": {"$in": concept_names}})
            resource_query["$or"].append({"title": {"$in": resource_titles or concept_names}})
        if resource_titles:
            resource_query["$or"].append({"title": {"$in": resource_titles}})
        concept_ids = [str(item.get("id") or item.get("concept_id") or "").strip() for item in context.get("concept_list", [])]
        numeric_concept_ids = [int(item) for item in concept_ids if item.isdigit()]
        if numeric_concept_ids:
            resource_query["$or"].append({"concept_id": {"$in": numeric_concept_ids}})
        if not resource_query["$or"]:
            resource_query = {"title": lesson_title}

        try:
            resource_docs = list(
                self.db.resources.find(
                    resource_query,
                    {
                        "_id": 1,
                        "title": 1,
                        "content": 1,
                        "topic": 1,
                        "source": 1,
                        "url": 1,
                        "concept_id": 1,
                    },
                ).limit(20)
            )
        except Exception as exc:
            logger.warning("Failed to load resource docs for lesson_id=%s: %s", lesson_id, exc)
            resource_docs = []

        for doc in resource_docs:
            content = self._clean_text(str(doc.get("content") or ""))
            if len(content) < MIN_CHUNK_CHARS:
                continue
            documents.append(
                LessonDocument(
                    document_id=str(doc.get("_id")),
                    lesson_id=lesson_id,
                    title=str(doc.get("title") or lesson_title),
                    content=content,
                    source_type=str(doc.get("source") or "resource"),
                    metadata={
                        "topic": str(doc.get("topic") or ""),
                        "url": str(doc.get("url") or ""),
                        "concept_id": str(doc.get("concept_id") or ""),
                    },
                )
            )

        if not documents:
            fallback = self._build_fallback_material(context)
            documents.append(
                LessonDocument(
                    document_id=f"{lesson_id}:fallback",
                    lesson_id=lesson_id,
                    title=lesson_title,
                    content=fallback,
                    source_type="lesson_fallback",
                    metadata={"lesson_title": lesson_title},
                )
            )

        return documents

    def _chunk_documents(
        self,
        *,
        lesson_id: str,
        documents: Sequence[LessonDocument],
        chunk_size: int,
        chunk_overlap: int,
    ) -> List[LessonChunk]:
        chunks: List[LessonChunk] = []
        global_index = 0
        for document in documents:
            for local_index, chunk_text in enumerate(self._split_text(document.content, chunk_size, chunk_overlap)):
                chunks.append(
                    LessonChunk(
                        chunk_id=f"{lesson_id}:{document.document_id}:{local_index}",
                        lesson_id=lesson_id,
                        chunk_index=global_index,
                        text=chunk_text,
                        source_type=document.source_type,
                        source_title=document.title,
                        metadata={
                            "document_id": document.document_id,
                            "source_title": document.title,
                            **document.metadata,
                        },
                    )
                )
                global_index += 1
        return chunks

    def _rank_chunks(self, *, query_text: str, chunks: Sequence[LessonChunk], top_k: int) -> List[LessonChunk]:
        query_embedding = embed_text(query_text)
        ranked: List[LessonChunk] = []
        for chunk in chunks:
            score = cosine_similarity(
                a=self._to_vector(query_embedding),
                b=self._to_vector(embed_text(chunk.text)),
            )
            ranked.append(
                LessonChunk(
                    chunk_id=chunk.chunk_id,
                    lesson_id=chunk.lesson_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    source_type=chunk.source_type,
                    source_title=chunk.source_title,
                    score=float(score),
                    metadata=chunk.metadata,
                )
            )

        ranked.sort(key=lambda item: (item.score, len(item.text)), reverse=True)
        return ranked[: max(1, top_k)]

    def _store_chunks(self, *, lesson_id: str, chunks: Sequence[LessonChunk]) -> None:
        now = datetime.utcnow()
        payload = []
        for chunk in chunks:
            payload.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "lesson_id": lesson_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "source_type": chunk.source_type,
                    "source_title": chunk.source_title,
                    "metadata": chunk.metadata or {},
                    "created_at": now,
                    "updated_at": now,
                }
            )

        try:
            self.db.lesson_content_chunks.delete_many({"lesson_id": lesson_id})
            if payload:
                self.db.lesson_content_chunks.insert_many(payload)
        except Exception as exc:
            logger.warning("Failed to persist lesson chunks for lesson_id=%s: %s", lesson_id, exc)

    @staticmethod
    def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
        normalized = LessonContentRetrievalService._clean_text(text)
        if not normalized:
            return []

        sentences = re.split(r"(?<=[\.\!\?])\s+", normalized)
        chunks: List[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= chunk_size:
                current = candidate
                continue
            if current and len(current) >= MIN_CHUNK_CHARS:
                chunks.append(current)
            current = sentence

        if current:
            chunks.append(current)

        if len(chunks) <= 1 or chunk_overlap <= 0:
            return chunks

        overlapped: List[str] = []
        previous_tail = ""
        for chunk in chunks:
            candidate = f"{previous_tail} {chunk}".strip() if previous_tail else chunk
            overlapped.append(candidate)
            previous_tail = chunk[max(0, len(chunk) - chunk_overlap) :].strip()
        return overlapped

    @staticmethod
    def _build_fallback_material(context: Dict) -> str:
        lesson_title = str(context.get("lesson_title") or "Lesson")
        concept_names = ", ".join(
            str(item.get("name") or item.get("concept_name") or "").strip()
            for item in context.get("concept_list", [])
            if str(item.get("name") or item.get("concept_name") or "").strip()
        )
        summary = str(context.get("lesson_summary") or "").strip()
        return ". ".join(part for part in [lesson_title, concept_names, summary] if part)

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    @staticmethod
    def _to_vector(values: Iterable[float]) -> List[float]:
        return [float(item) for item in values]


def retrieve_relevant_lesson_chunks(lesson_id: str, top_k: int = DEFAULT_RETRIEVAL_K) -> List[LessonChunk]:
    service = LessonContentRetrievalService()
    return service.get_relevant_chunks(lesson_id=lesson_id, top_k=top_k)
