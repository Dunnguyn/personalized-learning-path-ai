"""
AI tutor feature package.

This package contains the RAG retrieval pipeline and the orchestration service
that powers the ask/tutor experience.
"""

__all__ = [
    "AITutorService",
    "RAGPipeline",
    "USE_LLM",
    "ask_ai_service",
    "detect_concepts_batch",
    "recommend_next_concepts",
]


def __getattr__(name):
    if name in {"RAGPipeline", "USE_LLM"}:
        from .rag import RAGPipeline, USE_LLM

        exports = {
            "RAGPipeline": RAGPipeline,
            "USE_LLM": USE_LLM,
        }
        return exports[name]

    if name in {
        "AITutorService",
        "ask_ai_service",
        "detect_concepts_batch",
        "recommend_next_concepts",
    }:
        from .service import (
            AITutorService,
            ask_ai_service,
            detect_concepts_batch,
            recommend_next_concepts,
        )

        exports = {
            "AITutorService": AITutorService,
            "ask_ai_service": ask_ai_service,
            "detect_concepts_batch": detect_concepts_batch,
            "recommend_next_concepts": recommend_next_concepts,
        }
        return exports[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
