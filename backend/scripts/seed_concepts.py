from backend.app.database.mongo import db

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
        "course": "Python Backend",
        "concept_name": "Python Basics",
        "topic": "python",
        "difficulty": 1,
        "weight": 1.0
    },
    {
        "concept_id": 2,
        "course": "Python Backend",
        "concept_name": "Control Flow",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.1
    },
    {
        "concept_id": 3,
        "course": "Python Backend",
        "concept_name": "Functions",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.1
    },
    {
        "concept_id": 4,
        "course": "Python Backend",
        "concept_name": "OOP",
        "topic": "python",
        "difficulty": 3,
        "weight": 1.2
    },
    {
        "concept_id": 5,
        "course": "Python Backend",
        "concept_name": "Virtual Environment",
        "topic": "python",
        "difficulty": 2,
        "weight": 1.0
    },
    {
        "concept_id": 6,
        "course": "Python Backend",
        "concept_name": "FastAPI Fundamentals",
        "topic": "fastapi",
        "difficulty": 3,
        "weight": 1.3
    },
    {
        "concept_id": 7,
        "course": "Python Backend",
        "concept_name": "Request & Response Validation",
        "topic": "fastapi",
        "difficulty": 3,
        "weight": 1.2
    },
    {
        "concept_id": 8,
        "course": "Python Backend",
        "concept_name": "Authentication (JWT)",
        "topic": "fastapi",
        "difficulty": 4,
        "weight": 1.4
    },
    {
        "concept_id": 9,
        "course": "Python Backend",
        "concept_name": "MongoDB Basics",
        "topic": "database",
        "difficulty": 3,
        "weight": 1.2
    },
    {
        "concept_id": 10,
        "course": "Python Backend",
        "concept_name": "Async & Background Tasks",
        "topic": "fastapi",
        "difficulty": 4,
        "weight": 1.4
    }
]

db.concepts.insert_many(concepts)
print(f"✅ Inserted {len(concepts)} concepts")

# ===============================
# 3. DEFINE PREREQUISITES
# ===============================
prerequisites = [
    # Control Flow <- Python Basics
    {"from_concept_id": 1, "to_concept_id": 2},

    # Functions <- Control Flow
    {"from_concept_id": 2, "to_concept_id": 3},

    # OOP <- Functions
    {"from_concept_id": 3, "to_concept_id": 4},

    # FastAPI <- Python Basics
    {"from_concept_id": 1, "to_concept_id": 6},

    # Request/Response <- FastAPI
    {"from_concept_id": 6, "to_concept_id": 7},

    # JWT <- Request/Response
    {"from_concept_id": 7, "to_concept_id": 8},

    # MongoDB <- Python Basics
    {"from_concept_id": 1, "to_concept_id": 9},

    # Async <- FastAPI
    {"from_concept_id": 6, "to_concept_id": 10}
]

db.prerequisites.insert_many(prerequisites)
print(f"🔗 Inserted {len(prerequisites)} prerequisites")

print("🎉 SEED COMPLETED SUCCESSFULLY")
