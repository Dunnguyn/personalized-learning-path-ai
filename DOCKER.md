# Docker Guide

This repository includes a development-oriented Docker Compose setup for the backend, frontend, MongoDB, and an optional Mongo Express instance.

## Prerequisites

- Docker 24+
- Docker Compose v2
- A local `.env` copied from `.env.example`

## Start the stack

```bash
copy .env.example .env
docker compose up --build
```

Services:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- OpenAPI docs: `http://localhost:8000/api/docs`
- MongoDB: `mongodb://localhost:27017`

Optional Mongo Express:

```bash
docker compose --profile dev up --build
```

Mongo Express:

- URL: `http://localhost:8081`
- Username: value of `MONGO_EXPRESS_USERNAME`
- Password: value of `MONGO_EXPRESS_PASSWORD`

## Important security notes

- Set a real `SECRET_KEY` in `.env` before starting the backend
- Do not use the insecure direct password reset flow in public environments
- Treat Docker Compose defaults as local development only
- Keep `.env` untracked

## Useful commands

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose exec backend python -m pytest backend/tests -q
docker compose exec frontend npm run build
docker compose down
```

## Production guidance

The checked-in Compose file is for local development, not production. For production:

- build immutable images
- inject secrets from a secret manager or deployment platform
- place the app behind HTTPS and a reverse proxy
- restrict CORS to deployed frontend origins
- run MongoDB with production-grade authentication and backup settings
