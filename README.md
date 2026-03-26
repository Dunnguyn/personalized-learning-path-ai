# Personalized Learning Path AI

AI-powered personalized learning platform built with FastAPI + MongoDB + React + RAG.

## Overview

This repository includes two main applications:

- Backend: FastAPI APIs for auth, learning paths, adaptive progress tracking, resource ingestion, AI tutor, analytics, and evaluation.
- Frontend: React + TypeScript + Vite dashboard for learning workflow and content interaction.

High-level architecture:

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

## Tech Stack

Backend:
- FastAPI
- Uvicorn
- MongoDB (pymongo)
- JWT auth (python-jose)
- Passlib (Argon2)
- Google Gemini API
- Chroma (persistent vector store)

Frontend:
- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- Axios

## Requirements

Minimum:
- Python 3.11+ (recommended 3.12)
- Node.js 18+ (recommended 20+)
- npm 7+
- MongoDB local or Atlas

Optional:
- Docker + Docker Compose
- Redis

## Project Structure

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
|
+-- frontend/
|   +-- src/
|   |   +-- components/
|   |   +-- contexts/
|   |   +-- pages/
|   |   +-- services/
|   |   `-- utils/
|   `-- package.json
|
+-- docker-compose.yml
+-- Dockerfile
+-- DOCKER.md
+-- requirements.txt
`-- README.md
```

## Quick Start (Local)

If this repository already contains an initialized virtual environment (`.venv`), you can skip recreating it and run `pip install -r requirements.txt` directly.

### 1) Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create env file:

```bash
copy .env.example .env
```

Run backend:

```bash
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Alternative in VS Code:
- Run task `Start Backend API` from the command palette (`Tasks: Run Task`) or the Run Task UI.

Swagger docs:

```text
http://localhost:8000/api/docs
```

Health endpoints:

```text
http://localhost:8000/api/health
http://localhost:8000/api/ready
```

### 2) Frontend

```bash
cd frontend
npm install
npm run dev
```

Optional frontend env file (`frontend/.env`):

```env
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
```

Frontend default URL:

```text
http://localhost:5173
```

## Environment Variables

Required minimum:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=your-super-secret-key-minimum-32-characters-long
GEMINI_API_KEY=your-gemini-api-key
```

Setup tip:
- Start from `.env.example` and keep `.env` at repository root so backend and Docker use the same baseline config.

Common optional variables:

```env
ACCESS_TOKEN_EXPIRE_MINUTES=60
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
UPLOAD_DIR=./backend/uploads
RAG_MODEL=models/gemini-2.5-flash
CHROMA_PATH=backend/.runtime/chroma
CHROMA_COLLECTION=learning_resource_chunks
REC_W_SEMANTIC=0.30
REC_W_MASTERY=0.18
REC_W_CONFIDENCE=0.08
REC_W_GOAL=0.10
REC_W_DIFFICULTY=0.10
REC_W_COLLAB=0.12
REC_W_PEDAGOGY=0.05
REC_W_FORMAT_PREF=0.04
REC_W_NOVELTY=0.03
REC_RERANK_ENABLED=true
REC_RERANK_LAMBDA=0.75
REC_EXPLORATION_WEIGHT=0.03
```

Notes:
- Backend supports both `MONGODB_URI` and `MONGO_URI` (`MONGODB_URI` preferred).
- Do not keep `SECRET_KEY` at default values.
- `CHROMA_PATH` should point to runtime storage (not committed to git).
- Recommendation weights are normalized internally, so you can tune each signal independently.

## Run with Docker

Start full stack (MongoDB, Redis, Backend, Frontend):

```bash
docker compose up --build
```

Start with Mongo Express (dev profile):

```bash
docker compose --profile dev up --build
```

Default ports:
- Backend: 8000
- Frontend: 5173
- MongoDB: 27017
- Redis: 6379
- Mongo Express: 8081 (dev profile only)

## API Summary

All business APIs are mounted under `/api`.

### Health and Docs
- GET `/`
- GET `/api/health`
- GET `/api/ready`
- GET `/api/docs`
- GET `/api/openapi.json`

### Auth
- POST `/api/auth/signup`
- POST `/api/auth/login`
- POST `/api/auth/logout`

### Users
- POST `/api/users/`
- GET `/api/users/me`
- PUT `/api/users/{user_id}`

### Subjects
- GET `/api/subjects/`
- GET `/api/subjects/{subject_id}`
- POST `/api/subjects/`

### Chapters
- GET `/api/chapters/`
- GET `/api/chapters/{chapter_id}`
- POST `/api/chapters/`

### Lessons
- GET `/api/lessons/`
- POST `/api/lessons/`
- GET `/api/lessons/{lesson_id}`
- POST `/api/lessons/{lesson_id}/recommended-chunks`
- GET `/api/lessons/{lesson_id}/recommended-chunks`
- POST `/api/lessons/{lesson_id}/generate-questions`
- GET `/api/lessons/{lesson_id}/questions`

