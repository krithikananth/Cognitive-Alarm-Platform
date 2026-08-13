"""
Application configuration module using Pydantic BaseSettings.

Provides centralized configuration management with environment variable support,
type validation, and sensible defaults for development and production environments.
"""

import logging
from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Stable, obviously-insecure key used ONLY when ENVIRONMENT is not production.
# It is deliberately constant so development sessions survive a restart, and it
# is rejected outright in production by ``_validate_secret_key``.
DEV_SECRET_KEY = "insecure-development-secret-key-change-me-before-production"

# Placeholder values that must never sign production tokens.
WEAK_SECRET_KEYS = {
    DEV_SECRET_KEY,
    "secret",
    "secretkey",
    "secret_key",
    "changeme",
    "change-me",
    "please-change-me",
    "your-secret-key",
    "your-secret-key-here",
    "test",
    "testing",
    "development",
    "supersecret",
    "password",
}

MIN_SECRET_KEY_LENGTH = 32


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
        AGGREGATE_CACHE_ENABLED: Whether admin/analytics aggregates are cached.
        AGGREGATE_CACHE_TTL_SECONDS: TTL for cached aggregate payloads (0 disables).
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
    # development | test | production — production enforces a real SECRET_KEY
    # and secure cookies.
    ENVIRONMENT: str = "development"

    # ── Security ──────────────────────────────────────────────────────
    # No generated default: a random per-process key silently invalidates every
    # issued token on restart. Production must supply one; other environments
    # fall back to a constant, clearly-insecure development key.
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # ── Auth cookies (HttpOnly session transport for the SPA) ─────────
    AUTH_COOKIE_ENABLED: bool = True
    ACCESS_COOKIE_NAME: str = "icap_access_token"
    REFRESH_COOKIE_NAME: str = "icap_refresh_token"
    # None → derived from ENVIRONMENT (Secure is mandatory in production).
    AUTH_COOKIE_SECURE: Optional[bool] = None
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: Optional[str] = None

    # ── OAuth2 anti-CSRF state ────────────────────────────────────────
    OAUTH_STATE_COOKIE_NAME: str = "icap_oauth_state"
    OAUTH_STATE_TTL_SECONDS: int = 600

    # ── Interactive API documentation ─────────────────────────────────
    # None → derived from ENVIRONMENT (served everywhere except production).
    ENABLE_API_DOCS: Optional[bool] = None

    # ── Brute-force / abuse protection ────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    LOGIN_MAX_ATTEMPTS: int = 5
    # Looser per-address cap so shared/NAT addresses do not lock out everyone.
    LOGIN_IP_MAX_ATTEMPTS: int = 20
    LOGIN_ATTEMPT_WINDOW_SECONDS: int = 300
    LOGIN_LOCKOUT_SECONDS: int = 900
    PASSWORD_RESET_MAX_REQUESTS: int = 3
    PASSWORD_RESET_WINDOW_SECONDS: int = 900

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

    # ── Aggregate read cache ──────────────────────────────────────────
    # Platform-wide admin aggregates and the pandas-backed behavioural
    # analytics are identical for every caller within a few seconds. The TTL
    # is short on purpose: long enough to absorb a dashboard's burst of
    # parallel requests, short enough that an operator's own change shows up.
    # Set the TTL to 0 to disable the cache entirely.
    AGGREGATE_CACHE_ENABLED: bool = True
    AGGREGATE_CACHE_TTL_SECONDS: int = 30

    # ── Logging ───────────────────────────────────────────────────────
    # Without an explicit configuration the root logger has no handler, so
    # Python's lastResort handler applies and every logger.info() call in the
    # codebase is discarded. configure_logging() installs the settings below.
    LOG_LEVEL: str = "INFO"
    # json → one structured object per line (ship straight to an aggregator);
    # console → human-readable, for local development.
    LOG_FORMAT: str = "json"
    LOG_SERVICE_NAME: str = "icap-backend"
    # stdout is the container/orchestrator contract, so this stays on by
    # default; turn it off locally to keep the dev terminal readable while the
    # rotating file keeps the full record.
    LOG_TO_CONSOLE: bool = True
    # Size-based rotation so logs persist beyond the container's log ring
    # buffer. Degrades to stdout-only when the directory is not writable.
    LOG_TO_FILE: bool = True
    LOG_DIR: str = "logs"
    LOG_FILE_NAME: str = "icap.log"
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUP_COUNT: int = 5
    # Structured one-line-per-request access log carrying the correlation id.
    LOG_ACCESS_ENABLED: bool = True
    # Chatty third parties get their own floor so app logs can run at INFO.
    LOG_SQL_LEVEL: str = "WARNING"
    LOG_SCHEDULER_LEVEL: str = "WARNING"
    # Correlation id: honoured on the way in, echoed on the way out.
    REQUEST_ID_HEADER: str = "X-Request-ID"

    # ── Monitoring / alerting on the measured metrics ─────────────────
    # Thresholds evaluated against the existing /system/metrics reservoirs.
    # Nothing new is measured here — this only decides when a reading is bad
    # enough to page someone.
    METRICS_ALERTS_ENABLED: bool = True
    METRICS_ALERT_INTERVAL_SECONDS: int = 60
    METRICS_ALERT_P95_MS: float = 400.0
    METRICS_ALERT_ERROR_RATE_PCT: float = 5.0
    # A route needs this many observations before a percentile means anything.
    METRICS_ALERT_MIN_SAMPLES: int = 20
    # Breaching by this factor escalates warning → critical.
    METRICS_ALERT_CRITICAL_MULTIPLIER: float = 2.0
    # Re-notification interval while an alert stays firing (anti-flapping).
    METRICS_ALERT_COOLDOWN_SECONDS: int = 900
    METRICS_ALERT_WEBHOOK_URL: Optional[str] = None
    METRICS_ALERT_WEBHOOK_TIMEOUT_SECONDS: float = 3.0
    # Bearer token letting a Prometheus scraper read /system/metrics/prometheus
    # without an admin session. Unset → admins only.
    METRICS_SCRAPE_TOKEN: Optional[str] = None

    # ── Browser error reporting ───────────────────────────────────────
    CLIENT_ERROR_LOGGING_ENABLED: bool = True
    CLIENT_ERROR_MAX_PER_WINDOW: int = 30
    CLIENT_ERROR_WINDOW_SECONDS: int = 60

    # ── API latency measurement ───────────────────────────────────────
    # Per-request timing, stamped on responses as X-Process-Time and kept in a
    # bounded per-process reservoir for GET /system/metrics.
    REQUEST_METRICS_ENABLED: bool = True
    REQUEST_METRICS_SAMPLE_SIZE: int = 500

    # ── Challenge generation latency ──────────────────────────────────
    # Generation runs on the critical path of a ringing alarm, so every call
    # is timed and kept per (type, difficulty, source) for GET /system/metrics.
    CHALLENGE_METRICS_ENABLED: bool = True
    CHALLENGE_METRICS_SAMPLE_SIZE: int = 500
    # p95 budget in milliseconds; mirrors CHALLENGE_BUDGET_MS in perf/subsystems.py
    CHALLENGE_GENERATION_BUDGET_MS: float = 50.0

    # ── Database connection pool ──────────────────────────────────────
    # Every concurrent request holds a connection for its whole handler, so
    # the pool is the hard ceiling on concurrent users. Total capacity is
    # DB_POOL_SIZE + DB_MAX_OVERFLOW; requests beyond that wait up to
    # DB_POOL_TIMEOUT_SECONDS and then fail. Ignored on SQLite.
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800

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

    @field_validator("LOG_LEVEL", "LOG_SQL_LEVEL", "LOG_SCHEDULER_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        """Reject unknown level names at boot rather than silencing logs."""
        level = str(v).strip().upper()
        if level not in logging._nameToLevel:
            raise ValueError(
                f"Invalid log level {v!r}; expected one of "
                f"{sorted(logging._nameToLevel)}"
            )
        return level

    @field_validator("LOG_FORMAT")
    @classmethod
    def _validate_log_format(cls, v: str) -> str:
        fmt = str(v).strip().lower()
        if fmt not in {"json", "console"}:
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        return fmt

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

    # ── AI challenge generation ───────────────────────────────────
    # Cognitive puzzles are generated by Gemini when GEMINI_API_KEY is set;
    # the deterministic procedural generators remain the fallback so an
    # unavailable provider can never block a ringing alarm.
    AI_CHALLENGE_ENABLED: bool = True
    AI_CHALLENGE_MODEL: str = "gemini-1.5-flash"
    # Hard ceiling on the provider call — the alarm UI is waiting on it.
    AI_CHALLENGE_TIMEOUT_SECONDS: int = 6
    # After a provider failure, skip AI generation for this long so a broken
    # key or outage does not add latency to every alarm.
    AI_CHALLENGE_COOLDOWN_SECONDS: int = 300

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

    # ── Derived security helpers ──────────────────────────────────────

    @property
    def is_production(self) -> bool:
        """Whether the app runs with production security requirements."""
        return str(self.ENVIRONMENT or "").strip().lower() in (
            "production",
            "prod",
        )

    @property
    def cookies_secure(self) -> bool:
        """Whether auth cookies carry the ``Secure`` attribute."""
        if self.AUTH_COOKIE_SECURE is not None:
            return self.AUTH_COOKIE_SECURE
        return self.is_production

    @property
    def api_docs_enabled(self) -> bool:
        """Whether Swagger UI / ReDoc / the OpenAPI schema are served.

        Off in production by default: the schema is a complete map of every
        route, parameter and model, which is reconnaissance material an
        unauthenticated visitor has no need for. Can be re-enabled explicitly
        for an internal deployment.
        """
        if self.ENABLE_API_DOCS is not None:
            return self.ENABLE_API_DOCS
        return not self.is_production

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """Reject weak/missing signing keys in production, warn elsewhere."""
        key = (self.SECRET_KEY or "").strip()

        if self.is_production:
            if not key:
                raise ValueError(
                    "SECRET_KEY must be set in production. Generate one with "
                    "`python -c \"import secrets; print(secrets.token_urlsafe(64))\"`."
                )
            if len(key) < MIN_SECRET_KEY_LENGTH:
                raise ValueError(
                    f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} "
                    "characters in production."
                )
            if key.lower() in {weak.lower() for weak in WEAK_SECRET_KEYS}:
                raise ValueError(
                    "SECRET_KEY is a known placeholder value and cannot be used "
                    "in production."
                )
            if not self.cookies_secure:
                raise ValueError(
                    "AUTH_COOKIE_SECURE cannot be disabled in production."
                )
        elif not key:
            logger.warning(
                "SECRET_KEY is not set — falling back to the insecure "
                "development key. Set SECRET_KEY before deploying."
            )
            self.SECRET_KEY = DEV_SECRET_KEY

        return self


# Singleton settings instance used across the application
settings = Settings()
