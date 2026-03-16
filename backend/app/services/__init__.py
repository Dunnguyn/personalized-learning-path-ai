"""
Services Module
===============

Business logic and AI services:

Core Services:
- embedding_service: Vector embeddings and semantic search
- ai_tutor: Retrieval-Augmented Generation pipeline and tutor orchestration
- progress_tracking: Student progress, confidence state, and scoring
- learning_path: Personalized learning path generation

Resource Management:
- resource_service: Resource CRUD and search operations
- resource_imports: Learning material ingestion (manual, PDF, YouTube)

Adaptive Learning:
- adaptive_engine: Adaptive learning mode decisions
- concept_mapper: Concept detection and mapping

Feature Packages:
- question_generation: Rule-based and LLM-powered question generation flows
- lesson_quiz: Question bank storage, quiz attempts, and grading

"""

__all__ = [
    'embedding_service',
    'ai_tutor',
    'progress_tracking',
    'rag_pipeline',
    'ai_service',
    'progress_service',
    'confidence_service',
    'confidence_scorer',
    'learning_path',
    'learning_path_service',
    'resource_imports',
    'question_generator',
    'question_bank_service',
    'question_generation',
    'lesson_quiz',
    'resource_service',
    'adaptive_engine',
]
