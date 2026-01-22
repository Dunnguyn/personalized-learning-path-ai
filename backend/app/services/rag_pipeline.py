from typing import List, Dict
from backend.app.services.embedding_service import semantic_search
import os
import json

# ===== Optional LLM =====
USE_LLM = True
try:
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
except Exception:
    USE_LLM = False
    client = None


class RAGPipeline:
    """
    Retrieval-Augmented Generation (QA-RAG)
    Trả lời câu hỏi dựa trên học liệu (PDF, YouTube, v.v.)
    """

    # ===== 1. RETRIEVE =====
    def retrieve_context(self, query: str, k: int = 5) -> List[Dict]:
        """
        Semantic search học liệu liên quan
        """
        return semantic_search(query, k=k)

    # ===== 2. BUILD CONTEXT =====
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
                f"{r.get('content', '')[:400]}"
            )

        return "\n\n".join(blocks)

    # ===== 3. PROMPT =====
    def build_prompt(self, question: str, context: str) -> str:
        """
        Prompt QA-RAG: bắt buộc dùng context
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

Answer clearly, simply, and suitable for a beginner.
"""

    # ===== 4. GENERATE =====
    def generate(self, prompt: str) -> str:
        """
        Gọi LLM sinh câu trả lời
        """
        if USE_LLM and client:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You answer questions based on provided materials only."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.2
                )

                return response.choices[0].message.content.strip()

            except Exception as e:
                print("LLM error:", e)

        # ===== Fallback =====
        return "LLM is unavailable. Cannot generate answer at this time."

    # ===== 5. PIPELINE RUN =====
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

        # 1. Retrieve relevant materials
        resources = self.retrieve_context(question)

        # 2. Build context
        context = self.build_context(resources)

        # 3. Build prompt
        prompt = self.build_prompt(question, context)

        # 4. Generate answer
        answer_text = self.generate(prompt)

        # 5. Return structured response
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
