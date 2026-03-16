"""
AI tutor feature package.

This package contains the RAG retrieval pipeline and the orchestration service
that powers the ask/tutor experience.
"""

from .rag import RAGPipeline, USE_LLM
from .service import AITutorService, ask_ai_service, detect_concepts_batch, recommend_next_concepts

__all__ = [
    "AITutorService",
    "RAGPipeline",
    "USE_LLM",
    "ask_ai_service",
    "detect_concepts_batch",
    "recommend_next_concepts",
]