### Learning Paths
- POST `/api/learning-paths/generate`
- GET `/api/learning-paths/history`
- POST `/api/learning-paths/lesson-progress`
- GET `/api/learning-paths/{path_id}/lesson-locks`
- POST `/api/learning-paths/study-time`
- GET `/api/learning-paths/study-summary`
- GET `/api/learning-paths/{path_id}`
- DELETE `/api/learning-paths/{path_id}`

### AI Tutor
- POST `/api/ask/`
- GET `/api/ask/adaptive-status`
- POST `/api/ask/detect-concepts`
- GET `/api/ask/recommend-concepts`
- GET `/api/ask/history`
- DELETE `/api/ask/history/{history_id}`
- POST `/api/ask/generate-assessment`

### Progress
- POST `/api/progress/update`
- GET `/api/progress/summary`
- GET `/api/progress/overview`
- GET `/api/progress/confidence`
- GET `/api/progress/concept/{concept_id}`

### Resources
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

### Recommendations
- GET `/api/recommendations/resources`
- GET `/api/recommendations/resources/debug`
- GET `/api/recommendations/progress`
- POST `/api/recommendations/events/click`
- POST `/api/recommendations/events/resource-completed`
- POST `/api/recommendations/feedback`

Recommendation query options (`GET /api/recommendations/resources`):
- `include_breakdown` (bool, default `true`): include component score breakdown.
- `enable_reranking` (bool, default `true`): enable diversity-aware reranking.

### Adaptive Learning Loop
- GET `/api/kt/user/{user_id}/concepts`
- GET `/api/kt/user/{user_id}/lessons/{lesson_id}`
- POST `/api/feedback`
- POST `/api/path/refine/{path_id}`
- GET `/api/path/refinement/{user_id}`
- GET `/api/interventions/{user_id}`

### Exercise Attempts
- GET `/api/lessons/{lesson_id}/attempts`
- GET `/api/learning-paths/{path_id}/attempts`
- GET `/api/lessons/{lesson_id}/statistics`

### Analytics
- GET `/api/analytics/learner/{user_id}`
- GET `/api/analytics/admin/overview`
- GET `/api/analytics/admin/retention`
- GET `/api/analytics/admin/recommendation`
- GET `/api/analytics/system/performance`

### Evaluation
- GET `/api/evaluation/experiments`
- GET `/api/evaluation/experiments/{experiment_id}`
- POST `/api/evaluation/experiments/{experiment_id}/assign/{user_id}`

### Concepts
- GET `/api/concepts`
- GET `/api/concepts/{concept_id}`

Most business endpoints require a Bearer token.

## Frontend Routes

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

## Useful Commands

Backend (run from repository root):

```bash
python -m compileall backend
python -c "from backend.main import validate_env; validate_env(); print('env ok')"
python -c "from backend.app.database.mongo import get_db; print(get_db().command('ping'))"
```

Backend task-based run (from VS Code):
- Task name: `Start Backend API`

Frontend (run from `frontend`):

```bash
npm run dev
npm run build
npm run preview
npm run type-check
npm run lint
npm run format
```

## Quick Verification Flow

1. Start backend and frontend.
2. Open Swagger at `/api/docs`.
3. Verify `GET /api/health` and `GET /api/ready`.
4. Sign up/login to obtain Bearer token.
5. Test core flows: create subject/chapter/lesson, generate path, submit lesson progress, ask AI, import resources.
6. Validate analytics/evaluation endpoints for new telemetry.
7. Validate recommendation upgrade:
    - Call `GET /api/recommendations/resources?goal=<goal>&level=beginner&include_breakdown=true&enable_reranking=true` (you can pass `user_id` explicitly, but it is optional when authenticated)
    - Inspect detailed signal snapshot at `GET /api/recommendations/resources/debug?goal=<goal>&level=beginner&enable_reranking=true` (you can pass `user_id` explicitly, but it is optional when authenticated)
    - Submit explicit feedback with `POST /api/recommendations/feedback`
8. Validate lesson confidence behavior:
    - For an unattempted lesson, confirm confidence is `0.0` in lesson lock/state payloads.
    - Submit that lesson's own questions and verify only that lesson's confidence updates.
    - If a submission is all incorrect (`0%`), the attempt is still recorded for that lesson and confidence remains `0.0`.

## Operational Notes

- The current workspace has no `tests/` folder yet, so add tests before running full pytest workflows.
- `.env.example` already contains backend/frontend baseline variables.
- Docker stack in `docker-compose.yml` includes MongoDB, Redis, backend, frontend, and optional Mongo Express profile.
- Runtime vector index files are ignored from git (`backend/.chroma/`, `backend/.runtime/`).
- The backend loads env in this order: project `.env`, then `backend/.env` (backend overrides project values when both are present).

## Related Docs

- Docker guide: `DOCKER.md`
- Backend entrypoint: `backend/main.py`
- Frontend app router: `frontend/src/App.tsx`
