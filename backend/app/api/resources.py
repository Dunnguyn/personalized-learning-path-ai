from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
import numpy as np

from app.database.mongo import get_db
from app.services.embedding_service import get_embedding
from app.services.search_service import cosine_similarity

router = APIRouter(prefix="/resources", tags=["Resources"])

db = get_db()
resources_col = db["resources"]


class ResourceRequest(BaseModel):
    title: str
    content: str


class SearchRequest(BaseModel):
    query: str


@router.post("/add")
def add_resource(data: ResourceRequest):
    embedding = get_embedding(data.content)

    resources_col.insert_one({
        "title": data.title,
        "content": data.content,
        "embedding": embedding,
        "created_at": datetime.now()
    })

    return {"message": "Đã thêm học liệu"}


@router.post("/search")
def search_resources(data: SearchRequest):
    query_embedding = get_embedding(data.query)

    results = []
    for r in resources_col.find():
        score = cosine_similarity(
            query_embedding,
            np.array(r["embedding"])
        )
        results.append({
            "title": r["title"],
            "content": r["content"],
            "score": float(score)
        })

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    return results[:3]
