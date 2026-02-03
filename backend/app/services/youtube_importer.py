from typing import List
from pytube import YouTube
from youtube_transcript_api import YouTubeTranscriptApi

from backend.app.services.embedding_service import store_resource


# =========================
# CHUNKING
# =========================
def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    Chia transcript thành các đoạn nhỏ có overlap
    """
    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap

    return chunks


# =========================
# VIDEO ID
# =========================
def extract_video_id(url: str) -> str:
    """
    Trích video_id từ URL YouTube
    """
    if "v=" in url:
        return url.split("v=")[-1].split("&")[0]
    return url.split("/")[-1]


# =========================
# IMPORT YOUTUBE
# =========================
def import_youtube(
    youtube_url: str,
    topic: str,
    level: str = "beginner"
) -> dict:
    """
    Import học liệu từ YouTube vào hệ thống RAG:

    Steps:
    1. Lấy title video
    2. Lấy transcript
    3. Chunking
    4. Inject learning context
    5. Store resource + embedding
    """

    # 1. Extract video info
    video_id = extract_video_id(youtube_url)
    yt = YouTube(youtube_url)
    title = yt.title

    # 2. Get transcript
    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    full_text = " ".join([t["text"] for t in transcript])

    # 3. Chunking
    chunks = chunk_text(full_text)

    inserted = 0

    # 4. Process chunks
    for idx, chunk in enumerate(chunks):
        if len(chunk.strip()) < 100:
            continue  # bỏ chunk quá ngắn → giảm nhiễu

        contextual_content = (
            f"This transcript is from a YouTube video about {topic} "
            f"for {level} learners.\n\n{chunk}"
        )

        store_resource(
            title=f"{title} - chunk {idx + 1}",
            content=contextual_content,
            topic=topic,
            level=level,
            source="youtube"
        )

        inserted += 1

    # 5. Result
    return {
        "video_title": title,
        "total_chunks": len(chunks),
        "inserted_chunks": inserted
    }
