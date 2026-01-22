import os
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

if not MONGO_URI or not DB_NAME:
    raise RuntimeError("Thiếu biến môi trường MONGO_URI hoặc DB_NAME")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

def get_db():
    return db
