import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.mongo import db
from datetime import datetime

# =========================
# CLEAR OLD DATA (OPTIONAL)
# =========================
db.resources.delete_many({})

# =========================
# SEED RESOURCES
# =========================
resources = [
    # =====================
    # CONCEPT 1 – Python Basics
    # =====================
    {
        "resource_id": 101,
        "title": "What is Python?",
        "content": "Introduction to Python programming language.",
        "source": "video",
        "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
        "concept_id": 1,
        "pedagogy_type": "video",
        "bloom_level": "remember",
        "created_at": datetime.utcnow()
    },
    {
        "resource_id": 102,
        "title": "Python Syntax Overview",
        "content": "Basic Python syntax and structure.",
        "source": "text",
        "concept_id": 1,
        "pedagogy_type": "text",
        "bloom_level": "understand",
        "created_at": datetime.utcnow()
    },

    # =====================
    # CONCEPT 3 – Control Flow
    # =====================
    {
        "resource_id": 201,
        "title": "Python if-else Tutorial",
        "content": "Using conditional statements in Python.",
        "source": "video",
        "url": "https://www.youtube.com/watch?v=f4KOjWS_KZs",
        "concept_id": 3,
        "pedagogy_type": "video",
        "bloom_level": "apply",
        "created_at": datetime.utcnow()
    },
    {
        "resource_id": 202,
        "title": "Loop Exercises in Python",
        "content": "Practice problems for for-loop and while-loop.",
        "source": "text",
        "concept_id": 3,
        "pedagogy_type": "quiz",
        "bloom_level": "apply",
        "created_at": datetime.utcnow()
    },

    # =====================
    # CONCEPT 5 – OOP (ADVANCED)
    # =====================
    {
        "resource_id": 301,
        "title": "Python OOP Explained",
        "content": "Classes, objects, inheritance in Python.",
        "source": "video",
        "concept_id": 5,
        "pedagogy_type": "video",
        "bloom_level": "analyze",
        "created_at": datetime.utcnow()
    },
    {
        "resource_id": 302,
        "title": "Design Patterns in Python",
        "content": "Applying OOP principles with design patterns.",
        "source": "text",
        "concept_id": 5,
        "pedagogy_type": "text",
        "bloom_level": "create",
        "created_at": datetime.utcnow()
    }
]

db.resources.insert_many(resources)

print("✅ Seed learning resources DONE")
