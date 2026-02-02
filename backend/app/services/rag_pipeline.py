from typing import List, Dict
import os

from backend.app.services.embedding_service import semantic_search

# =========================
# Gemini LLM (SDK mới)
# =========================
USE_LLM = True
client = None

# Chọn model xịn nhất + fallback
PRIMARY_MODEL = "models/gemini-flash-latest"
FALLBACK_MODEL = None   # hoặc trả text fallback

try:
    from google import genai

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=GEMINI_API_KEY)

except Exception as e:
    print("❌ Gemini init error:", e)
    USE_LLM = False
    client = None


class RAGPipeline:
    """
    Retrieval-Augmented Generation (QA-RAG)
    Trả lời câu hỏi dựa trên học liệu đã index (PDF, text, video transcript, ...)
    """

    # =========================
    # 1. RETRIEVE
    # =========================
    def retrieve_context(self, query: str, k: int = 5) -> List[Dict]:
        """
        Semantic search học liệu liên quan
        """
        return semantic_search(query, k=k)

    # =========================
    # 2. BUILD CONTEXT
    # =========================
    def build_context(self, resources: List[Dict]) -> str:
        """
        Ghép các chunk học liệu thành context cho LLM
        """
        if not resources:
            return "No learning materials found."

        blocks = []
        for r in resources:
            blocks.append(
                f"[Source: {r.get('title', 'unknown')}]\n"
                f"{r.get('content', '')[:500]}"
            )

        return "\n\n".join(blocks)

    # =========================
    # 3. BUILD PROMPT
    # =========================
    def build_prompt(self, question: str, context: str) -> str:
        """
        Prompt QA-RAG (giảm hallucination)
        """
        return f"""
You are an AI tutor for beginner learners.

Use ONLY the learning materials below to answer the question.
If the answer is NOT contained in the materials, say:
"I cannot find the answer in the provided learning materials."

Learning materials:
--------------------
{context}
--------------------

Question:
{question}

Answer clearly, simply, and suitable for beginners.
"""

    # =========================
    # 4. GENERATE (Gemini)
    # =========================
    def generate(self, prompt: str) -> str:
        """
        Gọi Gemini sinh câu trả lời
        Ưu tiên Pro → fallback Flash
        """
        if not (USE_LLM and client):
            return "LLM is unavailable. Cannot generate answer at this time."

        # ---- 1. Try PRIMARY MODEL ----
        try:
            response = client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=prompt
            )
            return response.text.strip()

        except Exception as e:
            print(f"⚠️ Gemini PRIMARY model error ({PRIMARY_MODEL}):", e)

        # ---- 2. Fallback MODEL ----
        try:
            response = client.models.generate_content(
                model=FALLBACK_MODEL,
                contents=prompt
            )
            return response.text.strip()

        except Exception as e:
            print(f"❌ Gemini FALLBACK model error ({FALLBACK_MODEL}):", e)

        return "LLM is unavailable. Cannot generate answer at this time."

    # =========================
    # 5. RUN PIPELINE
    # =========================
    def run(
        self,
        question: str,
        goal: str,
        level: str,
        completed: List[str]
    ) -> Dict:
        """
        Chạy toàn bộ QA-RAG pipeline
        """

        # 1. Retrieve
        resources = self.retrieve_context(question)

        # 2. Build context
        context = self.build_context(resources)

        # 3. Build prompt
        prompt = self.build_prompt(question, context)

        # 4. Generate answer
        answer_text = self.generate(prompt)

        # 5. Structured response
        return {
            "question": question,
            "answer": answer_text,
            "sources": [
                {
                    "title": r.get("title"),
                    "score": r.get("score"),
                    "source": r.get("source", "unknown")
                }
                for r in resources
            ]
        }
