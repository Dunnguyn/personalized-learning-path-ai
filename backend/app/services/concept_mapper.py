from backend.app.database.mongo import get_db


def resolve_concept_id(topic: str) -> int | None:
    """
    Tự động map topic → concept_id
    """
    db = get_db()
    topic_lower = topic.lower()

    concepts = list(db.concepts.find({}, {"_id": 0}))

    if not concepts:
        return None

    # 1️⃣ Match theo concept.topic
    for c in concepts:
        if c.get("topic") and c["topic"].lower() in topic_lower:
            return c["concept_id"]

    # 2️⃣ Match theo concept_name
    for c in concepts:
        if c["concept_name"].lower() in topic_lower:
            return c["concept_id"]

    # 3️⃣ Fallback: concept dễ nhất
    concepts.sort(key=lambda x: x.get("difficulty", 99))
    return concepts[0]["concept_id"]
