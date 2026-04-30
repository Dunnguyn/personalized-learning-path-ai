"""Backward-compatible import shim for the AI tutor RAG pipeline."""

from .context_retrieval import RAGPipeline, USE_LLM

__all__ = [
    "RAGPipeline",
    "USE_LLM",
]
