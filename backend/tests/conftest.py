"""Pytest configuration and shared fixtures for the test suite.

Provides:
- In-memory SQLite test database
- TestClient fixture with dependency overrides
- Pre-created test user and admin user fixtures
- JWT auth header fixtures for authenticated requests
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Pinned before app.main is imported: the settings singleton (and the access-log
# middleware built from it) is created at import time, so a developer's local
# .env would otherwise decide whether the observability assertions can hold.
# A real environment variable still wins, so CI can override deliberately.
os.environ.setdefault("LOG_ACCESS_ENABLED", "true")
os.environ.setdefault("LOG_TO_CONSOLE", "true")
os.environ.setdefault("LOG_LEVEL", "INFO")

from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.utils.hashing import get_password_hash
from app.models.user import User, UserRole
from app.models.profile import UserProfile  # noqa: F401 - ensure model is registered
from app.models.alarm import Alarm  # noqa: F401 - ensure model is registered
from app.models.challenge_session import ChallengeSession  # noqa: F401
from app.models.alarm_wake_event import AlarmWakeEvent  # noqa: F401
from app.models.alarm_snooze_event import AlarmSnoozeEvent  # noqa: F401
from app.models.analytics_event import AnalyticsEvent  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.system_settings import SystemSettings  # noqa: F401
from app.models.coach_assignment import CoachAssignment  # noqa: F401
from app.models.revoked_token import RevokedToken  # noqa: F401
from app.core.security import create_access_token

# Use a single shared in-memory SQLite database for the whole test session.
# StaticPool keeps one connection so the schema/data are visible across the
# test thread and the TestClient's worker thread, and nothing is persisted to
# disk between runs (avoids stale/corrupt test.db state).
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def disable_ai_challenge_provider():
    """Keep challenge generation deterministic and offline by default.

    Tests that exercise the AI path opt in explicitly and mock the provider.
    """
    from app.core.config import settings
    from app.services import ai_challenge_provider

    previous_enabled = settings.AI_CHALLENGE_ENABLED
    previous_key = settings.GEMINI_API_KEY
    settings.AI_CHALLENGE_ENABLED = False
    settings.GEMINI_API_KEY = None
    ai_challenge_provider.reset_provider_state()
    try:
        yield
    finally:
        settings.AI_CHALLENGE_ENABLED = previous_enabled
        settings.GEMINI_API_KEY = previous_key
        ai_challenge_provider.reset_provider_state()


@pytest.fixture(autouse=True)
def reset_auth_rate_limits():
    """Keep brute-force counters out of unrelated tests.

    The limiter is process-wide, so repeated logins across the suite would
    otherwise trip a lockout. Security tests re-enable it explicitly.
    """
    from app.core import rate_limit
    from app.core.config import settings

    previous = settings.RATE_LIMIT_ENABLED
    settings.RATE_LIMIT_ENABLED = False
    rate_limit.reset_all_limiters()
    try:
        yield
    finally:
        settings.RATE_LIMIT_ENABLED = previous
        rate_limit.reset_all_limiters()


@pytest.fixture(autouse=True)
def disable_aggregate_cache():
    """Keep aggregate reads uncached so assertions see the current database.

    The cache is keyed on (namespace, scope, params) with a short TTL, so on a
    machine that happens to be running Redis a test could otherwise read a
    payload written by an earlier test. Cache behaviour itself is covered by
    tests/test_aggregate_cache.py, which enables it explicitly.
    """
    from app.core.config import settings

    previous = settings.AGGREGATE_CACHE_ENABLED
    settings.AGGREGATE_CACHE_ENABLED = False
    try:
        yield
    finally:
        settings.AGGREGATE_CACHE_ENABLED = previous


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test.

    Sets up all tables before the test and tears them down after,
    ensuring complete isolation between tests.
    """
    from app.services.system_settings_service import SystemSettingsService

    SystemSettingsService.reset_maintenance_cache()
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        SystemSettingsService.reset_maintenance_cache()


@pytest.fixture(scope="function")
def client(db_session):
    """Provide a FastAPI TestClient with the test database session injected.

    Overrides the get_db dependency so all requests use the test DB.
    Clears overrides after the test completes.
    """

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def start_google_oauth(client):
    """Begin the Google OAuth flow and return the anti-CSRF state it issued.

    The matching state cookie lands in the TestClient jar, so callers can hit
    the callback exactly as the initiating browser would. Google credentials
    must already be configured (monkeypatched) by the caller.
    """
    from urllib.parse import parse_qs, urlparse

    def _start() -> str:
        response = client.get(
            "/api/v1/auth/oauth/google", follow_redirects=False
        )
        assert response.status_code == 302
        query = parse_qs(urlparse(response.headers["location"]).query)
        return query["state"][0]

    return _start


@pytest.fixture
def test_user(db_session):
    """Create and return a standard test user (role=USER, active, verified)."""
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=get_password_hash("TestPass123"),
        full_name="Test User",
        role=UserRole.USER,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_user(db_session):
    """Create and return an admin test user (role=ADMIN, active, verified)."""
    user = User(
        email="admin@example.com",
        username="adminuser",
        hashed_password=get_password_hash("AdminPass123"),
        full_name="Admin User",
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def coach_user(db_session):
    """Create and return a wellness coach test user."""
    user = User(
        email="coach@example.com",
        username="coachuser",
        hashed_password=get_password_hash("CoachPass123"),
        full_name="Coach User",
        role=UserRole.WELLNESS_COACH,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def coach_headers(coach_user):
    """Return Authorization headers with a valid JWT for the coach test user."""
    token = create_access_token(
        data={"sub": str(coach_user.id), "role": coach_user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(test_user):
    """Return Authorization headers with a valid JWT for the standard test user."""
    token = create_access_token(
        data={"sub": str(test_user.id), "role": test_user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user):
    """Return Authorization headers with a valid JWT for the admin test user."""
    token = create_access_token(
        data={"sub": str(admin_user.id), "role": admin_user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}
