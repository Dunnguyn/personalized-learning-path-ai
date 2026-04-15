import logging
import os
import time
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# When this file is executed directly from backend/, add the project root so
# imports like backend.app.* resolve the same way they do under uvicorn.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load backend/.env first, then project-level .env so the repo root file wins.
# `override=True` ensures stale variables already present in the terminal session
# do not keep masking values updated in .env files.
load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Normalize Mongo env naming so startup validation and DB access stay consistent.
if not os.getenv("MONGODB_URI") and os.getenv("MONGO_URI"):
    os.environ["MONGODB_URI"] = os.getenv("MONGO_URI")
if not os.getenv("MONGO_URI") and os.getenv("MONGODB_URI"):
    os.environ["MONGO_URI"] = os.getenv("MONGODB_URI")

from backend.app.ai_module.embedding import embedding_service
from backend.app.api import (
    adaptive,
    analytics,
    ask,
    auth,
    chapters,
    concepts,
    diagnostic,
    exercise_attempts,
    feedback,
    kt,
    learner_profile,
    learning_paths,
    lessons,
    path_refinement,
    progress,
    recommendations,
    resources,
    subjects,
    users,
)
from backend.app.api.auth import require_admin_user
from backend.app.repositories import ResourceChunkRepository
from backend.app.services.event_logging_service import event_logging_service
from backend.app.services.ingestion_service import ingestion_service
from backend.app.utils.gemini import has_configured_gemini_api_keys

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =========================
# ENVIRONMENT VALIDATION
# =========================
def validate_env():
    """Validate required environment variables."""
    mongo_uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    secret_key = os.getenv("SECRET_KEY")

    if not mongo_uri:
        raise RuntimeError("Missing required env var: MONGODB_URI or MONGO_URI")
    if not secret_key or secret_key == "CHANGE_THIS_SECRET_KEY":
        raise RuntimeError("SECRET_KEY must be configured with a non-default value")

    optional_missing = []
    if not has_configured_gemini_api_keys():
        optional_missing.append("GEMINI_API_KEY or GEMINI_API_KEYS")
    if optional_missing:
        logger.warning("Missing optional env vars: %s", ", ".join(optional_missing))

    logger.info("Required environment variables loaded")


def get_ai_stack_snapshot():
    """Return runtime status for embedding/vector retrieval infrastructure."""
    chunk_repository = ResourceChunkRepository()
    embedding_status = embedding_service.backend_status()
    return {
        "ready": embedding_status.get("backend") != "hash_fallback"
        or not embedding_status.get("strict_mode"),
        "embedding": embedding_status,
        "vector_store": {
            "available": embedding_service.vector_store.available,
        },
        "chunks": {
            "total": chunk_repository.count_total(),
            "with_embeddings": chunk_repository.count_with_embeddings(),
            "without_embeddings": chunk_repository.count_without_embeddings(),
            "by_backend": chunk_repository.count_by_embedding_backend(),
        },
    }


# =========================
# MIDDLEWARE DEFINITIONS
# =========================
async def logging_middleware(request: Request, call_next):
    """Log request/response with timing."""
    start_time = time.time()
    path = f"{request.method} {request.url.path}"
    request_path = request.url.path

    session_id = request.headers.get("x-session-id") or request.cookies.get(
        "session_id"
    )
    auth_header = request.headers.get("authorization")
    user_id = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        try:
            payload = jwt.decode(
                token,
                os.getenv("SECRET_KEY") or "CHANGE_THIS_SECRET_KEY",
                algorithms=["HS256"],
            )
            user_id = payload.get("sub")
        except JWTError:
            user_id = None

    try:
        response = await call_next(request)
    except Exception as exc:
        duration = time.time() - start_time
        event_logging_service.log_api_event(
            event_type="api_failed",
            method=request.method,
            path=request_path,
            status_code=500,
            duration_ms=int(duration * 1000),
            user_id=user_id,
            session_id=session_id,
            error_code=exc.__class__.__name__,
        )
        raise

    duration = time.time() - start_time
    status_code = response.status_code

    if status_code >= 500:
        level = "ERROR"
    elif status_code >= 400:
        level = "WARNING"
    else:
        level = "INFO"

    logger.log(
        getattr(logging, level),
        "%s | Status: %s | Time: %.3fs",
        path,
        status_code,
        duration,
    )

    event_logging_service.log_api_event(
        event_type="api_called" if status_code < 400 else "api_failed",
        method=request.method,
        path=request_path,
        status_code=status_code,
        duration_ms=int(duration * 1000),
        user_id=user_id,
        session_id=session_id,
        error_code=None if status_code < 400 else str(status_code),
    )

    return response


