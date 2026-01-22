from typing import List
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi
from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import embed_text


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks


def extract_video_id(url: str) -> str:
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return url.split("/")[-1]


def import_youtube(
    youtube_url: str,
    topic: str,
    level: str = "beginner"
) -> dict:
    """
    Import video YouTube:
    - title
    - transcript
    - chunking
    - embedding
    """
    video_id = extract_video_id(youtube_url)

    yt = YouTube(youtube_url)
    title = yt.title

    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    full_text = " ".join([t["text"] for t in transcript])

    chunks = chunk_text(full_text)

    db = get_db()
    inserted = 0

    for idx, chunk in enumerate(chunks):
        embedding = embed_text(chunk)

        doc = {
            "title": title,
            "content": chunk,
            "topic": topic,
            "level": level,
            "embedding": embedding,
            "source": "youtube",
            "video_url": youtube_url,
            "chunk_index": idx + 1
        }

        db.resources.insert_one(doc)
        inserted += 1

    return {
        "video": title,
        "chunks": len(chunks),
        "inserted": inserted
    }
