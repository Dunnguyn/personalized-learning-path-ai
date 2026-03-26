"""AI module abstractions for embeddings, retrieval, and LLM summarization."""

from .curriculum_llm import CurriculumLLMClient
from .embedding import (
    EmbeddingService,
    compute_content_hash,
    compute_file_hash,
    cosine_similarity,
)
from .lesson_question_llm import LessonQuestionLLMClient
from .llm import YouTubeSummaryService
from .retrieval import SemanticRetrievalService

__all__ = [
    "CurriculumLLMClient",
    "EmbeddingService",
    "LessonQuestionLLMClient",
    "SemanticRetrievalService",
    "YouTubeSummaryService",
    "compute_content_hash",
    "compute_file_hash",
    "cosine_similarity",
]
