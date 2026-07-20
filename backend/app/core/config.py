"""
Application configuration module using Pydantic BaseSettings.

Provides centralized configuration management with environment variable support,
type validation, and sensible defaults for development and production environments.
"""

import secrets
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and .env file.

    Attributes:
        PROJECT_NAME: Display name of the application.
        VERSION: Current semantic version of the API.
        API_V1_STR: URL prefix for API version 1 endpoints.
        SECRET_KEY: Cryptographic key for JWT signing. Must be changed in production.
        ALGORITHM: JWT signing algorithm (HS256).
        ACCESS_TOKEN_EXPIRE_MINUTES: Lifetime of access tokens in minutes.
        REFRESH_TOKEN_EXPIRE_DAYS: Lifetime of refresh tokens in days.
        DATABASE_URL: SQLAlchemy database connection string.
        REDIS_ENABLED: Whether recommendation caching via Redis is attempted.
        REDIS_URL: Redis connection URL (e.g. redis://localhost:6379/0).
        REDIS_SOCKET_TIMEOUT_SECONDS: Short connect/read timeout for soft-fail.
        RECOMMENDATION_CACHE_TTL_SECONDS: Safety TTL for cached recommendation payloads.
        CORS_ORIGINS: List of allowed CORS origins for cross-origin requests.
        FRONTEND_URL: SPA origin used for OAuth callback redirects.
        OAUTH2_GOOGLE_CLIENT_ID: Google OAuth2 client ID for social login.
        OAUTH2_GOOGLE_CLIENT_SECRET: Google OAuth2 client secret for social login.
        OAUTH2_GOOGLE_REDIRECT_URI: Backend callback URL registered with Google.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Project Metadata ──────────────────────────────────────────────
    PROJECT_NAME: str = "Intelligent Cognitive Alarm Platform"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # ── Security ──────────────────────────────────────────────────────
    SECRET_KEY: str = secrets.token_urlsafe(64)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ──────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./icap.db"

    # ── Adaptive difficulty ───────────────────────────────────────────
    # Consecutive successes/failures required before difficulty ±1.
    ADAPTIVE_STREAK_THRESHOLD: int = 5

    # ── Redis / recommendation cache ──────────────────────────────────
    # When REDIS_ENABLED is false or Redis is unreachable, recommendations
    # recompute on every request (graceful fallback).
    REDIS_ENABLED: bool = True
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 0.5
    RECOMMENDATION_CACHE_TTL_SECONDS: int = 300

    # ── CORS ──────────────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:5173",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: object) -> List[str]:
        """Parse CORS origins from a comma-separated string or JSON list."""
        if isinstance(v, str):
            # Handle JSON-encoded list or comma-separated string
            if v.startswith("["):
                import json
                return json.loads(v)
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        if isinstance(v, list):
            return v
        raise ValueError(
            "CORS_ORIGINS must be a JSON list string or comma-separated string"
        )

    # ── Frontend ──────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"

    # ── External APIs ─────────────────────────────────────────────────
    OAUTH2_GOOGLE_CLIENT_ID: Optional[str] = None
    OAUTH2_GOOGLE_CLIENT_SECRET: Optional[str] = None
    OAUTH2_GOOGLE_REDIRECT_URI: str = (
        "http://localhost:8000/api/v1/auth/oauth/google/callback"
    )
    GEMINI_API_KEY: Optional[str] = None


# Singleton settings instance used across the application
settings = Settings()
