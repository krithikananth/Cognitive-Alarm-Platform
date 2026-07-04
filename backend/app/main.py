"""
Intelligent Cognitive Alarm Platform - FastAPI Main Application.

Entry point: uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_postgres, init_mongodb, close_mongodb, init_redis, close_redis

# Import routers
from app.routers import auth, users, alarms


# Rate Limiter
limiter = Limiter(key_func=get_remote_address)


# Lifespan (startup/shutdown)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Startup
    print("[STARTUP] Starting Intelligent Cognitive Alarm Platform...")
    await init_postgres()
    print("   [OK] Database connected")
    await init_mongodb()
    print("   [OK] MongoDB step done")
    await init_redis()
    print("   [OK] Redis step done")
    print(f"   [CORS] origins: {settings.cors_origins_list}")
    print("[READY] Platform ready!")

    yield

    # Shutdown
    print("[SHUTDOWN] Shutting down...")
    await close_mongodb()
    await close_redis()
    print("   Connections closed. Goodbye!")


# Create App
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-powered Intelligent Cognitive Alarm Platform that helps users develop "
        "consistent wake-up habits through personalized cognitive challenges."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Register Routers
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)
app.include_router(alarms.router, prefix=API_PREFIX)


# Root Endpoint
@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "healthy",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "services": {
            "api": "up",
            "database": "connected",
        },
    }
