from google import genai
import os

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

print("Checking available models...\n")

try:
    models = client.models.list()
    for m in models:
        print(
            f"- {m.name:30} | "
            f"generate={getattr(m, 'supportsGenerateContent', None)} | "
            f"embed={getattr(m, 'supportsEmbedding', None)}"
        )
except Exception as e:
    print("Error listing models:", e)
