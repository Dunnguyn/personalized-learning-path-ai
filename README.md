# Personalized Learning Path AI

Nen tang hoc tap ca nhan hoa su dung AI de sinh lo trinh hoc, quan ly lesson runtime, truy hoi hoc lieu theo ngu canh, va de xuat hanh dong hoc tiep theo dua tren learner state.

He thong nay duoc to chuc theo huong `backend orchestration`: backend khong chi cung cap CRUD ma con dieu phoi learning path generation, ingestion pipeline, semantic retrieval, quiz/progress, adaptive loop, AI tutor, va analytics.

## Tong quan he thong

San pham xoay quanh 4 vong lap chinh:

- `Generate path`: sinh learning path theo `subject + goal + level`, dong thoi khoi tao concept graph, chapter, lesson, va knowledge-tracing state.
- `Learn lesson`: hoc theo lesson, ghi study time, cap nhat confidence/completion, mo khoa lesson tiep theo khi dat dieu kien.
- `Retrieve resources`: ingest text/PDF/YouTube thanh chunks co embedding de search, recommend, va phuc vu AI tutor.
- `Adapt next step`: thu thap learning events, tinh learner snapshot, giai thich trang thai hoc, va de xuat next step/next action.

## Kien truc tong the

```text
Frontend (React + Vite + TypeScript)
  -> REST API /api/*
Backend (FastAPI)
  -> API routers
  -> Service orchestration layer
  -> Repository layer
  -> AI module (LLM, embeddings, retrieval)
Data layer
  -> MongoDB
  -> backend/uploads (PDF/assets)
  -> Redis (optional support/cache layer)
```

Mot so dac diem kien truc quan trong:

- `backend/main.py` la entrypoint duy nhat, mount toan bo router duoi prefix `/api`.
- Service layer la boundary nghiep vu chinh, gom cac domain nhu `unified_learning_path_service`, `adaptive_learning_loop_service`, `hybrid_recommendation_service`, `learner_profile_service`, `ai_tutor`.
- Repository layer dong vai tro truy cap collection MongoDB va tach persistence khoi orchestration logic.
- AI stack duoc chia thanh embedding, retrieval, prompt-building, question generation, va tutoring thay vi nhung truc tiep vao router.
- Startup co `fail fast` cho env bat buoc, readiness check xac thuc ca database va AI embedding runtime.

## Cac domain cot loi

### 1. Auth va learner profile

- JWT auth qua `/api/auth/*`.
- Ho so hoc vien duoc quan ly qua `/api/learner-profile/me`.
- Luong diagnostic duoc expose qua `/api/diagnostic/*` de bootstrap muc do/khoang trong kien thuc.

### 2. Learning path va lesson runtime

- `POST /api/learning-paths/generate` sinh learning path theo `subject_id`, `goal`, `level`.
- `GET /api/learning-paths/history` va cac endpoint detail/summary phuc vu man hinh lich su va chi tiet lo trinh.
- `POST /api/learning-paths/lesson-progress` cap nhat completion, confidence, quiz outcome, dong thoi kich hoat event/adaptive hooks.
- Lesson runtime duoc chia qua cac API `/api/chapters/*`, `/api/lessons/*`, `/api/progress/*`, `/api/kt/*`.

### 3. Resource ingestion, chunking, search, recommendation

- Admin co the ingest hoc lieu text/PDF/YouTube qua `/api/resources/*`.
- Noi dung duoc tach chunk, gan embedding, luu de semantic search va lesson recommendation.
- Hybrid recommendation layer ket hop quality, relevance, event signals, va lesson scope.
- Admin co snapshot cho curation va ingestion health de debug du lieu.

### 4. Adaptive learning loop

- Event hoc tap duoc ghi qua `/api/adaptive/events`.
- Learner state snapshot duoc tinh/lay qua `/api/adaptive/state/*` va `/api/adaptive/recompute-state/*`.
- He thong tra ve `next-step`, `next-action`, va explanation cho tung lesson/path.
- Path refinement va intervention duoc expose qua cac endpoint refinement rieng.

### 5. AI tutor va hoi dap co ngu canh

