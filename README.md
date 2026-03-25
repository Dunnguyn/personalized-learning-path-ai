# Personalized Learning Path AI

He thong ho tro hoc tap ca nhan hoa duoc xay dung voi FastAPI + MongoDB + React + AI/RAG.

## 1. Tong quan he thong

Project gom 2 phan chinh:

- Backend: FastAPI, xu ly auth, hoc tap thich nghi, learning path, resource ingestion, AI tutor.
- Frontend: React + TypeScript + Vite, giao dien dashboard, learning path, resources, AI tutor.

Kien truc tong quat:

```text
frontend (React + Vite)
    |
    | HTTP/REST
    v
backend (FastAPI)
    |
    +-- api
    +-- services
    +-- repositories
    +-- ai_module
    +-- database
    |
    v
MongoDB
```

## 2. Cau truc thu muc

```text
.
+-- backend/
|   +-- app/
|   |   +-- ai_module/
|   |   +-- api/
|   |   +-- database/
|   |   +-- repositories/
|   |   +-- services/
|   |   `-- utils/
|   +-- uploads/
|   `-- main.py
+-- frontend/
|   +-- src/
|   |   +-- components/
|   |   +-- contexts/
|   |   +-- pages/
|   |   +-- services/
|   |   `-- utils/
|   `-- package.json
+-- docker-compose.yml
+-- Dockerfile
+-- DOCKER.md
+-- requirements.txt
`-- README.md
```

## 3. Cong nghe su dung

Backend:
- FastAPI
- Uvicorn
- MongoDB (pymongo)
- JWT auth (python-jose)
- Passlib Argon2
- Google Gemini API

Frontend:
- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Axios

## 4. Yeu cau moi truong

Toi thieu:
- Python 3.11+ (khuyen nghi 3.12)
- Node.js 16+ (khuyen nghi 18+)
- npm 7+
- MongoDB local hoac MongoDB Atlas

Tuy chon:
- Docker + Docker Compose
- Redis (neu can cache)

## 5. Cai dat va chay local

### 5.1 Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

API docs:

```text
http://localhost:8000/api/docs
```

Health check:

```text
http://localhost:8000/api/health
```

Readiness check:

```text
http://localhost:8000/api/ready
```

### 5.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend mac dinh:

```text
http://localhost:5173
```

## 6. Chay bang Docker

Khoi dong toan bo stack (MongoDB, Redis, Backend, Frontend):

```bash
docker compose up --build
```

Khoi dong them Mongo Express (dev profile):

```bash
docker compose --profile dev up --build
```

Port mac dinh:
- Backend: 8000
- Frontend: 5173
- MongoDB: 27017
- Redis: 6379
- Mongo Express: 8081 (chi khi bat profile dev)

## 7. Bien moi truong (.env)

Project da co file mau `.env.example`.

```bash
copy .env.example .env
```

Can cau hinh toi thieu:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=your-super-secret-key-minimum-32-characters-long
GEMINI_API_KEY=your-gemini-api-key
```

Cac bien quan trong khac:

```env
ACCESS_TOKEN_EXPIRE_MINUTES=60
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
UPLOAD_DIR=./backend/uploads
RAG_MODEL=models/gemini-2.5-flash
```

Luu y:
- Backend ho tro ca `MONGODB_URI` va `MONGO_URI`, uu tien dung `MONGODB_URI`.
- Khong de `SECRET_KEY` o gia tri mac dinh.

## 8. API hien co

Tat ca business router duoc mount duoi prefix `/api`.

### 8.1 Health va docs

- GET `/`
- GET `/api/health`
- GET `/api/ready`
- GET `/api/docs`
- GET `/api/openapi.json`
- GET `/docs` -> redirect `/api/docs`
- GET `/openapi.json` -> redirect `/api/openapi.json`

### 8.2 Auth

- POST `/api/auth/signup`
- POST `/api/auth/login`

### 8.3 Users

- POST `/api/users/`
- GET `/api/users/me`
- PUT `/api/users/{user_id}`

### 8.4 Subjects

