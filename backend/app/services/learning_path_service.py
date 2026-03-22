"""Hybrid learning path generation service for subject -> chapter -> lesson flows."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from backend.app.ai_module import CurriculumLLMClient
from backend.app.repositories import (
    ChapterRepository,
    LearningPathRepository,
    LessonRepository,
    SubjectRepository,
)
from backend.app.services.lesson_chunk_service import lesson_chunk_service
from backend.app.services.learning_path_prompt_builder import (
    build_fallback_curriculum,
    build_learning_path_prompt,
    extract_json_object,
    get_subject_label,
    normalize_curriculum,
)

logger = logging.getLogger(__name__)


class HybridLearningPathService:
    """Generate subject-scoped curricula and freeze lesson chunk recommendations locally."""

    def __init__(self) -> None:
        self.subject_repository = SubjectRepository()
        self.chapter_repository = ChapterRepository()
        self.lesson_repository = LessonRepository()
        self.learning_path_repository = LearningPathRepository()
        self.lesson_chunk_service = lesson_chunk_service
        self.llm_client = CurriculumLLMClient()
        self.max_chunks_per_lesson = int(os.getenv("LEARNING_PATH_MAX_CHUNKS_PER_LESSON", "8"))

        self.subject_repository.ensure_indexes()
        self.chapter_repository.ensure_indexes()
        self.lesson_repository.ensure_indexes()
        self.learning_path_repository.ensure_indexes()

    def generate_learning_path(
        self,
        *,
        subject_id: str,
        goal: str,
        level: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a learning path and precompute lesson-scoped recommended chunks."""
        normalized_subject_id = (subject_id or "").strip().lower()
        normalized_goal = (goal or "").strip()
        normalized_level = (level or "").strip().lower()

        self._validate_inputs(
            subject_id=normalized_subject_id,
            goal=normalized_goal,
            level=normalized_level,
        )
        subject_label = get_subject_label(normalized_subject_id) or ""
        llm_status = self.llm_client.status()

        logger.info(
            "Generating hybrid learning path: subject_id=%s goal=%s level=%s user_id=%s llm_enabled=%s",
            normalized_subject_id,
            normalized_goal,
            normalized_level,
            user_id,
            llm_status.get("enabled"),
        )

        curriculum_source = "fallback"
        curriculum = self._generate_curriculum(
            subject_id=normalized_subject_id,
            subject_label=subject_label,
            goal=normalized_goal,
            level=normalized_level,
        )
        if curriculum["source"] == "ai":
            curriculum_source = "ai"
        llm_status = curriculum["llm_status"]

        path_id = uuid.uuid4().hex
        subject = self._ensure_subject(
            subject_id=normalized_subject_id,
            subject_label=subject_label,
            level=normalized_level,
        )

        chapter_responses: List[Dict[str, Any]] = []
        lesson_progress: Dict[str, str] = {}
        total_lessons = 0
        for chapter_index, chapter_payload in enumerate(curriculum["chapters"], start=1):
            chapter = self.chapter_repository.create(
                {
                    "subject_id": subject["_id"],
                    "title": chapter_payload["title"],
                    "description": f"Learning path chapter for goal: {normalized_goal}",
                    "order": chapter_index,
                    "topic": normalized_subject_id,
                    "metadata": {
                        "learning_path_id": path_id,
                        "subject_key": normalized_subject_id,
                        "goal": normalized_goal,
                        "level": normalized_level,
                        "generated_by": "hybrid_learning_path_service",
                    },
                }
            )

            lesson_responses: List[Dict[str, Any]] = []
            for lesson_index, lesson_payload in enumerate(chapter_payload["lessons"], start=1):
                lesson = self.lesson_repository.create(
                    {
                        "subject_id": subject["_id"],
                        "chapter_id": chapter["_id"],
                        "title": lesson_payload["title"],
                        "summary": lesson_payload["summary"],
                        "order": lesson_index,
                        "topic": normalized_subject_id,
                        "level": normalized_level,
                        "learning_objectives": [lesson_payload["summary"]],
                        "keywords": self._build_keywords(
                            subject_label=subject_label,
                            chapter_title=chapter_payload["title"],
                            lesson_title=lesson_payload["title"],
                            goal=normalized_goal,
                        ),
                        "resource_ids": [],
                        "metadata": {
                            "learning_path_id": path_id,
                            "subject_key": normalized_subject_id,
                            "goal": normalized_goal,
                            "level": normalized_level,
                            "generated_by": "hybrid_learning_path_service",
                            "curriculum_source": curriculum_source,
                        },
                    }
                )

                recommendation = self._recommend_chunks_for_lesson(
                    lesson=lesson,
                    chapter=chapter,
                    subject=subject,
                    goal=normalized_goal,
                    level=normalized_level,
                    path_id=path_id,
                )
                recommended_chunk_ids = recommendation.get("chunk_ids", [])
                recommended_resource_ids = recommendation.get("resource_ids", [])
                self.lesson_repository.update(
                    lesson["_id"],
                    {
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "recommended_resource_ids": recommended_resource_ids,
                    },
                )

                total_lessons += 1
                lesson_progress[str(lesson["_id"])] = "not_started"
                logger.info(
                    "Lesson recommendation ready: lesson_id=%s chunks=%s resources=%s",
                    lesson["_id"],
                    len(recommended_chunk_ids),
                    len(recommended_resource_ids),
                )
                lesson_responses.append(
                    {
                        "lesson_id": str(lesson["_id"]),
                        "title": lesson["title"],
                        "summary": lesson.get("summary"),
                        "recommended_chunk_ids": recommended_chunk_ids,
                        "status": "not_started",
                    }
                )

            chapter_responses.append(
                {
                    "chapter_id": str(chapter["_id"]),
                    "title": chapter["title"],
                    "lessons": lesson_responses,
                }
            )

        self.learning_path_repository.create(
            {
                "path_id": path_id,
                "user_id": user_id,
                "subject_id": normalized_subject_id,
                "subject_ref_id": subject["_id"],
                "subject_label": subject_label,
                "goal": normalized_goal,
                "level": normalized_level,
                "chapters": chapter_responses,
                "curriculum_source": curriculum_source,
                "llm_status": llm_status,
                "lesson_progress": lesson_progress,
                "metadata": {
                    "pipeline": "hybrid_subject_lesson_v1",
                    "chapter_count": len(chapter_responses),
                    "lesson_count": total_lessons,
                },
            }
        )

        logger.info(
            "Hybrid learning path generated: path_id=%s chapters=%s lessons=%s subject_id=%s",
            path_id,
            len(chapter_responses),
            total_lessons,
            normalized_subject_id,
        )
        return {
            "path_id": path_id,
            "subject_id": normalized_subject_id,
            "goal": normalized_goal,
            "level": normalized_level,
            "generated_at": datetime.utcnow(),
            "chapters": chapter_responses,
            "curriculum_source": curriculum_source,
            "llm_status": llm_status,
            "message": f"Generated learning path with {len(chapter_responses)} chapters and {total_lessons} lessons.",
        }

    def get_learning_path(self, *, path_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Load a generated learning path with optional ownership validation."""
        normalized_path_id = (path_id or "").strip()
        if not normalized_path_id:
            raise ValueError("path_id is required")

        document = self.learning_path_repository.get_by_path_id(normalized_path_id)
        if not document:
            raise ValueError("Learning path not found.")

        owner_id = document.get("user_id")
        if user_id and owner_id and str(owner_id) != str(user_id):
            raise ValueError("Learning path not found.")

        return self._serialize_learning_path(document)

    def list_learning_paths(self, *, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """List learning paths for the current user across legacy and hybrid documents."""
        documents = list(self.learning_path_repository.collection.find({"user_id": user_id}))
        documents.sort(
            key=lambda item: self._resolve_generated_at(item),
            reverse=True,
        )
        serialized = [self._serialize_learning_path(item) for item in documents[:limit]]
        return serialized

    def update_lesson_progress(
        self,
        *,
        path_id: str,
        user_id: str,
        lesson_id: str,
        status: str,
    ) -> Dict[str, Any]:
        """Update lesson progress for a stored learning path document."""
        document = self.learning_path_repository.get_by_path_id(path_id)
        if not document or str(document.get("user_id") or "") != str(user_id):
            raise ValueError("Learning path not found.")

        normalized = self._serialize_learning_path(document)
        known_lessons = {
            lesson.get("lesson_id")
            for chapter in normalized.get("chapters", [])
            for lesson in chapter.get("lessons", [])
            if lesson.get("lesson_id")
        }
        if lesson_id not in known_lessons:
            raise ValueError("Lesson not found in learning path.")

        updated_at = datetime.utcnow()
        lesson_progress = dict(document.get("lesson_progress") or {})
        lesson_progress[lesson_id] = status

        self.learning_path_repository.collection.update_one(
            {"_id": document["_id"]},
            {
                "$set": {
                    "lesson_progress": lesson_progress,
                    "updated_at": updated_at,
                }
            },
        )

        return {
            "path_id": path_id,
            "lesson_id": lesson_id,
            "status": status,
            "updated_at": updated_at,
        }

    @staticmethod
    def _validate_inputs(*, subject_id: str, goal: str, level: str) -> None:
        if not get_subject_label(subject_id):
            raise ValueError(f"Unsupported subject_id: {subject_id}")
        if level not in {"beginner", "intermediate", "advanced"}:
            raise ValueError(f"Unsupported level: {level}")
        if len(goal.strip()) < 3:
            raise ValueError("goal must be at least 3 characters")

    def _ensure_subject(self, *, subject_id: str, subject_label: str, level: str) -> Dict[str, Any]:
        subject = self.subject_repository.get_by_slug(subject_id)
        if subject:
            return subject
        try:
            return self.subject_repository.create(
                {
                    "title": subject_label,
                    "slug": subject_id,
                    "description": f"Fixed subject catalog entry for {subject_label}.",
                    "topic": subject_id,
                    "level": level,
                    "metadata": {
                        "is_fixed_subject": True,
                        "subject_key": subject_id,
                    },
                }
            )
        except DuplicateKeyError:
            subject = self.subject_repository.get_by_slug(subject_id)
            if subject:
                return subject
            raise

    def _generate_curriculum(
        self,
        *,
        subject_id: str,
        subject_label: str,
        goal: str,
        level: str,
    ) -> Dict[str, Any]:
        fallback = build_fallback_curriculum(subject_id=subject_id, goal=goal, level=level)
        llm_status = self.llm_client.status()
        if not self.llm_client.is_available():
            logger.warning("Curriculum LLM unavailable, using fallback curriculum for subject_id=%s", subject_id)
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        prompt = build_learning_path_prompt(subject_label=subject_label, goal=goal, level=level)
        raw_text = self.llm_client.generate(prompt)
        json_text = extract_json_object(raw_text)
        if not json_text:
            logger.warning("Curriculum LLM returned no JSON, using fallback curriculum for subject_id=%s", subject_id)
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        try:
            parsed = json.loads(json_text)
        except json.JSONDecodeError as exc:
            logger.warning("Curriculum JSON parse failed for subject_id=%s: %s", subject_id, exc)
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        normalized = normalize_curriculum(parsed)
        if not normalized:
            logger.warning("Curriculum normalization produced no chapters, using fallback for subject_id=%s", subject_id)
            return {
                "chapters": fallback,
                "source": "fallback",
                "llm_status": llm_status,
            }

        logger.info(
            "Curriculum LLM succeeded: subject_id=%s chapters=%s lessons=%s",
            subject_id,
            len(normalized),
            sum(len(chapter.get("lessons", [])) for chapter in normalized),
        )
        return {
            "chapters": normalized,
            "source": "ai",
            "llm_status": llm_status,
        }

    def _recommend_chunks_for_lesson(
        self,
        *,
        lesson: Dict[str, Any],
        chapter: Dict[str, Any],
        subject: Dict[str, Any],
        goal: str,
        level: str,
        path_id: str,
    ) -> Dict[str, Any]:
        metadata = {
            "goal": goal,
            "level": level,
            "learning_path_id": path_id,
            "subject_key": subject.get("slug"),
            "pipeline": "hybrid_subject_lesson_v1",
        }
        try:
            return self.lesson_chunk_service.recommend_chunks(
                lesson_id=str(lesson["_id"]),
                max_chunks=self.max_chunks_per_lesson,
                selection_strategy="local_semantic_lesson_scope_v1",
                resource_ids=[],
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning(
                "Primary lesson chunk recommendation failed for lesson_id=%s: %s. Falling back to top local chunks.",
                lesson["_id"],
                exc,
            )
            return self._fallback_recommendation(
                lesson=lesson,
                chapter=chapter,
                subject=subject,
                metadata=metadata,
            )

    def _fallback_recommendation(
        self,
        *,
        lesson: Dict[str, Any],
        chapter: Dict[str, Any],
        subject: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        topic = lesson.get("topic") or chapter.get("topic") or subject.get("topic")
        level = lesson.get("level")
        candidate_chunks = self.lesson_chunk_service.chunk_repository.candidate_chunks(
            topic=topic,
            level=level,
            limit=self.max_chunks_per_lesson,
        )
        if not candidate_chunks:
            candidate_chunks = self.lesson_chunk_service.chunk_repository.candidate_chunks(
                level=level,
                limit=self.max_chunks_per_lesson,
            )
        if not candidate_chunks:
            candidate_chunks = self.lesson_chunk_service.chunk_repository.candidate_chunks(
                limit=self.max_chunks_per_lesson,
            )

        selected_chunks = [
            {
                "chunk_id": str(chunk["_id"]),
                "resource_id": str(chunk["resource_id"]),
                "chunk_index": int(chunk.get("chunk_index", 0)),
                "score": 0.0,
                "preview": str(chunk.get("content") or "")[:240],
            }
            for chunk in candidate_chunks[: self.max_chunks_per_lesson]
        ]
        chunk_object_ids = [ObjectId(item["chunk_id"]) for item in selected_chunks]
        resource_object_ids = [ObjectId(item["resource_id"]) for item in selected_chunks]

        recommendation = self.lesson_chunk_service.recommendation_repository.upsert_for_lesson(
            lesson["_id"],
            {
                "subject_id": subject["_id"],
                "chapter_id": chapter["_id"],
                "lesson_id": lesson["_id"],
                "chunk_ids": chunk_object_ids,
                "resource_ids": resource_object_ids,
                "selection_strategy": "fallback_top_chunks_v1",
                "metadata": {
                    **metadata,
                    "fallback": True,
                    "selected_count": len(selected_chunks),
                    "candidate_count": len(candidate_chunks),
                },
            },
        )
        return self.lesson_chunk_service._serialize_recommendation(recommendation, selected_chunks)

    @staticmethod
    def _build_keywords(
        *,
        subject_label: str,
        chapter_title: str,
        lesson_title: str,
        goal: str,
    ) -> List[str]:
        tokens = [subject_label, chapter_title, lesson_title, goal]
        return [token.strip() for token in tokens if token and token.strip()]

    def _serialize_learning_path(self, document: Dict[str, Any]) -> Dict[str, Any]:
        subject_id = str(document.get("subject_id") or "python").strip().lower()
        if not get_subject_label(subject_id):
            subject_id = "python"

        chapters = self._normalize_chapters(
            chapters=document.get("chapters") or document.get("curriculum") or [],
            lesson_progress=document.get("lesson_progress") or {},
        )
        return {
            "path_id": str(document.get("path_id") or ""),
            "subject_id": subject_id,
            "goal": document.get("goal", ""),
            "level": str(document.get("level") or "beginner").strip().lower(),
            "generated_at": self._resolve_generated_at(document),
            "chapters": chapters,
            "curriculum_source": document.get("curriculum_source", "fallback"),
            "llm_status": document.get("llm_status"),
            "message": document.get("message", ""),
        }

    @staticmethod
    def _normalize_chapters(
        *,
        chapters: List[Dict[str, Any]],
        lesson_progress: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for chapter in chapters or []:
            lessons_payload = []
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "")
                lessons_payload.append(
                    {
                        "lesson_id": lesson_id,
                        "title": lesson.get("title", ""),
                        "summary": lesson.get("summary"),
                        "recommended_chunk_ids": [
                            str(item) for item in lesson.get("recommended_chunk_ids", []) or []
                        ],
                        "status": lesson_progress.get(lesson_id, lesson.get("status", "not_started")),
                    }
                )
            normalized.append(
                {
                    "chapter_id": str(chapter.get("chapter_id") or ""),
                    "title": chapter.get("title", ""),
                    "lessons": lessons_payload,
                }
            )
        return normalized

    @staticmethod
    def _resolve_generated_at(document: Dict[str, Any]) -> datetime:
        for key in ("generated_at", "created_at", "updated_at"):
            value = document.get(key)
            if isinstance(value, datetime):
                return value
        return datetime.utcnow()


learning_path_service = HybridLearningPathService()