- `POST /api/ask/` la entrypoint chinh cho AI tutor.
- Pipeline hoi dap bao gom retrieval, concept detection, answer generation, progress update, va adaptive recommendation.
- Ask history, concept-related endpoint, va feedback hooks ton tai de phuc vu tutor loop dai han.

### 6. Analytics va admin observability

- Learner analytics va admin analytics duoc expose qua `/api/analytics/*`.
- API middleware tu dong log `api_called` / `api_failed`.
- Co health/debug endpoint cho AI stack:
  - `GET /api/health`
  - `GET /api/ready`
  - `GET /api/health/ai`
  - `GET /api/debug/ai`
  - `POST /api/debug/ai/backfill?limit=...` (admin)

## Giao dien frontend hien co

Frontend hien tai la learner app build bang React 18 + Vite, gom cac route chinh:

- `/login`
- `/signup`
- `/signup-step2`
- `/dashboard`
- `/learning-path`
- `/learning-path/:pathId`
- `/resources`
- `/ai-tutor`
- `/settings`
- `/debug-token`

Man hinh frontend tiep can backend thong qua `frontend/src/services/*` va cac parser/type rieng cho dashboard, learning path, resources, adaptive, analytics, auth.

## Tech stack

### Backend

- Python + FastAPI + Uvicorn
- MongoDB (`pymongo`)
- Auth: `python-jose`, `passlib[argon2]`
- Validation/schema: `pydantic`
- AI/LLM: Google Gemini (`google-genai`)
- Retrieval/ranking: `numpy`, `scikit-learn`, `rank-bm25`
- Ingestion: `pypdf`, `PyMuPDF`, `pytube`, `youtube-transcript-api`
- Embedding fallback: `sentence-transformers` hoac `hash_fallback` tuy theo env/runtime

### Frontend

- React 18 + TypeScript + Vite
- React Router
- Tailwind CSS
- React Markdown + `remark-gfm`
- React Flow

### Runtime / ha tang

- MongoDB la dependency bat buoc
- Redis co trong `docker-compose.yml`, hien o vai tro support layer
- Docker + Docker Compose cho local full-stack runtime

## Cau truc thu muc

```text
.
+-- backend/
|   +-- main.py
|   +-- app/
|   |   +-- api/
|   |   +-- ai_module/
|   |   +-- services/
|   |   +-- repositories/
|   |   +-- database/
|   |   `-- utils/
|   +-- uploads/
|   `-- pyproject.toml
+-- frontend/
|   +-- src/
|   |   +-- components/
|   |   +-- contexts/
|   |   +-- pages/
|   |   +-- services/
|   |   +-- types/
|   |   `-- utils/
|   `-- package.json
+-- docs/
+-- docker-compose.yml
+-- Dockerfile
+-- requirements.txt
`-- README.md
```

## Luong nghiep vu chinh

### A. Tao learning path

1. Learner gui `POST /api/learning-paths/generate`.
2. Backend lay personalization context tu learner profile.
3. Unified learning path service sinh chapter, lesson, concept graph.
4. Knowledge tracing bootstrap state cho path vua tao.
5. Event `learning_path_generated` duoc ghi vao analytics/event layer.

### B. Hoc lesson va cap nhat tien do

1. Frontend lay lesson detail va recommended chunks.
2. Learner hoc tai lieu, doc PDF/resource, hoac lam cau hoi.
3. Frontend gui `lesson-progress`, `study-time`, hoac adaptive event.
4. Backend cap nhat confidence/completion, log event, va recompute learner state neu can.
5. Lesson tiep theo duoc mo khoa dua tren completion rule va prerequisite.

### C. Ingest hoc lieu

1. Admin them text/PDF/YouTube resource.
2. Backend tao ingestion job nen.
3. Noi dung duoc tach chunk, gan metadata, tao embedding, va luu vao kho semantic retrieval.
4. Resource chunks sau do duoc tai su dung cho search, lesson recommendation, va AI tutor.

### D. Adaptive learning

1. He thong nhan event hoc tap tu lesson/resource/quiz/recommendation.
2. Adaptive loop tong hop event thanh learner snapshot.
3. Decision service tinh next step, next action, intervention, hoac explanation.
4. Frontend co the hien thi de xuat hoc tiep theo dua tren snapshot moi nhat.

### E. AI tutor

1. Learner hoi qua `POST /api/ask/`.
2. Backend retrieval context lien quan tu resource chunks.
3. Neu can, LLM sinh cau tra loi dua tren ngu canh va learner state.
4. He thong co the cap nhat progress, concept detection, va ask history sau moi lan hoi dap.

## Chay local

### 1. Yeu cau

- Python 3.11+ khuyen nghi
- Node.js 18+ khuyen nghi
- MongoDB dang chay o local hoac accessible qua `MONGODB_URI`

### 2. Backend

```bash
python -m venv .venv
```

Windows PowerShell:

```bash
.\.venv\Scripts\activate
```

Cai dependency:

```bash
pip install -r requirements.txt
```

Tao `.env` tu `.env.example`. Cac bien toi thieu can co:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=your-super-secret-key-minimum-32-characters-long
```

