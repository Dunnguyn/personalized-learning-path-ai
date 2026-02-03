from typing import List, Optional
from pytube import YouTube
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
)
from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import embed_text
from backend.app.services.concept_mapper import resolve_concept_id


# =========================
# UTILS
# =========================
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap

    return chunks


def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return url.rstrip("/").split("/")[-1]


# =========================
# MAIN IMPORT
# =========================
def import_youtube(
    youtube_url: str,
    topic: str,
    level: str = "beginner",
    concept_id: Optional[int] = None,   # 🔥 AUTO MAP
):
    db = get_db()
    video_id = extract_video_id(youtube_url)

    # ===== 0. Resolve concept_id nếu chưa có =====
    if concept_id is None:
        concept_id = resolve_concept_id(topic)

    # ===== 1. Lấy title (AN TOÀN – không crash) =====
    try:
        yt = YouTube(youtube_url)
        title = yt.title
    except Exception as e:
        print("⚠️ pytube title fetch failed:", e)
        title = f"YouTube Video ({video_id})"

    # ===== 2. Lấy transcript (KHÔNG ĐƯỢC throw 500) =====
    full_text = ""
    has_transcript = False

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join(t["text"] for t in transcript)
        has_transcript = True
    except (TranscriptsDisabled, NoTranscriptFound):
        pass
    except Exception as e:
        print("⚠️ Transcript error:", e)

    # ===== 3. Nếu KHÔNG có transcript → chỉ lưu metadata =====
    if not full_text.strip():
        db.resources.insert_one({
            "title": title,
            "topic": topic,
            "concept_id": concept_id,
            "level": level,
            "source": "youtube",
            "video_url": youtube_url,
            "has_transcript": False,
        })

        return {
            "video_id": video_id,
            "title": title,
            "concept_id": concept_id,
            "inserted_chunks": 0,
            "has_transcript": False,
            "message": "Video saved, transcript unavailable",
        }

    # ===== 4. Chunk + embedding =====
    chunks = chunk_text(full_text)
    inserted = 0

    for idx, chunk in enumerate(chunks):
        embedding = embed_text(chunk)

        db.resources.insert_one({
            "title": title,
            "content": chunk,
            "topic": topic,
            "concept_id": concept_id,
            "level": level,
            "embedding": embedding,
            "source": "youtube",
            "video_url": youtube_url,
            "chunk_index": idx + 1,
        })

        inserted += 1

    return {
        "video_id": video_id,
        "title": title,
        "concept_id": concept_id,
        "inserted_chunks": inserted,
        "has_transcript": True,
    }
