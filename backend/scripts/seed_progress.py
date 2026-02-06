"""
Seed Script: Populate initial progress data for testing/demo.
"""

from datetime import datetime
from bson import ObjectId
from backend.app.database.mongo import get_db

# Test users (use real MongoDB ObjectIds)
# In a real scenario, fetch these from db.users.find()
USERS = {
    "weak": "507f1f77bcf86cd799439011",      # Example ObjectId as string
    "average": "507f1f77bcf86cd799439012",
    "strong": "507f1f77bcf86cd799439013"
}

def seed_progress():
    """Seed progress data for testing."""
    db = get_db()
    
    # Clear existing
    db.progress.delete_many({})
    
    progress_records = [
        # Weak learner: low mastery
        {
            "user_id": USERS["weak"],
            "concept_id": 1,      # Python Basics
            "mastery": 0.3,
            "confidence": 0.4,
            "total_attempts": 5,
            "successful_attempts": 1,
            "success_rate": 0.2,
            "status": "in_progress",
            "last_updated": datetime.utcnow()
        },
        {
            "user_id": USERS["weak"],
            "concept_id": 2,      # Control Flow
            "mastery": 0.2,
            "confidence": 0.3,
            "total_attempts": 3,
            "successful_attempts": 0,
            "success_rate": 0.0,
            "status": "not_started",
            "last_updated": datetime.utcnow()
        },
        
        # Average learner: moderate mastery
        {
            "user_id": USERS["average"],
            "concept_id": 1,
            "mastery": 0.65,
            "confidence": 0.7,
            "total_attempts": 8,
            "successful_attempts": 5,
            "success_rate": 0.625,
            "status": "proficient",
            "last_updated": datetime.utcnow()
        },
        {
            "user_id": USERS["average"],
            "concept_id": 2,
            "mastery": 0.55,
            "confidence": 0.6,
            "total_attempts": 6,
            "successful_attempts": 3,
            "success_rate": 0.5,
            "status": "proficient",
            "last_updated": datetime.utcnow()
        },
        {
            "user_id": USERS["average"],
            "concept_id": 3,
            "mastery": 0.4,
            "confidence": 0.45,
            "total_attempts": 4,
            "successful_attempts": 1,
            "success_rate": 0.25,
            "status": "in_progress",
            "last_updated": datetime.utcnow()
        },
        
        # Strong learner: high mastery
        {
            "user_id": USERS["strong"],
            "concept_id": 1,
            "mastery": 0.95,
            "confidence": 0.9,
            "total_attempts": 12,
            "successful_attempts": 11,
            "success_rate": 0.917,
            "status": "complete",
            "last_updated": datetime.utcnow()
        },
        {
            "user_id": USERS["strong"],
            "concept_id": 2,
            "mastery": 0.85,
            "confidence": 0.88,
            "total_attempts": 10,
            "successful_attempts": 8,
            "success_rate": 0.8,
            "status": "complete",
            "last_updated": datetime.utcnow()
        },
        {
            "user_id": USERS["strong"],
            "concept_id": 3,
            "mastery": 0.75,
            "confidence": 0.78,
            "total_attempts": 7,
            "successful_attempts": 5,
            "success_rate": 0.714,
            "status": "proficient",
            "last_updated": datetime.utcnow()
        }
    ]
    
    result = db.progress.insert_many(progress_records)
    
    print(f"✅ Seeded {len(result.inserted_ids)} progress records")
    print(f"  Users: {list(USERS.keys())}")
    print(f"  Progress range: weak → strong learners")

if __name__ == "__main__":
    seed_progress()