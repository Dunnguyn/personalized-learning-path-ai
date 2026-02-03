import os
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)


def score_confidence(
    question: str,
    answer: str
) -> float:
    """
    Dùng Gemini để chấm confidence [0.0 - 1.0]
    """

    prompt = f"""
You are an AI tutor.

Given:
Question:
{question}

Student Answer:
{answer}

Rate how confident and correct the answer is.

Return ONLY a number between 0.0 and 1.0.
No explanation.
"""

    try:
        response = client.models.generate_content(
            model="models/gemini-2.0-flash",
            contents=prompt
        )

        score = float(response.text.strip())
        return max(0.0, min(score, 1.0))

    except Exception:
        # fallback an toàn
        return 0.5
