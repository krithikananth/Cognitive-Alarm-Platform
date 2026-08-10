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
        PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: Lifetime of password-reset JWTs.
        EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: Lifetime of email-verification JWTs.
        DATABASE_URL: SQLAlchemy database connection string.
        REDIS_ENABLED: Whether recommendation caching via Redis is attempted.
        REDIS_URL: Redis connection URL (e.g. redis://localhost:6379/0).
        REDIS_SOCKET_TIMEOUT_SECONDS: Short connect/read timeout for soft-fail.
        RECOMMENDATION_CACHE_TTL_SECONDS: Safety TTL for cached recommendation payloads.
        CORS_ORIGINS: List of allowed CORS origins for cross-origin requests.
        FRONTEND_URL: SPA origin used for OAuth and email-link redirects.
        SMTP_HOST: SMTP server hostname (optional; emails logged when unset).
        SMTP_PORT: SMTP server port.
        SMTP_USER: SMTP username.
        SMTP_PASSWORD: SMTP password.
        SMTP_FROM_EMAIL: From address for outbound mail.
        SMTP_FROM_NAME: Display name for outbound mail.
        SMTP_USE_TLS: Whether to issue STARTTLS after connecting.
        OAUTH2_GOOGLE_CLIENT_ID: Google OAuth2 client ID for social login.
        OAUTH2_GOOGLE_CLIENT_SECRET: Google OAuth2 client secret for social login.
        OAUTH2_GOOGLE_REDIRECT_URI: Backend callback URL registered with Google.
        FCM_ENABLED: Master switch for Firebase Cloud Messaging push delivery.
        FIREBASE_CREDENTIALS_PATH: Path to the service-account JSON file.
        FIREBASE_CREDENTIALS_JSON: Inline service-account JSON (raw or base64).
        NOTIFICATION_PROCESSING_INTERVAL_SECONDS: Queue drain cadence.
        NOTIFICATION_RETRY_INTERVAL_SECONDS: Failed-push retry sweep cadence.
        NOTIFICATION_MAX_PUSH_ATTEMPTS: Attempts before a push is given up on.
        NOTIFICATION_RETRY_BACKOFF_SECONDS: Exponential backoff base for retries.
        ALARM_DISPATCH_ENABLED: Master switch for server-side alarm ringing.
        ALARM_DISPATCH_INTERVAL_SECONDS: How often due alarms are swept.
        ALARM_DISPATCH_MAX_LATENESS_MINUTES: Catch-up window after downtime;
            alarms later than this are never pushed.
        ALARM_MISSED_ROLLOVER_MINUTES: Age at which an unattended alarm is
            advanced to its next occurrence (or retired, if one-time).
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
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Optional first-run administrator. No account is seeded when unset.
    INITIAL_ADMIN_EMAIL: Optional[str] = None
    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: Optional[str] = None

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

    # ── Email / SMTP (optional — links are logged when unset) ─────────
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: str = "Intelligent Cognitive Alarm"
    SMTP_USE_TLS: bool = True

    # ── External APIs ─────────────────────────────────────────────────
    OAUTH2_GOOGLE_CLIENT_ID: Optional[str] = None
    OAUTH2_GOOGLE_CLIENT_SECRET: Optional[str] = None
    OAUTH2_GOOGLE_REDIRECT_URI: str = (
        "http://localhost:8000/api/v1/auth/oauth/google/callback"
    )
    GEMINI_API_KEY: Optional[str] = None

    # ── Firebase Cloud Messaging ──────────────────────────────────
    FCM_ENABLED: bool = False
    FIREBASE_CREDENTIALS_PATH: Optional[str] = None
    # Inline service-account JSON (raw or base64) for deployments without a
    # writable filesystem. Takes precedence over FIREBASE_CREDENTIALS_PATH.
    FIREBASE_CREDENTIALS_JSON: Optional[str] = None

    # ── Notification queue / delivery retry ───────────────────────
    NOTIFICATION_PROCESSING_INTERVAL_SECONDS: int = 60
    NOTIFICATION_RETRY_INTERVAL_SECONDS: int = 300
    NOTIFICATION_MAX_PUSH_ATTEMPTS: int = 3
    NOTIFICATION_RETRY_BACKOFF_SECONDS: int = 300

    # ── Server-side alarm dispatch ────────────────────────────────
    # Rings alarms from the backend so a closed browser tab cannot cause a
    # missed wake-up. The frontend ring experience is unchanged.
    ALARM_DISPATCH_ENABLED: bool = True
    ALARM_DISPATCH_INTERVAL_SECONDS: int = 20
    ALARM_DISPATCH_MAX_LATENESS_MINUTES: int = 15
    ALARM_MISSED_ROLLOVER_MINUTES: int = 60


# Singleton settings instance used across the application
settings = Settings()
