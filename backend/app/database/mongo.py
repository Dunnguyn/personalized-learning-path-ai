import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

# Preserve injected environment values; dotenv files only fill missing values.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")

if not os.getenv("MONGODB_URI") and os.getenv("MONGO_URI"):
    os.environ["MONGODB_URI"] = os.getenv("MONGO_URI")
if not os.getenv("MONGO_URI") and os.getenv("MONGODB_URI"):
    os.environ["MONGO_URI"] = os.getenv("MONGODB_URI")

MONGO_URI = os.getenv("MONGODB_URI") or os.getenv(
    "MONGO_URI", "mongodb://localhost:27017/personalized_learning_path"
)
DB_NAME = os.getenv("DB_NAME") or "personalized_learning_path"

if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGODB_URI hoặc MONGO_URI")

logger.info(
    f"Connecting to MongoDB: {MONGO_URI.split('@')[-1] if '@' in MONGO_URI else MONGO_URI}"
)
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
logger.info(f"Connected to database: {DB_NAME}")


def get_db():
    logger.debug(f"get_db() called, returning database: {DB_NAME}")
    return db
