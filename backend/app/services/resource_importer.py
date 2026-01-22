from typing import List, Dict
from backend.app.services.embedding_service import embed_text
from backend.app.database.mongo import get_db


def import_resources(resources: List[Dict]) -> Dict:
    """
    Import danh sách học liệu vào hệ thống.
    Mỗi resource gồm: title, content, topic, level, url (optional)
    """
    db = get_db()
    inserted = 0

    for r in resources:
        content = r.get("content", "")
        if not content.strip():
            continue

        embedding = embed_text(content)

        doc = {
            "title": r.get("title"),
            "content": content,
            "topic": r.get("topic"),
            "level": r.get("level", "beginner"),
            "url": r.get("url"),
            "embedding": embedding
        }

        db.resources.insert_one(doc)
        inserted += 1

    return {
        "status": "success",
        "inserted": inserted
    }
