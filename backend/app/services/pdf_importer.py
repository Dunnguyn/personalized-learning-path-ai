from typing import List, Dict
from pypdf import PdfReader
from backend.app.services.embedding_service import store_resource


# ==================================================
# TEXT CHUNKING
# ==================================================
def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    Split text into overlapping chunks for RAG.
    """
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap

    return chunks


# ==================================================
# PDF IMPORT PIPELINE
# ==================================================
def import_pdf(
    file_path: str,
    topic: str,
    level: str = "beginner"
) -> Dict:
    """
    Import PDF into RAG system:
    1. Read PDF
    2. Chunk text
    3. Filter noisy chunks
    4. Inject learning context
    5. Store embeddings
    """

    # ---------- 1. Read PDF ----------
    try:
        reader = PdfReader(file_path)
    except Exception as e:
        return {
            "error": "Failed to read PDF",
            "detail": str(e)
        }

    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"

    if not full_text.strip():
        return {
            "file": file_path,
            "error": "PDF contains no readable text"
        }

    # ---------- 2. Chunking ----------
    chunks = chunk_text(full_text)

    # ---------- 3. Topic-based filtering ----------
    keywords = _get_topic_keywords(topic)

    inserted = 0

    # ---------- 4. Process chunks ----------
    for idx, chunk in enumerate(chunks):
        if not _is_relevant_chunk(chunk, keywords):
            continue

        contextual_content = _inject_context(
            chunk=chunk,
            topic=topic,
            level=level
        )

        store_resource(
            title=f"{file_path} | chunk {idx + 1}",
            content=contextual_content,
            topic=topic,
            level=level,
            source="pdf"
        )

        inserted += 1

    # ---------- 5. Result ----------
    return {
        "file": file_path,
        "total_chunks": len(chunks),
        "inserted_chunks": inserted,
        "skipped_chunks": len(chunks) - inserted
    }


# ==================================================
# HELPERS
# ==================================================
def _get_topic_keywords(topic: str) -> List[str]:
    """
    Return keywords for filtering chunks based on topic.
    """
    topic = topic.lower()

    if "python" in topic:
        return [
            "list", "dict", "tuple", "set",
            "loop", "function", "class",
            "append", "pop", "index"
        ]

    if "fastapi" in topic:
        return [
            "fastapi", "endpoint", "router",
            "request", "response", "async"
        ]

    # Fallback: accept everything
    return []


def _is_relevant_chunk(
    chunk: str,
    keywords: List[str]
) -> bool:
    if not keywords:
        return True

    chunk_lower = chunk.lower()
    return any(k in chunk_lower for k in keywords)


def _inject_context(
    chunk: str,
    topic: str,
    level: str
) -> str:
    """
    Add learning context to reduce hallucination.
    """
    return (
        f"This content is part of learning materials about {topic}. "
        f"It is intended for {level} learners.\n\n"
        f"{chunk}"
    )
