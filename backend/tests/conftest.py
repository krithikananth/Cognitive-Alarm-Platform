"""
Pytest configuration and shared fixtures for the test suite.

Sets up an in-memory SQLite test database, async test client,
and helper fixtures for creating users and auth tokens.
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator, Dict

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.user import User, UserProfile
from app.utils.security import hash_password, create_access_token


# ─── Test Database Setup ─────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── Event Loop ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─── Database Session ────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a clean database for each test function."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ─── Test Client ─────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client with database override."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ─── User Fixtures ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a standard test user."""
    user = User(
        id=str(uuid.uuid4()),
        email="testuser@example.com",
        username="testuser",
        hashed_password=hash_password("TestPass123"),
        full_name="Test User",
        role="user",
        is_active=True,
        is_verified=True,
        timezone="UTC",
    )
    db_session.add(user)
    await db_session.flush()

    profile = UserProfile(
        id=str(uuid.uuid4()),
        user_id=user.id,
        difficulty_preference="medium",
        sleep_duration_hours=8.0,
        preferred_challenge_types=json.dumps(["math", "logic"]),
        habit_preferences="{}",
    )
    db_session.add(profile)
    await db_session.flush()

    return user


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    """Create an admin test user."""
    admin = User(
        id=str(uuid.uuid4()),
        email="admin@example.com",
        username="adminuser",
        hashed_password=hash_password("AdminPass123"),
        full_name="Admin User",
        role="admin",
        is_active=True,
        is_verified=True,
        timezone="UTC",
    )
    db_session.add(admin)
    await db_session.flush()

    profile = UserProfile(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        difficulty_preference="medium",
        sleep_duration_hours=7.0,
        preferred_challenge_types=json.dumps(["logic"]),
        habit_preferences="{}",
    )
    db_session.add(profile)
    await db_session.flush()

    return admin


@pytest_asyncio.fixture
async def test_coach(db_session: AsyncSession) -> User:
    """Create a wellness coach test user."""
    coach = User(
        id=str(uuid.uuid4()),
        email="coach@example.com",
        username="coachuser",
        hashed_password=hash_password("CoachPass123"),
        full_name="Coach User",
        role="wellness_coach",
        is_active=True,
        is_verified=True,
        timezone="UTC",
    )
    db_session.add(coach)
    await db_session.flush()

    profile = UserProfile(
        id=str(uuid.uuid4()),
        user_id=coach.id,
        difficulty_preference="hard",
        sleep_duration_hours=7.5,
        preferred_challenge_types=json.dumps(["logic", "math"]),
        habit_preferences="{}",
    )
    db_session.add(profile)
    await db_session.flush()

    return coach


# ─── Token Fixtures ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def user_token(test_user: User) -> str:
    """Generate a valid access token for the test user."""
    return create_access_token({"sub": test_user.id, "role": test_user.role})


@pytest_asyncio.fixture
async def admin_token(test_admin: User) -> str:
    """Generate a valid access token for the admin user."""
    return create_access_token({"sub": test_admin.id, "role": test_admin.role})


@pytest_asyncio.fixture
async def coach_token(test_coach: User) -> str:
    """Generate a valid access token for the wellness coach."""
    return create_access_token({"sub": test_coach.id, "role": test_coach.role})


def auth_header(token: str) -> Dict[str, str]:
    """Helper to create Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
