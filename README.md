# Personalized Learning Path AI

He thong ho tro hoc tap ca nhan hoa duoc xay dung voi `FastAPI + MongoDB + React + AI/RAG`.

## Trang thai hien tai

Backend da duoc smoke-test lai vao ngay `2026-03-22` trong workspace hien tai.

Da xac minh thanh cong:
- `python -m compileall backend`
- import app va chay startup `lifespan`
- `MongoDB ping` thanh cong
- `GET /` tra ve `200`
- `GET /api/health` tra ve `200`
- `GET /api/ready` tra ve `200`
- `GET /docs` redirect sang `/api/docs`
- `GET /api/openapi.json` tra ve `200`
- `pytest tests/test_backend_smoke.py` voi `12` smoke tests: passed

Ghi chu:
- Hien chua co bo test `pytest` rieng cho backend.
- ChromaDB co thu gui telemetry ra ngoai; trong moi truong bi chan network se xuat hien warning PostHog, nhung khong chan backend khoi dong.

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
    +-- repositories
    +-- database
    +-- ai_module
    |
    v
MongoDB
```

## Cau truc backend hien tai

```text
backend/
+-- app/
|   +-- ai_module/
|   +-- api/
|   +-- database/
|   +-- repositories/
|   +-- services/
|   `-- utils/
+-- scripts/
+-- uploads/
`-- main.py
```

`backend/app/api/` hien co cac router chinh:
- `auth.py`
- `users.py`
- `subjects.py`
- `chapters.py`
- `lessons.py`
- `resources.py`
- `learning_path.py`
- `learning_paths.py`
- `progress.py`
- `ask.py`
- `recommendations.py`
- `concepts.py`

## API dang co

Tat ca router business duoc mount duoi prefix `/api`.

### Health va docs
- `GET /`
- `GET /api/health`
- `GET /api/ready`
- `GET /api/docs`
- `GET /api/openapi.json`
- `GET /docs` -> redirect `/api/docs`
- `GET /openapi.json` -> redirect `/api/openapi.json`

### Auth va user
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/users/`
- `GET /api/users/me`
- `PUT /api/users/{user_id}`

### Subject, chapter, lesson
- `POST /api/subjects/`
- `POST /api/chapters/`
- `POST /api/lessons/`
- `POST /api/lessons/{lesson_id}/recommended-chunks`
- `GET /api/lessons/{lesson_id}/recommended-chunks`
- `POST /api/lessons/{lesson_id}/generate-questions`
- `GET /api/lessons/{lesson_id}/questions`

### Learning path
- `POST /api/learning-path/generate`
- `GET /api/learning-path/history`
- `POST /api/learning-path/lesson-progress`
- `GET /api/learning-path/{path_id}`
- `POST /api/learning-paths/generate`
- `GET /api/learning-paths/history`
- `POST /api/learning-paths/lesson-progress`
- `GET /api/learning-paths/{path_id}`

### AI tutor va progress
- `POST /api/ask/`
- `GET /api/ask/adaptive-status`
- `POST /api/ask/detect-concepts`
- `GET /api/ask/recommend-concepts`
- `GET /api/ask/history`
- `DELETE /api/ask/history/{history_id}`
- `POST /api/ask/generate-assessment`
- `POST /api/progress/update`
- `GET /api/progress/summary`
- `GET /api/progress/overview`
- `GET /api/progress/confidence`
- `GET /api/progress/concept/{concept_id}`

### Resources va recommendations
- `GET /api/resources/`
- `POST /api/resources/`
- `POST /api/resources/import`
- `GET /api/resources/search`
- `POST /api/resources/import-pdf`
- `POST /api/resources/import-youtube`
- `GET /api/resources/jobs/{job_id}`
- `GET /api/resources/pdf/{resource_id}`
- `GET /api/recommendations/resources`
- `GET /api/recommendations/progress`
- `GET /api/concepts`
- `GET /api/concepts/{concept_id}`

Nhieu endpoint trong so nay yeu cau `Bearer token`.

## Cai dat va chay local

### Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Backend docs:

```text
http://localhost:8000/api/docs
```

Health check:

```text
http://localhost:8000/api/health
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

Can co toi thieu:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
SECRET_KEY=your-secret-key
```

Nen co them:

```env
GEMINI_API_KEY=your-gemini-api-key
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000
DB_NAME=learning_path_ai
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
UPLOAD_DIR=./backend/uploads
```

Luu y:
- Backend hien da ho tro ca `MONGODB_URI` va `MONGO_URI`, nhung nen uu tien dung `MONGODB_URI` de dong bo voi `.env.example`.
- `SECRET_KEY` khong duoc de gia tri mac dinh `CHANGE_THIS_SECRET_KEY`.

## Kiem tra nhanh backend

### 1. Kiem tra compile

```bash
python -m compileall backend
```

### 2. Kiem tra env startup

```bash
python -c "from backend.main import validate_env; validate_env(); print('env ok')"
```

### 3. Kiem tra MongoDB

```bash
python -c "from backend.app.database.mongo import get_db; print(get_db().command('ping'))"
```

### 4. Kiem tra app bang TestClient

```bash
python -c "from fastapi.testclient import TestClient; from backend.main import app; c=TestClient(app); print(c.get('/api/health').status_code)"
```

### 5. Chay smoke test backend bang pytest

```bash
python -m pytest tests/test_backend_smoke.py
```

Bo test nay bao phu:
- startup, health, docs redirect
- auth gate cho cac route protected
- users, subjects, chapters, lessons
- resources, progress, ask
- learning-path, learning-paths
- recommendations va concepts

Neu can test day du vong doi startup:

```bash
@'
from fastapi.testclient import TestClient
from backend.main import app

with TestClient(app) as client:
    print(client.get("/api/ready").json())
'@ | python -
```

## Scripts frontend

Trong `frontend/package.json`:

```bash
npm run dev
npm run build
npm run preview
npm run type-check
npm run lint
```

## Ghi chu cho nguoi dev

- README cu khong con dung o mot so phan package/service, vi backend da doi cau truc.
- Trong workspace hien tai, backend khoi dong duoc sau khi dong bo cach doc `.env` giua `backend/main.py` va `backend/app/database/mongo.py`.
- Da bo sung smoke suite tai `tests/test_backend_smoke.py` va fixture tai `tests/conftest.py`.
- Neu muon kiem tra sau hon, buoc tiep theo nen la them test `pytest` cho auth, resources, learning-path va progress.
