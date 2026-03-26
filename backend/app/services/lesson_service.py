"""Service layer for subject -> chapter -> lesson structure management."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.repositories import (
    ChapterRepository,
    LessonRepository,
    SubjectRepository,
)


def serialize_document(document: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Mongo-friendly objects into JSON-friendly primitives."""
    payload = dict(document)
    if isinstance(payload.get("_id"), ObjectId):
        payload["_id"] = str(payload["_id"])
    for key, value in list(payload.items()):
        if isinstance(value, ObjectId):
            payload[key] = str(value)
        elif isinstance(value, datetime):
            payload[key] = value.isoformat()
    return payload


class LessonStructureService:
    """Manage lesson hierarchy storage without touching retrieval or LLM logic."""

    def __init__(self) -> None:
        self.subject_repository = SubjectRepository()
        self.chapter_repository = ChapterRepository()
        self.lesson_repository = LessonRepository()

        self.subject_repository.ensure_indexes()
        self.chapter_repository.ensure_indexes()
        self.lesson_repository.ensure_indexes()

    def create_subject(self, payload: Any) -> Dict[str, Any]:
        subject = self.subject_repository.create(
            {
                "title": payload.title.strip(),
                "slug": payload.slug.strip().lower() if payload.slug else None,
                "description": payload.description,
                "topic": payload.topic,
                "level": payload.level.value,
                "metadata": payload.metadata,
            }
        )
        return {
            "subject_id": str(subject["_id"]),
            "title": subject["title"],
            "slug": subject.get("slug"),
            "description": subject.get("description"),
            "topic": subject.get("topic"),
            "level": subject.get("level"),
            "metadata": subject.get("metadata", {}),
            "created_at": subject["created_at"],
        }

    @staticmethod
    def _serialize_subject(subject: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "subject_id": str(subject["_id"]),
            "title": subject["title"],
            "slug": subject.get("slug"),
            "description": subject.get("description"),
            "topic": subject.get("topic"),
            "level": subject.get("level"),
            "metadata": subject.get("metadata", {}),
            "created_at": subject["created_at"],
        }

    @staticmethod
    def _serialize_chapter(chapter: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "chapter_id": str(chapter["_id"]),
            "subject_id": str(chapter["subject_id"]),
            "title": chapter["title"],
            "description": chapter.get("description"),
            "order": chapter.get("order", 1),
            "topic": chapter.get("topic"),
            "metadata": chapter.get("metadata", {}),
            "created_at": chapter["created_at"],
        }

    @staticmethod
    def _serialize_lesson(lesson: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "lesson_id": str(lesson["_id"]),
            "subject_id": str(lesson["subject_id"]),
            "chapter_id": str(lesson["chapter_id"]),
            "title": lesson["title"],
            "summary": lesson.get("summary"),
            "order": lesson.get("order", 1),
            "topic": lesson.get("topic"),
            "level": lesson.get("level"),
            "learning_objectives": lesson.get("learning_objectives", []),
            "keywords": lesson.get("keywords", []),
            "resource_ids": [str(item) for item in lesson.get("resource_ids", [])],
            "metadata": lesson.get("metadata", {}),
            "created_at": lesson["created_at"],
        }

    def get_subject(self, subject_id: str) -> Dict[str, Any]:
        try:
            subject = self.subject_repository.get(subject_id)
        except Exception as exc:
            raise ValueError("Subject not found.") from exc
        if not subject:
            raise ValueError("Subject not found.")
        return self._serialize_subject(subject)

    def list_subjects(self) -> List[Dict[str, Any]]:
        return [
            self._serialize_subject(subject)
            for subject in self.subject_repository.list()
        ]

    def list_subjects_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        q: Optional[str] = None,
        topic: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = self.subject_repository.list_paginated(
            page=page,
            size=size,
            q=q,
            topic=topic,
            level=level,
        )
        return {
            **result,
            "items": [self._serialize_subject(subject) for subject in result["items"]],
        }

    def create_chapter(self, payload: Any) -> Dict[str, Any]:
        subject = self.subject_repository.get(payload.subject_id)
        if not subject:
            raise ValueError("Subject not found.")

        chapter = self.chapter_repository.create(
            {
                "subject_id": subject["_id"],
                "title": payload.title.strip(),
                "description": payload.description,
                "order": payload.order,
                "topic": payload.topic or subject.get("topic"),
                "metadata": payload.metadata,
            }
        )
        return self._serialize_chapter(chapter)

    def get_chapter(self, chapter_id: str) -> Dict[str, Any]:
        try:
            chapter = self.chapter_repository.get(chapter_id)
        except Exception as exc:
            raise ValueError("Chapter not found.") from exc
        if not chapter:
            raise ValueError("Chapter not found.")
        return self._serialize_chapter(chapter)

    def list_chapters(self, subject_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if subject_id:
            try:
                subject = self.subject_repository.get(subject_id)
            except Exception as exc:
                raise ValueError("Subject not found.") from exc
            if not subject:
                raise ValueError("Subject not found.")
            chapters = self.chapter_repository.list_by_subject(subject_id)
        else:
            chapters = self.chapter_repository.list()
        return [self._serialize_chapter(chapter) for chapter in chapters]

    def list_chapters_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        subject_id: Optional[str] = None,
        q: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> Dict[str, Any]:
        if subject_id:
            try:
                subject = self.subject_repository.get(subject_id)
            except Exception as exc:
                raise ValueError("Subject not found.") from exc
            if not subject:
                raise ValueError("Subject not found.")
        result = self.chapter_repository.list_paginated(
            page=page,
            size=size,
            subject_id=subject_id,
            q=q,
            topic=topic,
        )
        return {
            **result,
            "items": [self._serialize_chapter(chapter) for chapter in result["items"]],
        }

    def create_lesson(self, payload: Any) -> Dict[str, Any]:
        subject = self.subject_repository.get(payload.subject_id)
        if not subject:
            raise ValueError("Subject not found.")
        chapter = self.chapter_repository.get(payload.chapter_id)
        if not chapter:
            raise ValueError("Chapter not found.")
        if str(chapter["subject_id"]) != str(subject["_id"]):
            raise ValueError("Chapter does not belong to the provided subject.")

        lesson = self.lesson_repository.create(
            {
                "subject_id": subject["_id"],
                "chapter_id": chapter["_id"],
                "title": payload.title.strip(),
                "summary": payload.summary,
                "order": payload.order,
                "topic": payload.topic or chapter.get("topic") or subject.get("topic"),
                "level": payload.level.value,
                "learning_objectives": payload.learning_objectives,
                "keywords": payload.keywords,
                "resource_ids": [
                    ObjectId(item)
                    for item in payload.resource_ids
                    if ObjectId.is_valid(item)
                ],
                "metadata": payload.metadata,
            }
        )
        return self._serialize_lesson(lesson)

    def get_lesson(self, lesson_id: str) -> Dict[str, Any]:
        try:
            lesson = self.lesson_repository.get(lesson_id)
        except Exception as exc:
            raise ValueError("Lesson not found.") from exc
        if not lesson:
            raise ValueError("Lesson not found.")
        return self._serialize_lesson(lesson)

    def list_lessons(
        self,
        *,
        chapter_id: Optional[str] = None,
        subject_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if chapter_id:
            try:
                chapter = self.chapter_repository.get(chapter_id)
            except Exception as exc:
                raise ValueError("Chapter not found.") from exc
            if not chapter:
                raise ValueError("Chapter not found.")
            lessons = self.lesson_repository.list_by_chapter(chapter_id)
        elif subject_id:
            try:
                subject = self.subject_repository.get(subject_id)
            except Exception as exc:
                raise ValueError("Subject not found.") from exc
            if not subject:
                raise ValueError("Subject not found.")
            lessons = self.lesson_repository.list_by_subject(subject_id)
        else:
            lessons = self.lesson_repository.list()
        return [self._serialize_lesson(lesson) for lesson in lessons]

    def list_lessons_paginated(
        self,
        *,
        page: int = 1,
        size: int = 20,
        chapter_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        q: Optional[str] = None,
        topic: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        if chapter_id:
            try:
                chapter = self.chapter_repository.get(chapter_id)
            except Exception as exc:
                raise ValueError("Chapter not found.") from exc
            if not chapter:
                raise ValueError("Chapter not found.")
        if subject_id:
            try:
                subject = self.subject_repository.get(subject_id)
            except Exception as exc:
                raise ValueError("Subject not found.") from exc
            if not subject:
                raise ValueError("Subject not found.")
        result = self.lesson_repository.list_paginated(
            page=page,
            size=size,
            chapter_id=chapter_id,
            subject_id=subject_id,
            q=q,
            topic=topic,
            level=level,
        )
        return {
            **result,
            "items": [self._serialize_lesson(lesson) for lesson in result["items"]],
        }

    def get_lesson_context(self, lesson_id: str) -> Dict[str, Any]:
        lesson = self.lesson_repository.get(lesson_id)
        if not lesson:
            raise ValueError("Lesson not found.")
        chapter = self.chapter_repository.get(lesson["chapter_id"])
        subject = self.subject_repository.get(lesson["subject_id"])
        if not chapter or not subject:
            raise ValueError("Lesson hierarchy is incomplete.")
        return {
            "subject": subject,
            "chapter": chapter,
            "lesson": lesson,
        }


lesson_structure_service = LessonStructureService()
