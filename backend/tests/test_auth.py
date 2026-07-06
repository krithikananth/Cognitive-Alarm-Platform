"""
Tests for authentication endpoints: register, login, refresh, me, logout.

Covers success paths, validation errors, duplicate checks, and token flows.
"""

import pytest
from httpx import AsyncClient
from tests.conftest import auth_header


# ═══════════════════════════════════════════
# Registration Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    """Test successful user registration."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "newuser@example.com",
        "username": "newuser",
        "password": "StrongPass1",
        "full_name": "New User",
        "timezone": "UTC",
    })
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "newuser@example.com"
    assert data["user"]["username"] == "newuser"
    assert data["user"]["role"] == "user"
    assert data["user"]["is_active"] is True


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient, test_user):
    """Test registration fails with duplicate email."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "testuser@example.com",
        "username": "different_user",
        "password": "StrongPass1",
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_duplicate_username(client: AsyncClient, test_user):
    """Test registration fails with duplicate username."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "different@example.com",
        "username": "testuser",
        "password": "StrongPass1",
    })
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    """Test registration fails with a weak password."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "weak@example.com",
        "username": "weakuser",
        "password": "short",
    })
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_register_invalid_email(client: AsyncClient):
    """Test registration fails with invalid email format."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "not-an-email",
        "username": "validuser",
        "password": "StrongPass1",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_missing_fields(client: AsyncClient):
    """Test registration fails when required fields are missing."""
    response = await client.post("/api/v1/auth/register", json={
        "email": "miss@example.com",
    })
    assert response.status_code == 422


# ═══════════════════════════════════════════
# Login Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, test_user):
    """Test successful login with correct credentials."""
    response = await client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "testuser@example.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, test_user):
    """Test login fails with incorrect password."""
    response = await client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "WrongPassword1",
    })
    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client: AsyncClient):
    """Test login fails for non-existent user."""
    response = await client.post("/api/v1/auth/login", json={
        "email": "ghost@example.com",
        "password": "SomePass123",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_deactivated_user(client: AsyncClient, db_session, test_user):
    """Test login fails for deactivated user."""
    test_user.is_active = False
    await db_session.flush()

    response = await client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
    })
    assert response.status_code == 403
    assert "deactivated" in response.json()["detail"].lower()


# ═══════════════════════════════════════════
# Token Refresh Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient, test_user):
    """Test successful token refresh."""
    # First login to get tokens
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "TestPass123",
    })
    refresh_tok = login_resp.json()["refresh_token"]

    # Refresh
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_tok,
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_with_invalid_token(client: AsyncClient):
    """Test refresh fails with invalid token."""
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": "invalid.token.string",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_with_access_token(client: AsyncClient, test_user, user_token):
    """Test refresh fails when using an access token instead of refresh token."""
    response = await client.post("/api/v1/auth/refresh", json={
        "refresh_token": user_token,  # This is an access token, not refresh
    })
    assert response.status_code == 400


# ═══════════════════════════════════════════
# Current User Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_me_authenticated(client: AsyncClient, test_user, user_token):
    """Test getting current user when authenticated."""
    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_header(user_token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "testuser@example.com"
    assert data["username"] == "testuser"
    assert data["role"] == "user"


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient):
    """Test getting current user without authentication fails."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(client: AsyncClient):
    """Test getting current user with invalid token fails."""
    response = await client.get(
        "/api/v1/auth/me",
        headers=auth_header("invalid.token.here"),
    )
    assert response.status_code == 401


# ═══════════════════════════════════════════
# Password Reset Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_forgot_password_existing_user(client: AsyncClient, test_user):
    """Test password reset request for existing user."""
    response = await client.post("/api/v1/auth/forgot-password", json={
        "email": "testuser@example.com",
    })
    assert response.status_code == 200
    data = response.json()
    assert "reset_token" in data


@pytest.mark.asyncio
async def test_forgot_password_nonexistent_user(client: AsyncClient):
    """Test password reset request for non-existent user (should not reveal info)."""
    response = await client.post("/api/v1/auth/forgot-password", json={
        "email": "nonexistent@example.com",
    })
    assert response.status_code == 200
    # Should still return a generic message (security: no info leak)


@pytest.mark.asyncio
async def test_reset_password_success(client: AsyncClient, test_user):
    """Test full password reset flow."""
    # Get reset token
    reset_resp = await client.post("/api/v1/auth/forgot-password", json={
        "email": "testuser@example.com",
    })
    reset_token = reset_resp.json()["reset_token"]

    # Reset password
    response = await client.post("/api/v1/auth/reset-password", json={
        "token": reset_token,
        "new_password": "NewSecurePass1",
    })
    assert response.status_code == 200

    # Verify login with new password
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "testuser@example.com",
        "password": "NewSecurePass1",
    })
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_invalid_token(client: AsyncClient):
    """Test password reset with invalid token fails."""
    response = await client.post("/api/v1/auth/reset-password", json={
        "token": "invalid.token.here",
        "new_password": "NewPass123",
    })
    assert response.status_code == 400
