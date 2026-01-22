import os
from typing import List, Dict

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import semantic_search

# ===== Optional LLM =====
USE_LLM = True
try:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    USE_LLM = False
    client = None


# ===== RULE-BASED BASE PATH (FALLBACK) =====
BASE_PATHS = {
    "python backend": [
        "Python Basics",
        "Control Flow",
        "Functions",
        "OOP",
        "Virtual Environment",
        "FastAPI Fundamentals",
        "Request/Response & Validation",
        "Authentication (JWT)",
        "MongoDB Basics",
        "Async & Background Tasks",
        "Testing",
        "Deployment"
    ],
    "data science": [
        "Python Basics",
        "NumPy",
        "Pandas",
        "Data Visualization",
        "Statistics",
        "Machine Learning Basics",
        "Model Evaluation",
        "Mini Project"
    ]
}


# ======================================================
# 1️⃣ RETRIEVE – Truy hồi học liệu (RAG)
# ======================================================
def retrieve_resources(goal: str, level: str, k: int = 5) -> List[Dict]:
    """
    Truy hồi học liệu bằng semantic search (embedding-based).
    """
    query = f"{goal} {level}"
    return semantic_search(query, k=k)


# ======================================================
# 2️⃣ CONTEXT BUILDER
# ======================================================
def build_context(resources: List[Dict]) -> str:
    """
    Chuyển học liệu thành context text cho LLM.
    """
    context_blocks = []
    for r in resources:
        context_blocks.append(
            f"- {r.get('title')} ({r.get('topic')}): {r.get('content', '')[:300]}"
        )
    return "\n".join(context_blocks)


# ======================================================
# 3️⃣ PROMPT TEMPLATE (RAG)
# ======================================================
def build_prompt(
    goal: str,
    level: str,
    completed: List[str],
    context: str
) -> str:
    return f"""
You are an AI learning path advisor.

Learner profile:
- Goal: {goal}
- Level: {level}
- Completed concepts: {completed}

Relevant learning materials:
{context}

Task:
- Generate a personalized learning path.
- Avoid concepts already completed.
- Order topics from basic to advanced.
- Output STRICT JSON with fields:
  goal, level, recommended_path (array of strings).
"""


# ======================================================
# 4️⃣ RULE-BASED FALLBACK
# ======================================================
def rule_based_path(goal: str, level: str, completed: List[str]) -> Dict:
    goal_key = goal.lower().strip()
    base = BASE_PATHS.get(goal_key, BASE_PATHS.get("python backend", []))
    return {
        "goal": goal,
        "level": level,
        "recommended_path": [c for c in base if c not in completed]
    }


# ======================================================
# 5️⃣ CORE – GENERATE LEARNING PATH (RAG-READY)
# ======================================================
def generate_learning_path(
    goal: str,
    level: str,
    completed_concepts: List[str]
) -> Dict:
    """
    Sinh lộ trình học cá nhân hóa theo RAG pipeline:
    Retrieve → Context → Prompt → LLM → Post-process → Fallback
    """

    # ----- Retrieve -----
    resources = retrieve_resources(goal, level)

    # ----- Build context -----
    context = build_context(resources)

    # ----- Build prompt -----
    prompt = build_prompt(goal, level, completed_concepts, context)

    # ----- LLM Generation -----
    if USE_LLM and client:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You output JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            content = response.choices[0].message.content

            if content.strip().startswith("{"):
                result = eval(content)

                # ----- Post-process -----
                filtered = [
                    c for c in result.get("recommended_path", [])
                    if c not in completed_concepts
                ]

                return {
                    "goal": goal,
                    "level": level,
                    "recommended_path": filtered
                }
        except Exception:
            pass

    # ----- Fallback -----
    return rule_based_path(goal, level, completed_concepts)
