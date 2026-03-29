# Personalized Learning Path AI

AI-powered learning platform for generating personalized study paths, tracking learner progress, and supporting question answering with retrieval-augmented generation (RAG).

## Overview

This repository contains:

- `backend/`: FastAPI application for auth, curriculum, learning paths, progress tracking, analytics, recommendations, and AI tutor workflows
- `frontend/`: React + TypeScript + Vite client for the learner-facing experience
- MongoDB as the primary application database
- Chroma as the local vector store used by retrieval features

```text
frontend (React + Vite)
    |
    | HTTP / REST
    v
backend (FastAPI)
    |
    +-- app/api
    +-- app/services
    +-- app/repositories
    +-- app/ai_module
    +-- app/database
    |
    +-- MongoDB
    `-- Chroma
```

## Key Features

- Personalized learning path generation by subject, goal, and level
- Lesson progress tracking with confidence, study-time, and adaptive quiz support
- Resource ingestion from text, PDF, and YouTube
- AI tutor endpoints backed by retrieval and Gemini-based generation
- Recommendation, knowledge tracing, intervention, analytics, and evaluation modules

## Tech Stack

Backend:

- FastAPI
- Uvicorn
- MongoDB (`pymongo`)
- JWT auth (`python-jose`)
- Passlib with Argon2
- Google Gemini API
- Chroma

Frontend:

- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router

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
|   +-- tests/
|   +-- uploads/
|   `-- main.py
|
+-- frontend/
|   +-- public/
|   +-- src/
|   |   +-- components/
|   |   +-- contexts/
|   |   +-- pages/
|   |   +-- services/
|   |   +-- types/
|   |   `-- utils/
|   +-- .env.example
|   `-- package.json
|
+-- docker-compose.yml
+-- DOCKER.md
+-- requirements.txt
`-- README.md
```

## Requirements

- Python 3.11+
- Node.js 20+ recommended
- npm 9+
- MongoDB local or MongoDB Atlas

Optional:

- Docker + Docker Compose
- Redis

## Quick Start

### 1. Backend setup

Create a virtual environment if you do not already have one:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.\.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the backend env file from the project root:

```bash
copy .env.example .env
```

Run the API from the repository root:

```bash
python -m uvicorn backend.main:app --reload 
```

Useful URLs:

- Swagger UI: `http://localhost:8000/api/docs`
- OpenAPI JSON: `http://localhost:8000/api/openapi.json`
- Health check: `http://localhost:8000/api/health`
- Readiness check: `http://localhost:8000/api/ready`

Note:

- `GET /docs` and `GET /openapi.json` redirect to the `/api/*` versions.

### 2. Frontend setup

Move into the frontend app:

```bash
cd frontend
```

Create the frontend env file:

```bash
copy .env.example .env
```

Install dependencies and start Vite:

```bash
npm install
npm run dev
```

Frontend URL:

- `http://localhost:5173`

## Environment Variables

### Backend `.env` at repository root

Minimum backend configuration:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=your-super-secret-key-minimum-32-characters-long
```

Recommended for AI features:

```env
GEMINI_API_KEY=your-gemini-api-key
RAG_MODEL=models/gemini-2.5-flash
```

Common optional backend variables:

```env
ACCESS_TOKEN_EXPIRE_MINUTES=60
ADMIN_EMAILS=admin@example.com
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000
UPLOAD_DIR=./backend/uploads
CHROMA_PATH=backend/.runtime/chroma
CHROMA_COLLECTION=learning_resource_chunks
```

Notes:

- The backend accepts both `MONGODB_URI` and `MONGO_URI`, with `MONGODB_URI` preferred.
- `SECRET_KEY` must not use the default placeholder value.
- `GEMINI_API_KEY` is optional for startup, but required for Gemini-backed generation flows.
- The backend loads env in this order: project `.env`, then `backend/.env` if present.

### Frontend `frontend/.env`

```env
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
VITE_APP_NAME=Personalized Learning Path
```

Notes:

- Vite reads frontend env files from the `frontend/` directory, not from the repository root.
- The frontend API client defaults to `http://localhost:8000/api` if these vars are omitted.

## Running with Docker

Start the full stack:

```bash
docker compose up --build
```

Start the stack with Mongo Express:

```bash
docker compose --profile dev up --build
```

Default ports:

- Backend: `8000`
- Frontend: `5173`
- MongoDB: `27017`
- Redis: `6379`
- Mongo Express: `8081` with `--profile dev`

For more container details, see `DOCKER.md`.

## Development Commands

Backend:

```bash
python -m compileall backend
python -c "from backend.main import validate_env; validate_env(); print('env ok')"
pytest backend/tests -q
```

Frontend:

```bash
cd frontend
npm run dev
npm run build
npm run preview
npm run type-check
npm run lint
npm run format
```

## API Overview

All business endpoints are mounted under `/api`.

Main route groups:

- `/api/auth/*`: signup, login, logout
- `/api/users/*`: current user and profile updates
- `/api/subjects/*`, `/api/chapters/*`, `/api/lessons/*`: curriculum data
- `/api/learning-paths/*`: path generation, history, lesson progress, study time
- `/api/resources/*`: resource CRUD, import, search, ingestion jobs
- `/api/ask/*`: AI tutor and assessment flows
- `/api/progress/*`: progress summaries and concept confidence
- `/api/recommendations/*`: recommendation retrieval, debug, feedback, interaction events
- `/api/kt/*`, `/api/path/*`, `/api/interventions/*`, `/api/feedback`: adaptive learning loop
- `/api/analytics/*`, `/api/evaluation/*`: telemetry and experiment workflows
- `/api/concepts/*`: concept lookup

Use Swagger for the latest request and response schemas:

- `http://localhost:8000/api/docs`

## Frontend Routes

The current frontend includes these primary routes:

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

## Notes

- MongoDB is required for backend readiness checks to pass.
- Chroma data should stay in a runtime directory and not be committed.
- Redis is optional in local development unless you explicitly depend on it.
- The repository currently includes backend tests under `backend/tests/`.
