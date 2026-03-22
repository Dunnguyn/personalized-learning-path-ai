"""
Services Module
===============

Business logic and AI services:

Core Services:
- embedding_service: Vector embeddings and semantic search
- ai_tutor: Retrieval-Augmented Generation pipeline and tutor orchestration
- progress_tracking: Student progress and confidence scoring
- learning_path: Personalized learning path generation

Resource Management:
- resource_service: Resource CRUD and search operations
- ingestion_service: Background ingestion orchestration and job tracking
- chunk_service: Text cleaning and chunk construction helpers
- lesson_service: Subject/chapter/lesson hierarchy management
- lesson_chunk_service: Lesson-scoped chunk recommendation
- question_generation_service: Lesson-scoped question bank orchestration
- search_service: Search orchestration across local resource storage

Adaptive Learning:
- adaptive_engine: Adaptive learning mode decisions
- concept_mapper: Concept detection and mapping

"""

__all__ = [
    'embedding_service',
    'ai_tutor',
    'progress_tracking',
    'learning_path',
    'resource_service',
    'ingestion_service',
    'chunk_service',
    'lesson_service',
    'lesson_chunk_service',
    'question_generation_service',
    'search_service',
    'adaptive_engine',
    'concept_mapper',
]
