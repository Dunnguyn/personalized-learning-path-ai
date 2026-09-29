# Personalized Learning Path AI

Personalized Learning Path AI is a full-stack learning platform that generates AI-assisted study plans, retrieves lesson resources with semantic search, tracks learner progress, and adapts the next recommended action based on user activity.

The repository is structured as a modular monolith:

- `frontend/`: React 18 + TypeScript + Vite single-page application
- `backend/`: FastAPI application with service and repository layers
- `backend/app/ai_module/`: LLM, embeddings, and retrieval integrations
- `backend/app/services/`: domain orchestration for learning paths, lessons, recommendations, adaptive logic, and tutoring
- `backend/app/repositories/`: MongoDB access layer

## Main Features

- JWT-based authentication and learner profile management
- AI-generated learning paths by subject, goal, and level
- Lesson runtime with progress tracking and mastery updates
- Resource ingestion for text, PDF, and YouTube sources
- Semantic retrieval and recommendation ranking
- AI tutor endpoints backed by retrieval-augmented generation
- Adaptive next-step recommendations from learner events
- Docker-based local development workflow

## Tech Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS, React Router
- Backend: FastAPI, Pydantic, PyMongo, PyJWT, passlib
- AI: Google Gemini, BM25 retrieval; optional sentence-transformers and Chroma integrations
- Data: MongoDB
- Tooling: ESLint, TypeScript, pytest, Docker Compose

## Architecture

The backend follows a service-oriented layered architecture inside one deployable application. API routers handle transport concerns, services own domain workflows, repositories isolate persistence, and AI modules encapsulate model and embedding integrations. The frontend consumes the REST API through typed service modules.

Strengths:

- Clear separation between routers, services, and repositories
- Rich domain coverage for learning paths, lessons, analytics, and tutoring
- Good fit for incremental extraction into smaller modules later

Current limitations:

- Several backend services and frontend pages are very large and hard to reason about
- Current tests focus on selected curriculum, adaptive-learning, and recommendation workflows; they do not establish end-to-end coverage
- Runtime configuration is distributed across multiple files
- The codebase still contains traces of local/demo workflows that should stay disabled in public deployments

## Getting Started

### Prerequisites

- Python 3.12 (used by the backend Docker image and local verification environment)
- Node.js 20.19+ or 22.13+ (Docker uses Node 22)
- MongoDB 7 or newer

### 1. Backend setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

The default requirements do not include `sentence-transformers`, `chromadb`, or spaCy. These integrations load optionally at runtime. A tested optional dependency set still needs manual completion; there is no separate local-embeddings requirements file in this repository.

Required backend variables:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=replace-with-a-random-secret-at-least-32-characters-long
```

Replace `SECRET_KEY` with a newly generated random value of at least 32 characters. Configure `GEMINI_API_KEY` or `GEMINI_API_KEYS` for provider-backed AI features. Never put secrets in `VITE_*` variables: those values are exposed to the browser.

Start the API:

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Frontend setup

```powershell
cd frontend
npm ci
copy .env.example .env
npm run dev
```

Default frontend environment:

```env
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
VITE_APP_NAME=Personalized Learning Path AI
```

### 3. Repository-level helper scripts

From the repo root:

```bash
npm run build
npm run lint
npm run type-check
```

These delegate to the frontend workspace.

## Running with Docker

```bash
docker compose up --build
```

Optional development profile with Mongo Express:

```bash
docker compose --profile dev up --build
```

See [DOCKER.md](DOCKER.md) for details. Compose uses development settings, fallback passwords, reload, and host-published database ports; deployment hardening and a clean Docker startup still need manual verification.

## Environment Variables

Important backend variables:

- `MONGODB_URI`
- `DB_NAME`
- `SECRET_KEY`
- `ADMIN_EMAILS`
- `GEMINI_API_KEY` or `GEMINI_API_KEYS`
- `EMBEDDING_PROVIDER`
- `CORS_ORIGINS`
- `UPLOAD_DIR`

Important frontend variables:

- `VITE_API_URL`
- `VITE_API_BASE_PATH`
- `VITE_APP_NAME`

The checked-in `.env.example` files intentionally keep insecure demo-only options disabled by default.

## Tests and Validation

Backend:

```bash
python -m compileall -q backend/app backend/main.py
python -m flake8 backend --select F401,F841,F821,E9
```

The local test suite and benchmark scripts are excluded from this repository. If available locally, run backend tests with `python -m pytest backend/tests -q` using a disposable database; imports can initialize MongoDB indexes.

Frontend:

```bash
cd frontend
npm run lint
npm run type-check
npm run build
```

## API / Main Modules

- Interactive API documentation: `http://localhost:8000/api/docs`
- OpenAPI schema: `http://localhost:8000/api/openapi.json`
- Liveness and readiness: `/api/health` and `/api/ready` (these inspect dependencies)
- Routers under `backend/app/api/` cover authentication, learning paths, resources, lessons, questions, progress, recommendations, analytics, and tutoring.
- `backend/app/jobs/` contains explicit batch/backfill entry points; review their database effects before running.

## Project Structure

```text
backend/                 FastAPI entry point and application modules
frontend/                React application and build configuration
requirements.txt         Pinned Python dependencies and quality tools
docker-compose.yml       Local development services
```

## Known Limitations

- Automated checks do not establish safe production authentication, authorization, or deployment.
- Optional AI backends and provider availability affect retrieval and generation quality.
- Local uploaded books and benchmark results are excluded from version control; review ownership and privacy before sharing any copies.
