"""
FastAPI application entry point for the Intelligent Cognitive Alarm Platform.

Creates and configures the main application instance with CORS middleware,
API routing, and database initialization on startup.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router
from app.db.base import Base
from app.db.session import engine

# Import all models so they are registered with Base.metadata
from app.models import user, profile, alarm  # noqa: F401
from app.models import challenge_session  # noqa: F401
from app.models import alarm_wake_event  # noqa: F401
from app.models import alarm_snooze_event  # noqa: F401
from app.models import analytics_event  # noqa: F401


def _ensure_sqlite_columns() -> None:
    """Add missing columns/indexes on existing SQLite tables (create_all won't alter)."""
    if not str(settings.DATABASE_URL).startswith("sqlite"):
        return
    statements = [
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
    ]
    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.exec_driver_sql(sql)
            except Exception:
                # Column already exists / statement not applicable
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
            print(f"✅ Attempt logs repaired: {repaired} row(s)")
    except Exception as e:
        db.rollback()
        print(f"⚠️ Attempt-log repair skipped: {e}")
    finally:
        db.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "AI-powered Intelligent Cognitive Alarm Platform that helps users "
            "develop consistent wake-up habits through personalized cognitive "
            "challenges including puzzles, riddles, math, and logic problems."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
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

    # Include API v1 routes
    application.include_router(api_router)

    @application.on_event("startup")
    def on_startup():
        """Create database tables on application startup."""
        Base.metadata.create_all(bind=engine)
        _ensure_sqlite_columns()
        _repair_attempt_logs_on_startup()

        # Seed default admin user if not present
        from app.db.session import SessionLocal
        from app.models.user import User, UserRole
        from app.models.profile import UserProfile, DifficultyPreference
        from app.utils.hashing import get_password_hash

        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.email == "23102107@rmd.ac.in").first()
            if not admin:
                admin = User(
                    email="23102107@rmd.ac.in",
                    username="admin_icap",
                    hashed_password=get_password_hash("Admin@123"),
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
                    timezone="Asia/Kolkata",
                    difficulty_preference=DifficultyPreference.MEDIUM,
                )
                db.add(admin_profile)
                db.commit()
                print("✅ Admin user seeded: 23102107@rmd.ac.in")
        except Exception as e:
            db.rollback()
            print(f"⚠️ Admin seeding skipped: {e}")
        finally:
            db.close()

    @application.get("/", tags=["Root"])
    def root():
        """Root endpoint with API information."""
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "description": "Intelligent Cognitive Alarm Platform API",
            "docs": "/docs",
            "redoc": "/redoc",
        }

    @application.get("/health", tags=["Health"])
    def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "version": settings.VERSION}

    return application


app = create_app()
