from typing import List, Dict
from backend.app.services.rag_pipeline import RAGPipeline
from backend.app.services.progress_service import update_progress
from backend.app.services.learning_path_service import generate_learning_path
from backend.app.database.mongo import db

rag = RAGPipeline()


def detect_concept(question: str) -> str:
    """
    Rule-based concept detection (baseline)
    """
    q = question.lower()
    if "list" in q:
        return "Python List"
    if "dictionary" in q:
        return "Python Dictionary"
    if "loop" in q:
        return "Python Loop"
    return "General Python"


def get_concept_id(concept_name: str) -> int | None:
    concept = db.concepts.find_one({"concept_name": concept_name})
    return concept["concept_id"] if concept else None


def ask_ai_service(
    user_id: int,
    question: str,
    goal: str,
    level: str,
    completed: List[str]
) -> Dict:
    """
    Core AI orchestration logic:
    - RAG
    - Progress update
    - Learning path generation
    """

    # 1. RAG
    rag_result = rag.run(
        question=question,
        goal=goal,
        level=level,
        completed=completed
    )

    # 2. Update progress
    concept_name = detect_concept(question)
    concept_id = get_concept_id(concept_name)

    if concept_id is not None:
        update_progress(
            user_id=user_id,
            concept_id=concept_id,
            success=True
        )

    # 3. Learning path
    learning_path = generate_learning_path(
        user_id=user_id,
        goal=goal,
        level=level
    )

    return {
        "answer": rag_result,
        "learning_path": learning_path["recommended_path"]
    }
