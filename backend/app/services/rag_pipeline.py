from typing import List, Dict
import os

from backend.app.services.embedding_service import semantic_search

# =========================
# Gemini LLM (NEW SDK)
# =========================
USE_LLM = True
client = None

# Ưu tiên model ổn định + ít bị khóa
PRIMARY_MODEL = "models/gemini-2.0-flash"
FALLBACK_MODEL = None   # fallback = trả lời không dùng LLM

MAX_CONTEXT_CHARS = 2000  # chống vượt quota


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

    Pipeline:
        Query → Retrieve → Context → Prompt → Gemini → Answer
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
        Có giới hạn độ dài để tránh vượt quota
        """
        if not resources:
            return "No learning materials found."

        blocks = []
        total_chars = 0

        for r in resources:
            block = (
                f"[Source: {r.get('title', 'unknown')}]\n"
                f"{r.get('content', '')[:500]}"
            )

            total_chars += len(block)
            if total_chars > MAX_CONTEXT_CHARS:
                break

            blocks.append(block)

        return "\n\n".join(blocks)

    # =========================
    # 3. BUILD PROMPT
    # =========================
    def build_prompt(self, question: str, context: str) -> str:
        """
        Prompt QA-RAG (ép LLM không hallucinate)
        """
        return f"""
You are an AI tutor for beginner learners.

RULES:
- Use ONLY the learning materials below.
- Do NOT use outside knowledge.
- If the answer is not found, say exactly:
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
        Có fallback an toàn khi hết quota
        """
        if not (USE_LLM and client):
            return "LLM is unavailable. Cannot generate answer at this time."

        # ---- Try PRIMARY MODEL ----
        try:
            response = client.models.generate_content(
                model=PRIMARY_MODEL,
                contents=prompt
            )
            return response.text.strip()

        except Exception as e:
            print(f"⚠️ Gemini PRIMARY error ({PRIMARY_MODEL}):", e)

        # ---- Fallback: no-LLM answer ----
        return "LLM is temporarily unavailable due to quota limits."

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

        # 1. Retrieve learning materials
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