Gemini la optional, nhung can key neu muon dung day du duong LLM/Gemini.
Ban co the dung 1 key hoac nhieu key:

```env
# Mot key
GEMINI_API_KEY=your-primary-key

# Hoac nhieu key de app tu doi sang key tiep theo khi key hien tai het quota
GEMINI_API_KEYS=key_1,key_2,key_3

# Hoac danh so thu tu neu muon de doc hon
GEMINI_API_KEY_1=key_1
GEMINI_API_KEY_2=key_2
GEMINI_API_KEY_3=key_3
```

Chay backend:

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Tao `frontend/.env` tu `frontend/.env.example`:

```env
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
VITE_APP_NAME=Personalized Learning Path
```

### 4. Dia chi mac dinh

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/api/docs`

## Chay bang Docker

Chay full stack:

```bash
docker compose up --build
```

Chay kem Mongo Express:

```bash
docker compose --profile dev up --build
```

Port mac dinh:

- Backend: `8000`
- Frontend: `5173`
- MongoDB: `27017`
- Redis: `6379`
- Mongo Express: `8081` (chi khi bat profile `dev`)

## Bien moi truong quan trong

### Backend bat buoc

- `MONGODB_URI` hoac `MONGO_URI`
- `DB_NAME`
- `SECRET_KEY`

### Backend thuong dung

- `GEMINI_API_KEY`
- `GEMINI_API_KEYS`
- `GEMINI_API_KEY_1..N`
- `GEMINI_API_KEY_COOLDOWN_SECONDS`
- `GEMINI_API_KEY_RETRY_DELAY_SECONDS`
- `RAG_MODEL`
- `EMBEDDING_PROVIDER`
- `SENTENCE_TRANSFORMER_MODEL`
- `GEMINI_EMBEDDING_MODEL`
- `CORS_ORIGINS`
- `UPLOAD_DIR`
- `ENVIRONMENT`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `EMBEDDING_BACKFILL_ON_STARTUP`
- `EMBEDDING_BACKFILL_LIMIT`

### Frontend

- `VITE_API_URL`
- `VITE_API_BASE_PATH`
- `VITE_APP_NAME`

Chi tiet day du xem `.env.example` va `frontend/.env.example`.

## Lenh dev huu ich

### Backend

```bash
python -m compileall backend
python -c "from backend.main import validate_env; validate_env(); print('env ok')"
```

### Frontend

```bash
cd frontend
npm run type-check
npm run lint
npm run build
```

Luu y: trong worktree hien tai khong thay `backend/tests/`, vi vay README nay khong khai bao mot backend pytest suite cu the.

## Tai lieu lien quan

- `DOCKER.md`: huong dan runtime va container chi tiet hon
- `backend/ARCHITECTURE_SOURCE_OF_TRUTH_VI.md`: boundary/domain source of truth
- `SYSTEM_ANALYSIS_VI.md`, `SYSTEM_ANALYSIS_VII.md`, `SYSTEM_UC_ACTIVITY_ERD_VI.md`: tai lieu phan tich, use case, ERD, va direction nang cap
- `docs/plantuml/*`: use case, activity, va ERD diagram

## Trang thai hien tai cua codebase

Codebase dang o giai doan hop nhat giua legacy flow va boundary moi. README nay mo ta boundary dang duoc su dung o `backend/main.py` va cac router/service hien co, uu tien phan da expose ra API thay vi cac implementation cu chua don xong.
