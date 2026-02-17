import os
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI", "mongodb://localhost:27017/personalized_learning_path")
DB_NAME = os.getenv("DB_NAME") or "personalized_learning_path"

if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGODB_URI hoặc MONGO_URI")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

def get_db():
    return db
