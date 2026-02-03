"""
Search Service
--------------
Tầng trung gian cho các chức năng tìm kiếm học liệu.
Không tự xử lý embedding – chỉ điều phối logic.
"""

from typing import List, Dict
from backend.app.services.embedding_service import semantic_search


def search_learning_resources(
    query: str,
    limit: int = 5,
    min_score: float = 0.75
) -> List[Dict]:
    """
    Tìm kiếm học liệu theo ngữ nghĩa (Semantic Search).

    Args:
        query (str): câu truy vấn của người học
        limit (int): số kết quả trả về
        min_score (float): ngưỡng similarity

    Returns:
        List[Dict]: danh sách học liệu liên quan
    """

    return semantic_search(
        query=query,
        k=limit,
        min_score=min_score
    )
