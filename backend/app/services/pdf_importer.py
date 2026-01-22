from typing import List
from pypdf import PdfReader
from backend.app.services.embedding_service import store_resource


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    Chia văn bản thành các đoạn nhỏ (chunking) có overlap
    """
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks


def import_pdf(
    file_path: str,
    topic: str,
    level: str = "beginner"
) -> dict:
    """
    Import PDF vào hệ thống RAG:
    1. Đọc file PDF
    2. Chunking văn bản
    3. Lọc chunk theo keyword của topic
    4. Gắn ngữ cảnh học tập
    5. Tạo embedding & lưu MongoDB
    """

    # ===== 1. Read PDF =====
    reader = PdfReader(file_path)
    full_text = ""

    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    # ===== 2. Chunking =====
    chunks = chunk_text(full_text)

    # ===== 3. Keyword filter (giảm nhiễu ngữ nghĩa) =====
    topic_lower = topic.lower()

    # Keyword mẫu – có thể mở rộng theo môn học
    keywords = [
        "list", "lists", "append", "pop",
        "index", "slice", "mutable", "sequence"
    ]

    inserted = 0

    # ===== 4. Process each chunk =====
    for idx, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()

        # Bỏ chunk không liên quan
        if not any(k in chunk_lower for k in keywords):
            continue

        # ===== 5. Context injection =====
        contextual_content = (
            f"This text is about {topic} for {level} learners. "
            f"{chunk}"
        )

        store_resource(
            title=f"{file_path} - chunk {idx + 1}",
            content=contextual_content,
            topic=topic,
            level=level,
            source="pdf"
        )

        inserted += 1

    # ===== 6. Return result =====
    return {
        "file": file_path,
        "total_chunks": len(chunks),
        "inserted_chunks": inserted
    }
