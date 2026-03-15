"""
Services Module
===============

Business logic and AI services:

Core Services:
- embedding_service: Vector embeddings and semantic search
- rag_pipeline: Retrieval-Augmented Generation pipeline
- ai_service: Main AI tutor service
- progress_service: Student progress tracking and EMA scoring
- learning_path_service: Personalized learning path generation

Resource Management:
- resource_service: Resource CRUD and search operations
- resource_importer: Batch import with validation
- pdf_importer: PDF processing and parsing
- youtube_importer: YouTube content extraction
- youtube_summarizer: YouTube content summarization

Adaptive Learning:
- adaptive_engine: Adaptive learning mode decisions
- confidence_scorer: Confidence scoring algorithms
- concept_mapper: Concept detection and mapping

"""

__all__ = [
    'embedding_service',
    'rag_pipeline',
    'ai_service',
    'progress_service',
    'learning_path_service',
    'question_generator',
    'question_bank_service',
    'resource_service',
    'adaptive_engine',
]
