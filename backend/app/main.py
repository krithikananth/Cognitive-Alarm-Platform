"""
FastAPI application entry point for the Intelligent Cognitive Alarm Platform.

Creates and configures the main application instance with CORS middleware,
API routing, and database initialization on startup.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging_config import configure_logging, logging_status
from app.core.request_metrics import RequestTimingMiddleware, configure_registry
from app.core.challenge_metrics import (
    configure_registry as configure_challenge_registry,
)
from app.middleware.request_context import RequestContextMiddleware
from app.schemas.common import HealthResponse, RootResponse
from app.api.v1.router import api_router
from app.db.base import Base
from app.db.session import engine

# Installed before anything else so import-time and startup records are
# captured. Without it the root logger has no handler and every logger.info()
# call in the codebase is discarded.
configure_logging()
logger = logging.getLogger(__name__)

# Import all models so they are registered with Base.metadata
from app.models import user, profile, alarm  # noqa: F401
from app.models import challenge_session  # noqa: F401
from app.models import challenge_delivery  # noqa: F401
from app.models import recommendation_feedback  # noqa: F401
from app.models import alarm_wake_event  # noqa: F401
from app.models import alarm_snooze_event  # noqa: F401
from app.models import analytics_event  # noqa: F401
from app.models import notification  # noqa: F401
from app.models import system_settings  # noqa: F401
from app.models import coach_assignment  # noqa: F401
from app.models import revoked_token  # noqa: F401


def _ensure_sqlite_columns() -> None:
    """Add missing columns/indexes on existing SQLite tables (create_all won't alter)."""
    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    statements = [
        "ALTER TABLE users ADD COLUMN tokens_valid_after DATETIME",
        "ALTER TABLE alarm_challenge_logs ADD COLUMN difficulty VARCHAR(50)",
        "ALTER TABLE alarm_challenge_logs ADD COLUMN challenge_prompt TEXT",
        "ALTER TABLE alarm_challenge_logs ADD COLUMN is_correct BOOLEAN DEFAULT 0",
        "ALTER TABLE alarm_challenge_logs ADD COLUMN points_earned INTEGER DEFAULT 0",
        "ALTER TABLE challenge_sessions ADD COLUMN challenge_type VARCHAR(50) DEFAULT 'math'",
        "ALTER TABLE challenge_sessions ADD COLUMN consecutive_correct INTEGER DEFAULT 0",
        "ALTER TABLE challenge_sessions ADD COLUMN required_correct INTEGER DEFAULT 1",
        "ALTER TABLE challenge_sessions ADD COLUMN total_failed_attempts INTEGER DEFAULT 0",
        "ALTER TABLE challenge_sessions ADD COLUMN escalation_level INTEGER DEFAULT 0",
        "ALTER TABLE challenge_sessions ADD COLUMN verification_token VARCHAR(64)",
        "ALTER TABLE challenge_sessions ADD COLUMN wake_confirmed BOOLEAN DEFAULT 0",
        "ALTER TABLE challenge_sessions ADD COLUMN session_started_at DATETIME",
        "ALTER TABLE alarms ADD COLUMN challenge_difficulty VARCHAR(50) DEFAULT 'medium'",
        # Strict consecutive-streak adaptive difficulty counters
        "ALTER TABLE user_profiles ADD COLUMN consecutive_success_streak "
        "INTEGER DEFAULT 0",
        "ALTER TABLE user_profiles ADD COLUMN consecutive_failure_streak "
        "INTEGER DEFAULT 0",
        "ALTER TABLE user_profiles ADD COLUMN last_adapted_success_streak "
        "INTEGER DEFAULT 0",
        "ALTER TABLE user_profiles ADD COLUMN last_adapted_failure_streak "
        "INTEGER DEFAULT 0",
        # Query indexes for adaptive difficulty / history / stats
        "CREATE INDEX IF NOT EXISTS ix_alarm_challenge_logs_user_id "
        "ON alarm_challenge_logs (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_alarm_challenge_logs_alarm_id "
        "ON alarm_challenge_logs (alarm_id)",
        "CREATE INDEX IF NOT EXISTS ix_alarm_challenge_logs_created_at "
        "ON alarm_challenge_logs (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_alarm_challenge_logs_user_created "
        "ON alarm_challenge_logs (user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_alarm_challenge_logs_alarm_created "
        "ON alarm_challenge_logs (alarm_id, created_at)",
        # Backfill legacy nullables so analytics never see incomplete rows
        "UPDATE alarm_challenge_logs SET difficulty = 'medium' "
        "WHERE difficulty IS NULL OR TRIM(difficulty) = ''",
        "UPDATE alarm_challenge_logs SET challenge_prompt = '' "
        "WHERE challenge_prompt IS NULL",
        "UPDATE alarm_challenge_logs SET challenge_type = 'word_game' "
        "WHERE lower(challenge_type) = 'word'",
        "UPDATE alarm_challenge_logs SET time_taken_seconds = 0 "
        "WHERE time_taken_seconds IS NULL OR time_taken_seconds < 0",
        "UPDATE alarm_challenge_logs SET failed_attempts = 0 "
        "WHERE failed_attempts IS NULL OR failed_attempts < 0",
        "UPDATE alarm_challenge_logs SET points_earned = 0 "
        "WHERE points_earned IS NULL OR points_earned < 0",
        # Notification preference extensions (master toggle / sound / frequency)
        "ALTER TABLE notification_preferences ADD COLUMN notifications_enabled "
        "BOOLEAN DEFAULT 1",
        "ALTER TABLE notification_preferences ADD COLUMN notification_sound "
        "VARCHAR(32) DEFAULT 'default'",
        "ALTER TABLE notification_preferences ADD COLUMN notification_frequency "
        "VARCHAR(32) DEFAULT 'all'",
        # Challenge practice reminders + weekly progress recaps
        "ALTER TABLE notification_preferences ADD COLUMN "
        "challenge_reminders_enabled BOOLEAN NOT NULL DEFAULT 1",
        "ALTER TABLE notification_preferences ADD COLUMN "
        "progress_updates_enabled BOOLEAN NOT NULL DEFAULT 1",
        # Notification delivery tracking / retry bookkeeping
        "ALTER TABLE notifications ADD COLUMN delivered_at DATETIME",
        "ALTER TABLE notifications ADD COLUMN push_attempts INTEGER DEFAULT 0",
        "ALTER TABLE notifications ADD COLUMN email_attempts INTEGER DEFAULT 0",
        "ALTER TABLE notifications ADD COLUMN next_retry_at DATETIME",
        "ALTER TABLE notifications ADD COLUMN last_error VARCHAR(500)",
        "UPDATE notifications SET push_attempts = 0 WHERE push_attempts IS NULL",
        "UPDATE notifications SET email_attempts = 0 WHERE email_attempts IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_notifications_retry "
        "ON notifications (next_retry_at)",
        # Device token health / invalid-token cleanup bookkeeping
        "ALTER TABLE user_device_tokens ADD COLUMN last_success_at DATETIME",
        "ALTER TABLE user_device_tokens ADD COLUMN failure_count INTEGER DEFAULT 0",
        "ALTER TABLE user_device_tokens ADD COLUMN deactivated_at DATETIME",
        "ALTER TABLE user_device_tokens ADD COLUMN deactivated_reason VARCHAR(255)",
        "UPDATE user_device_tokens SET failure_count = 0 "
        "WHERE failure_count IS NULL",
        # Server-side alarm dispatch bookkeeping
        "ALTER TABLE alarms ADD COLUMN last_notified_trigger_at DATETIME",
        "CREATE INDEX IF NOT EXISTS ix_alarms_active_next_trigger "
        "ON alarms (is_active, next_trigger_at)",
        # One-time alarms keep their calendar date across edits / re-enables
        "ALTER TABLE alarms ADD COLUMN one_time_date DATE",
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.exec_driver_sql(sql)
            except Exception:
                # Column already exists / statement not applicable
                pass
        # adapted_difficulty must use enum NAMES (MEDIUM) to match
        # difficulty_preference / SQLAlchemy Enum(DifficultyPreference).
        try:
            conn.exec_driver_sql(
                "ALTER TABLE user_profiles ADD COLUMN adapted_difficulty "
                "VARCHAR(50) DEFAULT 'MEDIUM'"
            )
            conn.exec_driver_sql(
                "UPDATE user_profiles "
                "SET adapted_difficulty = difficulty_preference"
            )
        except Exception:
            pass
        # Repair rows seeded with lowercase .value ('medium') instead of name.
        # Exact lowercase only — do not touch valid names like MEDIUM/HARD.
        try:
            conn.exec_driver_sql(
                "UPDATE user_profiles "
                "SET adapted_difficulty = difficulty_preference "
                "WHERE adapted_difficulty IS NULL "
                "OR TRIM(adapted_difficulty) = '' "
                "OR adapted_difficulty IN "
                "('beginner','easy','medium','hard','expert')"
            )
        except Exception:
            pass


def _repair_attempt_logs_on_startup() -> None:
    """Normalize any remaining dirty attempt-log rows after schema ensure."""
    from app.db.session import SessionLocal
    from app.services.attempt_log_service import AttemptLogService

    db = SessionLocal()
    try:
        result = AttemptLogService.repair_logs(db, commit=True)
        repaired = result.get("repaired_rows", 0)
        if repaired:
            logger.info(
                "Attempt logs repaired",
                extra={"event": "startup.attempt_log_repair", "rows": repaired},
            )
    except Exception as e:
        db.rollback()
        logger.warning(
            "Attempt-log repair skipped: %s",
            e,
            extra={"event": "startup.attempt_log_repair_failed"},
        )
    finally:
        db.close()


# Paths always allowed during maintenance (mutating methods included).
_MAINTENANCE_ALLOW_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/v1/auth",
    "/api/v1/system",
    "/api/v1/admin",
)


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """Block non-admin mutating requests when maintenance mode is enabled."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        path = request.url.path
        if path == "/" or any(path.startswith(p) for p in _MAINTENANCE_ALLOW_PREFIXES):
            return await call_next(request)

        from app.services.system_settings_service import SystemSettingsService

        enabled, message = SystemSettingsService.get_maintenance_status()
        if not enabled:
            return await call_next(request)

        # Allow admins through (JWT role claim)
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            from app.core.security import verify_token
            from app.models.user import UserRole

            payload = verify_token(auth.split(" ", 1)[1])
            if payload and payload.get("role") == UserRole.ADMIN.value:
                return await call_next(request)

        return JSONResponse(
            status_code=503,
            content={
                "detail": message,
                "maintenance_mode": True,
            },
        )


def _run_startup() -> None:
    """Create database tables and warm caches/schedulers on application startup."""
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    _repair_attempt_logs_on_startup()

    logger.info(
        "Application starting",
        extra={
            "event": "startup.begin",
            "project": settings.PROJECT_NAME,
            **logging_status(),
        },
    )

    # Warm system-settings / maintenance cache
    try:
        from app.db.session import SessionLocal
        from app.services.system_settings_service import SystemSettingsService

        _settings_db = SessionLocal()
        try:
            SystemSettingsService.get_or_create(_settings_db)
        finally:
            _settings_db.close()
    except Exception as e:
        logger.warning(
            "System settings warm-up skipped: %s",
            e,
            extra={"event": "startup.system_settings_failed"},
        )

    # Validate push credentials up front so a broken Firebase setup is
    # visible at boot instead of at the first reminder.
    try:
        from app.services.fcm_service import FCMService

        if FCMService.initialize_at_startup():
            logger.info(
                "Firebase Cloud Messaging ready", extra={"event": "startup.fcm_ready"}
            )
        else:
            logger.warning(
                "Push notifications unavailable: %s",
                FCMService.unavailable_detail(),
                extra={"event": "startup.fcm_unavailable"},
            )
    except Exception as e:
        logger.warning(
            "Firebase Cloud Messaging check failed: %s",
            e,
            extra={"event": "startup.fcm_failed"},
        )

    # Start the APScheduler notification scheduler
    try:
        from app.services.notification_scheduler import (
            start_notification_scheduler,
        )
        start_notification_scheduler()
    except Exception as e:
        logger.warning(
            "Notification scheduler startup skipped: %s",
            e,
            extra={"event": "startup.scheduler_failed"},
        )

    # Seed an explicitly configured first-run administrator.
    if settings.INITIAL_ADMIN_EMAIL and settings.INITIAL_ADMIN_PASSWORD:
        from app.db.session import SessionLocal
        from app.models.user import User, UserRole
        from app.models.profile import UserProfile, DifficultyPreference
        from app.utils.hashing import get_password_hash

        db = SessionLocal()
        try:
            admin = (
                db.query(User)
                .filter(User.email == settings.INITIAL_ADMIN_EMAIL)
                .first()
            )
            if not admin:
                admin = User(
                    email=settings.INITIAL_ADMIN_EMAIL,
                    username=settings.INITIAL_ADMIN_USERNAME,
                    hashed_password=get_password_hash(
                        settings.INITIAL_ADMIN_PASSWORD
                    ),
                    full_name="ICAP Administrator",
                    role=UserRole.ADMIN,
                    is_active=True,
                    is_verified=True,
                )
                db.add(admin)
                db.flush()
                admin_profile = UserProfile(
                    user_id=admin.id,
                    sleep_duration_hours=8.0,
                    timezone="UTC",
                    difficulty_preference=DifficultyPreference.MEDIUM,
                    adapted_difficulty=DifficultyPreference.MEDIUM,
                )
                db.add(admin_profile)
                db.commit()
                logger.info(
                    "Admin user seeded",
                    extra={
                        "event": "startup.admin_seeded",
                        "email": settings.INITIAL_ADMIN_EMAIL,
                    },
                )
        except Exception as e:
            db.rollback()
            logger.warning(
                "Admin seeding skipped: %s",
                e,
                extra={"event": "startup.admin_seed_failed"},
            )
        finally:
            db.close()


def _run_shutdown() -> None:
    """Gracefully shut down the notification scheduler."""
    try:
        from app.services.notification_scheduler import (
            shutdown_notification_scheduler,
        )
        shutdown_notification_scheduler()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan: run startup work, yield, then shut down cleanly."""
    _run_startup()
    yield
    _run_shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # The OpenAPI schema maps every route, parameter and model. That is a
    # reconnaissance aid, so it is not served in production unless explicitly
    # re-enabled; the routes are never registered rather than merely blocked.
    docs_enabled = settings.api_docs_enabled
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "AI-powered Intelligent Cognitive Alarm Platform that helps users "
            "develop consistent wake-up habits through personalized cognitive "
            "challenges including puzzles, riddles, math, and logic problems."
        ),
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # CORS middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.add_middleware(MaintenanceModeMiddleware)

    # Registered last so it is the outermost layer and therefore times the
    # whole stack, CORS and maintenance handling included.
    configure_registry(settings.REQUEST_METRICS_SAMPLE_SIZE)
    application.add_middleware(
        RequestTimingMiddleware, enabled=settings.REQUEST_METRICS_ENABLED
    )
    configure_challenge_registry(settings.CHALLENGE_METRICS_SAMPLE_SIZE)

    # Outermost of all: the correlation id must be bound before any other
    # middleware can log, and the access line must observe the true total.
    application.add_middleware(
        RequestContextMiddleware,
        header_name=settings.REQUEST_ID_HEADER,
        access_log=settings.LOG_ACCESS_ENABLED,
    )

    # Include API v1 routes
    application.include_router(api_router)

    @application.get(
        "/",
        tags=["Root"],
        response_model=RootResponse,
        # The doc links are absent in production, not null.
        response_model_exclude_none=True,
    )
    def root():
        """Root endpoint with API information."""
        info = {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "description": "Intelligent Cognitive Alarm Platform API",
        }
        if docs_enabled:
            info["docs"] = "/docs"
            info["redoc"] = "/redoc"
        return info

    @application.get("/health", tags=["Health"], response_model=HealthResponse)
    def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": settings.VERSION}

    return application


app = create_app()
