import os
import logging
import time
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from jose import jwt, JWTError

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent

# Load project-level env first, then backend/.env for local backend-only overrides.
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")

# Normalize Mongo env naming so startup validation and DB access stay consistent.
if not os.getenv("MONGODB_URI") and os.getenv("MONGO_URI"):
    os.environ["MONGODB_URI"] = os.getenv("MONGO_URI")
if not os.getenv("MONGO_URI") and os.getenv("MONGODB_URI"):
    os.environ["MONGO_URI"] = os.getenv("MONGODB_URI")

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError

from backend.app.api import (
    adaptive,
    auth,
    users,
    resources,
    subjects,
    chapters,
    lessons,
    learning_path,
    learning_paths,
    progress,
    ask,
    recommendations,
    feedback,
    kt,
    path_refinement,
    concepts,
    exercise_attempts,
    analytics,
)
from backend.app.services.event_logging_service import event_logging_service

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

    optional_missing = [var for var in ["GEMINI_API_KEY"] if not os.getenv(var)]
    if optional_missing:
        logger.warning(f"⚠️  Missing optional env vars: {', '.join(optional_missing)}")

    logger.info("✅ Required environment variables loaded")


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

    # Color-code based on status
    if status_code >= 500:
        level = "ERROR"
    elif status_code >= 400:
        level = "WARNING"
    else:
        level = "INFO"

    logger.log(
        getattr(logging, level),
        f"{path} | Status: {status_code} | Time: {duration:.3f}s",
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
    # Startup
    logger.info("🚀 Starting Backend API...")
    validate_env()
    logger.info("✅ Backend API started successfully")

    yield

    # Shutdown
    logger.info("🛑 Shutting down Backend API...")


# =========================
# INIT APP
# =========================
app = FastAPI(
    title="AI Personalized Learning Path System",
    description="Backend cho hệ thống cá nhân hóa lộ trình học tập sử dụng AI + RAG",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# =========================
# MIDDLEWARE STACK
# =========================
# Request/Response logging middleware
app.middleware("http")(logging_middleware)

# CORS middleware
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
    logger.warning(f"Validation error: {exc}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation error", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
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
app.include_router(learning_path.router, prefix="/api")
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


# =========================
# HEALTH CHECK ENDPOINTS
# =========================
@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Backend hệ thống cá nhân hóa lộ trình học tập",
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
    return {
        "status": "healthy",
        "service": "AI Learning Path Backend",
        "timestamp": time.time(),
    }


@app.get("/api/ready")
async def readiness_check():
    """Readiness check - verify dependencies are available."""
    try:
        from backend.app.database.mongo import get_db

        db = get_db()

        # Test database connection
        db.command("ping")

        return {"status": "ready", "database": "connected"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "error": str(e)},
        )
