# Docker Guide

This repository includes a development-oriented Docker Compose setup for the backend, frontend, MongoDB, and an optional Mongo Express instance.

## Prerequisites

- Docker 24+
- Docker Compose v2
- A local `.env` copied from `.env.example`

## Start the stack

```bash
copy .env.example .env
# Edit .env: set SECRET_KEY (32+ random characters) and local MongoDB passwords.
docker compose config --quiet
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

The frontend uses Node 22 and installs the locked dependency set with `npm ci`.
MongoDB uses the official `mongo:7.0` image; the backend authenticates the root
user against `admin`. Process/Compose variables take precedence over local `.env`
files. Backend tests are local-only and are not included in a fresh clone.

## Important security notes

- Set a real `SECRET_KEY` in `.env` before starting the backend
- Do not use the insecure direct password reset flow in public environments
- Treat Docker Compose defaults as local development only
- Keep `.env` untracked

## Useful commands

```bash
docker compose logs -f backend
docker compose logs -f frontend
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
