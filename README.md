# Personalized Learning Path AI

Personalized Learning Path AI is a full-stack learning platform that generates AI-assisted study plans, retrieves lesson resources with semantic search, tracks learner progress, and adapts the next recommended action based on user activity.

The repository is structured as a modular monolith:

- `frontend/`: React 18 + TypeScript + Vite single-page application
- `backend/`: FastAPI application with service and repository layers
- `backend/app/ai_module/`: LLM, embeddings, and retrieval integrations
- `backend/app/services/`: domain orchestration for learning paths, lessons, recommendations, adaptive logic, and tutoring
- `backend/app/repositories/`: MongoDB access layer
- `docs/`: release-facing architecture and contributor documentation

## Features

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
- Backend: FastAPI, Pydantic, PyMongo, python-jose, passlib
- AI: Google Gemini, sentence-transformers, BM25 retrieval
- Data: MongoDB
- Tooling: ESLint, TypeScript, pytest, Docker Compose

## Architecture Summary

The backend follows a service-oriented layered architecture inside one deployable application. API routers handle transport concerns, services own domain workflows, repositories isolate persistence, and AI modules encapsulate model and embedding integrations. The frontend consumes the REST API through typed service modules.

Strengths:

- Clear separation between routers, services, and repositories
- Rich domain coverage for learning paths, lessons, analytics, and tutoring
- Good fit for incremental extraction into smaller modules later

Current limitations:

- Several backend services and frontend pages are very large and hard to reason about
- Test coverage is minimal
- Runtime configuration is distributed across multiple files
- The codebase still contains traces of local/demo workflows that should stay disabled in public deployments

More detail: [docs/ARCHITECTURE.md](/e:/Hocccc/Project/personalized-learning-path-ai/docs/ARCHITECTURE.md)

## Getting Started

### Prerequisites

- Python 3.11 or newer
- Node.js 18 or newer
- MongoDB 7 or newer

### 1. Backend setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Optional local embeddings:

```bash
pip install -r requirements-local-embeddings.txt
```

Required backend variables:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=replace-with-a-random-secret-at-least-32-characters-long
```

Start the API:

```bash
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Frontend setup

```bash
cd frontend
npm install
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

See [DOCKER.md](/e:/Hocccc/Project/personalized-learning-path-ai/DOCKER.md) for details.

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
python -m pytest backend/tests -q
python -m compileall backend
```

Frontend:

```bash
cd frontend
npm run type-check
npm run build
```

## Release Notes

Before publishing this repository publicly:

- Generate a real `SECRET_KEY`
- Keep all `.env` files untracked
- Review CORS origins for your deployment
- Keep `ALLOW_INSECURE_EMAIL_ONLY_PASSWORD_RESET` disabled
- Remove local build artifacts and dependency folders from the working tree

## Contributing

See [CONTRIBUTING.md](/e:/Hocccc/Project/personalized-learning-path-ai/CONTRIBUTING.md).

## License

This project is released under the [MIT License](/e:/Hocccc/Project/personalized-learning-path-ai/LICENSE).
