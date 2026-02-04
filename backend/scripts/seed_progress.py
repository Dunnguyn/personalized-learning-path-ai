import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.mongo import db
from datetime import datetime

# ===============================
# 1. CLEAR OLD PROGRESS (OPTIONAL)
# ===============================
db.progress.delete_many({})

print("🧹 Cleared progress data")

# ===============================
# 2. DEFINE USERS (DEMO)
# ===============================
USERS = {
    "weak": 101,        # học yếu
    "average": 102,     # học trung bình
    "strong": 103       # học tốt
}

# ===============================
# 3. SEED PROGRESS DATA
# ===============================
progress_records = [

    # =================================================
    # USER 101 – HỌC YẾU
    # =================================================
    {
        "user_id": USERS["weak"],
        "concept_id": 1,      # Python Basics
        "mastery": 0.35,
        "confidence": 0.3,
        "total_attempts": 3,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["weak"],
        "concept_id": 2,      # Control Flow
        "mastery": 0.2,
        "confidence": 0.25,
        "total_attempts": 2,
        "successful_attempts": 0,
        "last_updated": datetime.utcnow()
    },

    # =================================================
    # USER 102 – HỌC TRUNG BÌNH
    # =================================================
    {
        "user_id": USERS["average"],
        "concept_id": 1,
        "mastery": 0.75,
        "confidence": 0.7,
        "total_attempts": 2,
        "successful_attempts": 2,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["average"],
        "concept_id": 2,
        "mastery": 0.6,
        "confidence": 0.55,
        "total_attempts": 2,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["average"],
        "concept_id": 3,
        "mastery": 0.4,
        "confidence": 0.45,
        "total_attempts": 1,
        "successful_attempts": 0,
        "last_updated": datetime.utcnow()
    },

    # =================================================
    # USER 103 – HỌC GIỎI
    # =================================================
    {
        "user_id": USERS["strong"],
        "concept_id": 1,
        "mastery": 0.95,
        "confidence": 0.9,
        "total_attempts": 1,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["strong"],
        "concept_id": 2,
        "mastery": 0.9,
        "confidence": 0.85,
        "total_attempts": 1,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["strong"],
        "concept_id": 3,
        "mastery": 0.85,
        "confidence": 0.8,
        "total_attempts": 1,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    },
    {
        "user_id": USERS["strong"],
        "concept_id": 4,
        "mastery": 0.7,
        "confidence": 0.75,
        "total_attempts": 1,
        "successful_attempts": 1,
        "last_updated": datetime.utcnow()
    }
]

db.progress.insert_many(progress_records)

print(f"✅ Inserted {len(progress_records)} progress records")
print("🎉 SEED PROGRESS COMPLETED SUCCESSFULLY")
