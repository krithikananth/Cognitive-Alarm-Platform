"""Tests for Role-Based Access Control (RBAC).

Verifies that admin-only endpoints are properly guarded against regular
users and unauthenticated requests. Targets the actually-wired endpoints:
- Admin user management under ``/api/v1/users`` (guarded by ``get_current_admin``).
- The admin dashboard under ``/api/v1/admin/dashboard`` (guarded by ``require_admin``).
"""


class TestAdminUserManagementAccess:
    """Access control for admin user-management endpoints."""

    def test_admin_can_list_users(self, client, admin_user, test_user, admin_headers):
        """Admins can access the user listing endpoint."""
        response = client.get("/api/v1/users/", headers=admin_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_user_cannot_list_users(self, client, test_user, auth_headers):
        """Regular users are forbidden from the admin listing endpoint."""
        response = client.get("/api/v1/users/", headers=auth_headers)
        assert response.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client):
        """Unauthenticated requests are rejected with 401."""
        response = client.get("/api/v1/users/")
        assert response.status_code == 401

    def test_admin_can_change_role(self, client, admin_user, test_user, admin_headers):
        """Admins can change another user's role."""
        response = client.put(
            f"/api/v1/users/{test_user.id}",
            json={"role": "wellness_coach"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["role"] == "wellness_coach"

    def test_user_cannot_change_role(self, client, test_user, admin_user, auth_headers):
        """Regular users cannot change roles."""
        response = client.put(
            f"/api/v1/users/{admin_user.id}",
            json={"role": "user"},
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_invalid_role_rejected(self, client, admin_user, test_user, admin_headers):
        """Invalid role values are rejected with 422."""
        response = client.put(
            f"/api/v1/users/{test_user.id}",
            json={"role": "superuser"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_admin_can_deactivate_and_activate(
        self, client, admin_user, test_user, admin_headers
    ):
        """Admins can deactivate and re-activate a user."""
        deactivate = client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )
        assert deactivate.status_code == 200
        assert deactivate.json()["is_active"] is False

        activate = client.post(
            f"/api/v1/users/{test_user.id}/activate", headers=admin_headers
        )
        assert activate.status_code == 200
        assert activate.json()["is_active"] is True

    def test_admin_cannot_deactivate_self(self, client, admin_user, admin_headers):
        """Admins cannot deactivate their own account (lockout prevention)."""
        response = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=admin_headers
        )
        assert response.status_code == 400

    def test_user_cannot_delete_user(self, client, test_user, admin_user, auth_headers):
        """Regular users cannot delete accounts."""
        response = client.delete(
            f"/api/v1/users/{admin_user.id}", headers=auth_headers
        )
        assert response.status_code == 403


class TestAdminDashboardAccess:
    """Access control for the admin dashboard endpoint."""

    def test_admin_can_view_dashboard(self, client, admin_user, admin_headers):
        """Admins can view platform dashboard statistics."""
        response = client.get("/api/v1/admin/dashboard", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "total_alarms" in data

    def test_user_cannot_view_dashboard(self, client, test_user, auth_headers):
        """Regular users are forbidden from the admin dashboard."""
        response = client.get("/api/v1/admin/dashboard", headers=auth_headers)
        assert response.status_code == 403

    def test_unauthenticated_cannot_view_dashboard(self, client):
        """Unauthenticated requests to the dashboard are rejected with 401."""
        response = client.get("/api/v1/admin/dashboard")
        assert response.status_code == 401
