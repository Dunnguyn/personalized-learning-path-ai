import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.mongo import db
from datetime import datetime

# ===============================
# 1. CLEAR OLD DATA (OPTIONAL)
# ===============================
db.concepts.delete_many({})
db.prerequisites.delete_many({})

print("🧹 Cleared concepts & prerequisites")

# ===============================
# 2. DEFINE CONCEPTS
# ===============================
concepts = [
    # ===== PYTHON BACKEND COURSE =====
    {
        "concept_id": 1,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Python Basics",
        "topic": "python",
        "difficulty": 1,
        "weight": 1.0,
        "bloom_level": "remember",
        "prerequisites": [],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 2,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Control Flow",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.1,
        "bloom_level": "apply",
        "prerequisites": [1],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 3,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Functions",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.1,
        "bloom_level": "apply",
        "prerequisites": [2],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 4,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "OOP",
        "topic": "python",
        "difficulty": 3,
        "weight": 1.2,
        "bloom_level": "analyze",
        "prerequisites": [3],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 5,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Virtual Environment",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.0,
        "bloom_level": "understand",
        "prerequisites": [1],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 6,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "FastAPI Fundamentals",
        "topic": "fastapi",
        "difficulty": 3,
        "weight": 1.3,
        "bloom_level": "apply",
        "prerequisites": [1],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 7,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Request & Response Validation",
        "topic": "fastapi",
        "difficulty": 3,
        "weight": 1.2,
        "bloom_level": "analyze",
        "prerequisites": [6],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 8,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Authentication (JWT)",
        "topic": "fastapi",
        "difficulty": 4,
        "weight": 1.4,
        "bloom_level": "evaluate",
        "prerequisites": [7],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 9,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "MongoDB Basics",
        "topic": "database",
        "difficulty": 3,
        "weight": 1.2,
        "bloom_level": "understand",
        "prerequisites": [1],
        "created_at": datetime.utcnow()
    },
    {
        "concept_id": 10,
        "course_id": 1,
        "course": "Python Backend",
        "concept_name": "Async & Background Tasks",
        "topic": "fastapi",
        "difficulty": 4,
        "weight": 1.4,
        "bloom_level": "create",
        "prerequisites": [6],
        "created_at": datetime.utcnow()
    }
]

db.concepts.insert_many(concepts)
print(f"✅ Inserted {len(concepts)} concepts")

# ===============================
# 3. DEFINE PREREQUISITE EDGES
# ===============================
prerequisites = [
    {"from_concept_id": 1, "to_concept_id": 2},
    {"from_concept_id": 2, "to_concept_id": 3},
    {"from_concept_id": 3, "to_concept_id": 4},
    {"from_concept_id": 1, "to_concept_id": 5},
    {"from_concept_id": 1, "to_concept_id": 6},
    {"from_concept_id": 6, "to_concept_id": 7},
    {"from_concept_id": 7, "to_concept_id": 8},
    {"from_concept_id": 1, "to_concept_id": 9},
    {"from_concept_id": 6, "to_concept_id": 10}
]

db.prerequisites.insert_many(prerequisites)
print(f"🔗 Inserted {len(prerequisites)} prerequisite edges")

print("🎉 SEED CONCEPT GRAPH COMPLETED SUCCESSFULLY")
