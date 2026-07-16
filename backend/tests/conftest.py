"""Pytest configuration and shared fixtures for the test suite.

Provides:
- In-memory SQLite test database
- TestClient fixture with dependency overrides
- Pre-created test user and admin user fixtures
- JWT auth header fixtures for authenticated requests
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.utils.hashing import get_password_hash
from app.models.user import User, UserRole
from app.models.profile import UserProfile  # noqa: F401 - ensure model is registered
from app.models.alarm import Alarm  # noqa: F401 - ensure model is registered
from app.models.challenge_session import ChallengeSession  # noqa: F401
from app.models.alarm_wake_event import AlarmWakeEvent  # noqa: F401
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


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test.

    Sets up all tables before the test and tears them down after,
    ensuring complete isolation between tests.
    """
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


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
