import os
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)


def summarize_youtube_video(
    video_title: str,
    topic: str,
    level: str
) -> str:
    """
    Dùng Gemini tạo pseudo-transcript cho video YouTube
    """

    prompt = f"""
You are an AI tutor.

A learner is studying: {topic}
Level: {level}

The YouTube video title is:
"{video_title}"

The video has NO transcript.

Based on the title and common knowledge,
generate a detailed learning-oriented summary
as if it were the transcript of the video.

Rules:
- Explain clearly for {level} learners
- Use bullet points
- Include definitions, examples if possible
- DO NOT hallucinate advanced topics
"""

    response = client.models.generate_content(
        model="models/gemini-2.0-flash",
        contents=prompt
    )

    return response.text.strip()
