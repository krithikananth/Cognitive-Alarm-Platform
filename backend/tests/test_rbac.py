"""
Tests for Role-Based Access Control (RBAC).

Verifies that admin, wellness_coach, and user roles are properly
enforced across all protected endpoints.
"""

import pytest
from httpx import AsyncClient
from tests.conftest import auth_header


# ═══════════════════════════════════════════
# Admin Endpoint Access Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_admin_can_list_users(client: AsyncClient, test_admin, admin_token):
    """Test that admin can access user listing endpoint."""
    response = await client.get(
        "/api/v1/admin/users",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_user_cannot_list_users(client: AsyncClient, test_user, user_token):
    """Test that regular user cannot access admin endpoints."""
    response = await client.get(
        "/api/v1/admin/users",
        headers=auth_header(user_token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_coach_cannot_list_all_users(client: AsyncClient, test_coach, coach_token):
    """Test that coach cannot access admin-only endpoints."""
    response = await client.get(
        "/api/v1/admin/users",
        headers=auth_header(coach_token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_change_role(
    client: AsyncClient, test_admin, test_user, admin_token,
):
    """Test that admin can change a user's role."""
    response = await client.put(
        f"/api/v1/admin/users/{test_user.id}/role",
        json={"role": "wellness_coach"},
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["role"] == "wellness_coach"


@pytest.mark.asyncio
async def test_user_cannot_change_role(
    client: AsyncClient, test_user, test_admin, user_token,
):
    """Test that regular user cannot change roles."""
    response = await client.put(
        f"/api/v1/admin/users/{test_admin.id}/role",
        json={"role": "user"},
        headers=auth_header(user_token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_demote_self(
    client: AsyncClient, test_admin, admin_token,
):
    """Test that admin cannot change their own role (lockout prevention)."""
    response = await client.put(
        f"/api/v1/admin/users/{test_admin.id}/role",
        json={"role": "user"},
        headers=auth_header(admin_token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_deactivate_user(
    client: AsyncClient, test_admin, test_user, admin_token,
):
    """Test that admin can deactivate a user account."""
    response = await client.patch(
        f"/api/v1/admin/users/{test_user.id}/deactivate",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_can_activate_user(
    client: AsyncClient, test_admin, test_user, admin_token, db_session,
):
    """Test that admin can re-activate a deactivated user."""
    test_user.is_active = False
    await db_session.flush()

    response = await client.patch(
        f"/api/v1/admin/users/{test_user.id}/activate",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_self(
    client: AsyncClient, test_admin, admin_token,
):
    """Test that admin cannot deactivate their own account."""
    response = await client.patch(
        f"/api/v1/admin/users/{test_admin.id}/deactivate",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_delete_user(
    client: AsyncClient, test_admin, test_user, admin_token,
):
    """Test that admin can delete a user."""
    response = await client.delete(
        f"/api/v1/admin/users/{test_user.id}",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    assert "deleted" in response.json()["message"].lower()


@pytest.mark.asyncio
async def test_admin_can_view_platform_stats(
    client: AsyncClient, test_admin, admin_token,
):
    """Test that admin can view platform statistics."""
    response = await client.get(
        "/api/v1/admin/stats",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_users" in data
    assert "role_distribution" in data


# ═══════════════════════════════════════════
# Coach Endpoint Access Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_coach_can_access_coach_endpoints(
    client: AsyncClient, test_coach, coach_token,
):
    """Test that wellness coach can access coach endpoints."""
    response = await client.get(
        "/api/v1/coach/users",
        headers=auth_header(coach_token),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_access_coach_endpoints(
    client: AsyncClient, test_admin, admin_token,
):
    """Test that admin can also access coach endpoints (role hierarchy)."""
    response = await client.get(
        "/api/v1/coach/users",
        headers=auth_header(admin_token),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_user_cannot_access_coach_endpoints(
    client: AsyncClient, test_user, user_token,
):
    """Test that regular user cannot access coach endpoints."""
    response = await client.get(
        "/api/v1/coach/users",
        headers=auth_header(user_token),
    )
    assert response.status_code == 403


# ═══════════════════════════════════════════
# Unauthenticated Access Tests
# ═══════════════════════════════════════════

@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_admin(client: AsyncClient):
    """Test that unauthenticated requests cannot access admin endpoints."""
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_cannot_access_coach(client: AsyncClient):
    """Test that unauthenticated requests cannot access coach endpoints."""
    response = await client.get("/api/v1/coach/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_role_in_update(
    client: AsyncClient, test_admin, test_user, admin_token,
):
    """Test that invalid role values are rejected."""
    response = await client.put(
        f"/api/v1/admin/users/{test_user.id}/role",
        json={"role": "superuser"},  # Invalid role
        headers=auth_header(admin_token),
    )
    assert response.status_code == 422
