import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI", "mongodb://localhost:27017/personalized_learning_path")
DB_NAME = os.getenv("DB_NAME") or "personalized_learning_path"

if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGODB_URI hoặc MONGO_URI")

logger.info(f"Connecting to MongoDB: {MONGO_URI.split('@')[-1] if '@' in MONGO_URI else MONGO_URI}")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
logger.info(f"Connected to database: {DB_NAME}")

def get_db():
    logger.debug(f"get_db() called, returning database: {DB_NAME}")
    return db