- GET `/api/subjects/`
- GET `/api/subjects/{subject_id}`
- POST `/api/subjects/`

### 8.5 Chapters

- GET `/api/chapters/`
- GET `/api/chapters/{chapter_id}`
- POST `/api/chapters/`

### 8.6 Lessons

- GET `/api/lessons/`
- POST `/api/lessons/`
- GET `/api/lessons/{lesson_id}`
- POST `/api/lessons/{lesson_id}/recommended-chunks`
- GET `/api/lessons/{lesson_id}/recommended-chunks`
- POST `/api/lessons/{lesson_id}/generate-questions`
- GET `/api/lessons/{lesson_id}/questions`

### 8.7 Learning paths (chinh)

- POST `/api/learning-paths/generate`
- GET `/api/learning-paths/history`
- POST `/api/learning-paths/lesson-progress`
- POST `/api/learning-paths/study-time`
- GET `/api/learning-paths/study-summary`
- GET `/api/learning-paths/{path_id}`
- DELETE `/api/learning-paths/{path_id}`

### 8.8 Learning path legacy (hidden from Swagger)

Router legacy dang duoc mount nhung `include_in_schema=False`:

- POST `/api/learning-path/generate`
- GET `/api/learning-path/history`
- POST `/api/learning-path/lesson-progress`
- GET `/api/learning-path/{path_id}`
- DELETE `/api/learning-path/{path_id}`

### 8.9 AI Tutor (ask)

- POST `/api/ask/`
- GET `/api/ask/adaptive-status`
- POST `/api/ask/detect-concepts`
- GET `/api/ask/recommend-concepts`
- GET `/api/ask/history`
- DELETE `/api/ask/history/{history_id}`
- POST `/api/ask/generate-assessment`

### 8.10 Progress

- POST `/api/progress/update`
- GET `/api/progress/summary`
- GET `/api/progress/overview`
- GET `/api/progress/confidence`
- GET `/api/progress/concept/{concept_id}`

### 8.11 Resources

- GET `/api/resources/`
- POST `/api/resources/`
- POST `/api/resources/import`
- GET `/api/resources/search`
- POST `/api/resources/import-pdf`
- POST `/api/resources/import-youtube`
- GET `/api/resources/jobs/{job_id}`
- GET `/api/resources/pdf/{resource_id}`
- GET `/api/resources/{resource_id}`
- DELETE `/api/resources/{resource_id}`

### 8.12 Recommendations

- GET `/api/recommendations/resources`
- GET `/api/recommendations/progress`

### 8.13 Concepts

- GET `/api/concepts`
- GET `/api/concepts/{concept_id}`

Phan lon endpoint business yeu cau Bearer token.

## 9. Frontend routes hien co

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

## 10. Scripts huu ich

Backend (tu root):

```bash
python -m compileall backend
python -c "from backend.main import validate_env; validate_env(); print('env ok')"
python -c "from backend.app.database.mongo import get_db; print(get_db().command('ping'))"
```

Frontend (trong thu muc `frontend`):

```bash
npm run dev
npm run build
npm run preview
npm run type-check
npm run lint
npm run format
```

## 11. Kiem tra nhanh he thong

1. Start backend va frontend.
2. Mo Swagger tai `/api/docs`.
3. Kiem tra `GET /api/health` va `GET /api/ready`.
4. Dang ky/dang nhap de lay Bearer token.
5. Thu cac luong chinh: create subject/chapter/lesson, generate learning path, ask AI, import resource.

## 12. Luu y quan trong

- Trong workspace hien tai khong co thu muc `tests/`, vi vay cac lenh pytest can duoc bo sung them test files truoc khi chay.
- File `.env.example` hien dang bao gom day du bien cho backend/frontend.
- Docker stack trong `docker-compose.yml` da co san MongoDB, Redis, backend, frontend va profile dev cho mongo-express.

## 13. Tai lieu lien quan

- Docker huong dan chi tiet: `DOCKER.md`
- Backend entrypoint: `backend/main.py`
- Frontend app router: `frontend/src/App.tsx`
