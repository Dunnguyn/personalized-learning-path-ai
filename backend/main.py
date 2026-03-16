import os
import logging
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from backend.app.api import (
    auth,
    users,
    resources,
    learning_path,
    lesson_quiz,
    progress,
    ask,
    recommendations,
    concepts,
    rag
)

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =========================
# ENVIRONMENT VALIDATION
# =========================
def validate_env():
    """Validate required environment variables."""
    required_vars = ["MONGODB_URI"]
    missing = [var for var in required_vars if not os.getenv(var)]
    secret_key = os.getenv("SECRET_KEY")

    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
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
    
    response = await call_next(request)
    
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
        f"{path} | Status: {status_code} | Time: {duration:.3f}s"
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
    lifespan=lifespan
)

# =========================
# MIDDLEWARE STACK
# =========================
# Request/Response logging middleware
app.middleware("http")(logging_middleware)

# CORS middleware
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000").split(",")
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
        content={"detail": "Validation error", "errors": exc.errors()}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )

# =========================
# REGISTER ROUTERS
# =========================
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(resources.router, prefix="/api")
app.include_router(learning_path.router, prefix="/api")
app.include_router(lesson_quiz.router, prefix="/api")
app.include_router(progress.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(recommendations.router, prefix="/api")
app.include_router(concepts.router, prefix="/api")
app.include_router(rag.router, prefix="/api")

# =========================
# HEALTH CHECK ENDPOINTS
# =========================
@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Backend hệ thống cá nhân hóa lộ trình học tập",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "AI Learning Path Backend",
        "timestamp": time.time()
    }


@app.get("/api/ready")
async def readiness_check():
    """Readiness check - verify dependencies are available."""
    try:
        from backend.app.database.mongo import get_db
        db = get_db()
        
        # Test database connection
        db.command("ping")
        
        return {
            "status": "ready",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "error": str(e)}
        )
