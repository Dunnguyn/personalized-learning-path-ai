from typing import List
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi
from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import embed_text


def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return url.rstrip("/").split("/")[-1]


def chunk_text(text: str, chunk_size=500, overlap=50) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def import_youtube(
    youtube_url: str,
    topic: str,
    level: str = "beginner",
    concept_id: int | None = None
) -> dict:

    db = get_db()
    video_id = extract_video_id(youtube_url)

    # =========================
    # 1. TITLE (SAFE)
    # =========================
    try:
        yt = YouTube(youtube_url)
        title = yt.title
    except Exception:
        title = f"YouTube Video ({video_id})"

    # =========================
    # 2. TRANSCRIPT (SAFE MODE)
    # =========================
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        full_text = " ".join([t["text"] for t in transcript])
        has_transcript = True
    except Exception as e:
        # ⚠️ KHÔNG CRASH
        print(f"⚠️ Transcript unavailable for {video_id}: {e}")

        # Lưu metadata video để sau này xử lý
        db.resources.insert_one({
            "title": title,
            "topic": topic,
            "level": level,
            "concept_id": concept_id,
            "source": "youtube",
            "video_url": youtube_url,
            "video_id": video_id,
            "has_transcript": False
        })

        return {
            "video_id": video_id,
            "title": title,
            "inserted_chunks": 0,
            "has_transcript": False,
            "message": "Video saved, transcript unavailable"
        }

    # =========================
    # 3. CHUNK + EMBEDDING
    # =========================
    chunks = chunk_text(full_text)
    inserted = 0

    for idx, chunk in enumerate(chunks):
        db.resources.insert_one({
            "title": title,
            "content": chunk,
            "topic": topic,
            "level": level,
            "concept_id": concept_id,
            "embedding": embed_text(chunk),
            "source": "youtube",
            "video_url": youtube_url,
            "video_id": video_id,
            "chunk_index": idx + 1,
            "has_transcript": True
        })
        inserted += 1

    return {
        "video_id": video_id,
        "title": title,
        "total_chunks": len(chunks),
        "inserted_chunks": inserted,
        "has_transcript": True,
        "concept_id": concept_id
    }
