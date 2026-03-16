# Personalized Learning Path AI

He thong ho tro hoc tap ca nhan hoa duoc xay dung voi `FastAPI + MongoDB + React + AI/RAG`.

Muc tieu cua du an:
- tra loi cau hoi hoc tap theo ngu canh tai lieu
- sinh lo trinh hoc tap phu hop voi muc tieu va trinh do
- goi y hoc lieu lien quan cho tung concept
- theo doi mastery, confidence, va tien do hoc tap
- tao question bank va quiz theo bai hoc

## Tong quan kien truc

```text
frontend (React + TypeScript + Vite)
    |
    | HTTP/REST
    v
backend (FastAPI)
    |
    +-- api
    +-- services
    +-- database
    |
    v
MongoDB
```

## Cau truc backend hien tai

Backend da duoc sap xep lai theo tung package chuc nang:

```text
backend/app/services/
├── ai_tutor/
│   ├── rag.py
│   └── service.py
├── learning_path/
│   ├── recommender.py
│   └── service.py
├── lesson_quiz/
│   └── bank_service.py
├── progress_tracking/
│   ├── confidence.py
│   ├── confidence_scorer.py
│   └── progress.py
├── question_generation/
│   ├── bloom.py
│   ├── generator.py
│   ├── lesson_content.py
│   ├── llm_generator.py
│   ├── pipeline.py
│   ├── prompt_builder.py
│   ├── rules.py
│   ├── templates.py
│   └── validator.py
├── resource_imports/
│   ├── batch.py
│   ├── pdf.py
│   ├── youtube.py
│   └── youtube_summary.py
├── adaptive_engine.py
├── concept_mapper.py
├── embedding_service.py
├── resource_service.py
└── search_service.py
```

## Y nghia tung package

### `ai_tutor`
- xu ly hoi dap AI
- chay RAG retrieval + answer generation
- dieu phoi confidence, progress, adaptive learning, learning path

### `learning_path`
- sinh lo trinh hoc tap
- tao curriculum theo goal/level
- goi y hoc lieu cho concept trong learning path

### `lesson_quiz`
- tao question bank cho lesson
- tao quiz attempt
- cham diem va luu ket qua quiz

### `progress_tracking`
- cap nhat mastery theo progress
- tinh va luu confidence
- tong hop overview confidence/progress cho user

### `question_generation`
- sinh cau hoi rule-based
- sinh cau hoi lesson-grounded bang LLM
- prompt, validation, retrieval chunk, template, Bloom taxonomy

### `resource_imports`
- import hoc lieu thu cong theo lo
- import PDF
- import YouTube
- tao tom tat YouTube fallback

## API chinh

Tat ca router duoc mount duoi prefix `/api`.

### Auth
- `POST /api/auth/signup`
- `POST /api/auth/login`

### Ask / AI Tutor
- `POST /api/ask/`
- `GET /api/ask/adaptive-status`
- `POST /api/ask/detect-concepts`
- `GET /api/ask/recommend-concepts`
- `GET /api/ask/history`
- `DELETE /api/ask/history/{history_id}`
- `POST /api/ask/generate-assessment`

### Learning Path
- `POST /api/learning-path/generate`
- `GET /api/learning-path/history`
- `POST /api/learning-path/lesson-progress`
- `GET /api/learning-path/{path_id}`

### Lesson Quiz
- `GET /api/lesson-question-banks`
- `GET /api/lesson-question-bank/{lesson_id}`
- `POST /api/lesson-question-bank/generate`
- `GET /api/lesson-question-bank/debug/{lesson_id}`
- `POST /api/lesson-quiz/attempt`
- `POST /api/lesson-quiz/submit`
- `POST /api/quiz/submit`

### Progress
- `POST /api/progress/update`
- `GET /api/progress/summary`
- `GET /api/progress/overview`
- `GET /api/progress/confidence`
- `GET /api/progress/confidence/{lesson_id}`
- `GET /api/progress/attempt-confidence/{attempt_id}`
- `GET /api/progress/overview/{user_id}`

### Resources
- `GET /api/resources/`
- `POST /api/resources/`
- `POST /api/resources/import`
- `GET /api/resources/search`
- `POST /api/resources/import-pdf`
- `POST /api/resources/import-youtube`
- `GET /api/resources/pdf/{resource_id}`

### Recommendations
- `GET /api/recommendations/resources`
- `GET /api/recommendations/progress`

### Concepts
- `GET /api/concepts`
- `GET /api/concepts/{concept_id}`

### RAG Utilities
- `POST /api/rag/upload-pdf`
- `POST /api/rag/chat`

## Frontend

Frontend dung:
- React 18
- TypeScript
- Vite
- React Router
- Axios

Scripts chinh trong `frontend/package.json`:

```bash
npm run dev
npm run build
npm run type-check
npm run lint
```

## Cai dat va chay local

### Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Swagger docs:

```text
http://localhost:8000/api/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend mac dinh:

```text
http://localhost:5173
```

## Bien moi truong quan trong

Can co it nhat:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your-gemini-api-key
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

Mot so bien hay dung:

```env
RAG_MODEL=models/gemini-2.5-flash
RAG_MAX_CONTEXT_CHARS=2000
RAG_DIRECT_ANSWER_THRESHOLD=0.80
LESSON_QUESTION_GENERATION_MODE=hybrid
LESSON_QUESTION_BANK_SIZE=20
LESSON_QUIZ_ATTEMPT_SIZE=10
PROGRESS_ALPHA=0.3
UPLOAD_DIR=backend/uploads
```

## Kiem tra nhanh

### Backend

```bash
python -m compileall backend
```

### Frontend

```bash
cd frontend
cmd /c npm run type-check
```

## Luu y

- Backend da duoc re-structure theo package chuc nang, nen README cu co the khong con dung.
- Neu kiem tra import runtime that su, can dam bao da cai cac dependency nhu `passlib`, `python-jose`, `pymongo`, `google-genai`, `pypdf`, `pytube`, `youtube-transcript-api`.
- Thu muc `backend/uploads` dung de luu file PDF upload.

## Huong mo rong tiep

- bo sung test cho tung package chuc nang
- viet docs rieng cho database collections
- bo sung so do sequence cho luong `ask -> progress -> adaptive -> learning path`
- tach them business rules lon trong `learning_path/service.py` va `ai_tutor/service.py` neu muon chia nho hon
