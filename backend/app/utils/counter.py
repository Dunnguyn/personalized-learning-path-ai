from pymongo import ReturnDocument
from backend.app.database.mongo import db


def get_next_sequence(name: str) -> int:
    """
    Sinh ID tự tăng cho các entity (user_id, course_id, concept_id, ...)

    Cơ chế:
    - Lưu counter trong collection `counters`
    - Mỗi document có dạng:
        {
            _id: "user_id",
            seq: 1
        }
    """

    counter = db.counters.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )

    return counter["seq"]


# =========================
# USER ID
# =========================
def get_next_user_id() -> int:
    return get_next_sequence("user_id")
