from typing import List, Dict
from backend.app.services.embedding_service import embed_text
from backend.app.database.mongo import get_db


def import_resources(resources: List[Dict]) -> Dict:
    """
    Import danh sách học liệu vào hệ thống RAG.

    Mỗi resource cần:
        - title (str)
        - content (str)
        - topic (str)
        - level (optional, default=beginner)
        - source (pdf / youtube / web / manual)
        - url (optional)

    Returns:
        {
            status: "success",
            inserted: int,
            skipped: int
        }
    """

    db = get_db()
    inserted = 0
    skipped = 0

    for r in resources:
        # ===== 1. Validate bắt buộc =====
        title = r.get("title")
        content = r.get("content")
        topic = r.get("topic")

        if not title or not content or not topic:
            skipped += 1
            continue

        content = content.strip()
        if not content:
            skipped += 1
            continue

        # ===== 2. Embedding =====
        embedding = embed_text(content)

        # ===== 3. Chuẩn hóa document =====
        doc = {
            "title": title,
            "content": content,
            "topic": topic,
            "level": r.get("level", "beginner"),
            "source": r.get("source", "manual"),
            "url": r.get("url"),
            "embedding": embedding
        }

        # ===== 4. Lưu MongoDB =====
        db.resources.insert_one(doc)
        inserted += 1

    return {
        "status": "success",
        "inserted": inserted,
        "skipped": skipped
    }