# =========================
# LIFESPAN EVENTS
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Backend API...")
    validate_env()
    embedding_service.validate_runtime()
    if os.getenv("EMBEDDING_BACKFILL_ON_STARTUP", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            limit = int(os.getenv("EMBEDDING_BACKFILL_LIMIT", "500"))
            summary = ingestion_service.backfill_embeddings(limit=limit)
            logger.info("Embedding backfill on startup: %s", summary)
        except Exception as exc:
            logger.warning("Embedding backfill on startup skipped: %s", exc)
    logger.info("Backend API started successfully")

    yield

    logger.info("Shutting down Backend API...")


# =========================
# INIT APP
# =========================
app = FastAPI(
    title="AI Personalized Learning Path System",
    description="Backend cho he thong ca nhan hoa lo trinh hoc tap su dung AI + RAG",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# =========================
# MIDDLEWARE STACK
# =========================
app.middleware("http")(logging_middleware)

allowed_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# EXCEPTION HANDLERS
# =========================
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors gracefully."""
    logger.warning("Validation error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# =========================
# REGISTER ROUTERS
# =========================
app.include_router(auth.router, prefix="/api")
app.include_router(adaptive.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(subjects.router, prefix="/api")
app.include_router(chapters.router, prefix="/api")
app.include_router(lessons.router, prefix="/api")
app.include_router(learning_paths.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(kt.router, prefix="/api")
app.include_router(path_refinement.router, prefix="/api")
app.include_router(concepts.router, prefix="/api")
app.include_router(exercise_attempts.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(learner_profile.router, prefix="/api")
app.include_router(diagnostic.router, prefix="/api")


# =========================
# HEALTH CHECK ENDPOINTS
# =========================
@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Backend he thong ca nhan hoa lo trinh hoc tap",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/docs", include_in_schema=False)
async def docs_redirect():
    """Redirect the conventional Swagger URL to the API-prefixed docs route."""
    return RedirectResponse(
        url="/api/docs", status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


@app.get("/openapi.json", include_in_schema=False)
async def openapi_redirect():
    """Redirect the conventional OpenAPI URL to the API-prefixed schema route."""
    return RedirectResponse(
        url="/api/openapi.json", status_code=status.HTTP_307_TEMPORARY_REDIRECT
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring."""
    ai_snapshot = get_ai_stack_snapshot()
    return {
        "status": "healthy",
        "service": "AI Learning Path Backend",
        "timestamp": time.time(),
        "ai": {
            "backend": ai_snapshot["embedding"].get("backend"),
            "strict_mode": ai_snapshot["embedding"].get("strict_mode"),
            "vector_store_available": ai_snapshot["vector_store"].get("available"),
        },
    }


@app.get("/api/ready")
async def readiness_check():
    """Readiness check - verify dependencies are available."""
    try:
        from backend.app.database.mongo import get_db

        db = get_db()
        db.command("ping")

        ai_snapshot = get_ai_stack_snapshot()
        if not ai_snapshot["ready"]:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "not_ready",
                    "error": "AI embedding backend is still using hash_fallback.",
                    "ai": ai_snapshot,
                },
            )

        return {"status": "ready", "database": "connected", "ai": ai_snapshot}
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "error": str(exc)},
        )


@app.get("/api/health/ai")
async def ai_health_check():
    """Health snapshot for the semantic retrieval stack."""
    return get_ai_stack_snapshot()


@app.get("/api/debug/ai")
async def ai_debug_snapshot():
    """Debug snapshot for embedding/vector infrastructure."""
    snapshot = get_ai_stack_snapshot()
    snapshot["timestamp"] = time.time()
    return snapshot


@app.post("/api/debug/ai/backfill")
async def trigger_ai_embedding_backfill(
    limit: int = Query(200, ge=1, le=5000),
    current_user=Depends(require_admin_user),
):
    """Admin endpoint to backfill non-semantic or missing chunk embeddings."""
    del current_user
    return ingestion_service.backfill_embeddings(limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
