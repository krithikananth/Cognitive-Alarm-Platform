"""Tests for user management endpoints (admin-only).

Aligned with the actual wired API (``app/api/v1/endpoints/users.py``):
- Integer user IDs.
- ``GET /users/`` returns a raw list of users.
- Admin updates use ``AdminUserUpdate`` (role + is_active supported).
- Activate/deactivate are ``POST /users/{id}/activate|deactivate``.
"""


class TestListUsers:
    """Tests for GET /api/v1/users/."""

    def test_list_users_admin(self, client, admin_user, test_user, admin_headers):
        """An admin can list all users."""
        response = client.get("/api/v1/users/", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # admin_user + test_user
        emails = [u["email"] for u in data]
        assert "admin@example.com" in emails
        assert "test@example.com" in emails

    def test_list_users_non_admin_forbidden(self, client, test_user, auth_headers):
        """A non-admin user receives 403 when trying to list users."""
        response = client.get("/api/v1/users/", headers=auth_headers)

        assert response.status_code == 403
        assert "Admin privileges required" in response.json()["detail"]

    def test_list_users_unauthenticated(self, client):
        """Unauthenticated requests to list users return 401."""
        response = client.get("/api/v1/users/")

        assert response.status_code == 401


class TestGetUser:
    """Tests for GET /api/v1/users/{user_id}."""

    def test_get_user_admin(self, client, admin_user, test_user, admin_headers):
        """An admin can retrieve a specific user by ID."""
        response = client.get(
            f"/api/v1/users/{test_user.id}", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_user.id
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"

    def test_get_user_not_found(self, client, admin_user, admin_headers):
        """Requesting a non-existent user ID returns 404."""
        response = client.get("/api/v1/users/999999", headers=admin_headers)

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]


class TestUpdateUser:
    """Tests for PUT /api/v1/users/{user_id}."""

    def test_update_user_role(self, client, admin_user, test_user, admin_headers):
        """An admin can change a user's role."""
        payload = {"role": "admin"}
        response = client.put(
            f"/api/v1/users/{test_user.id}", json=payload, headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"

    def test_update_user_full_name(self, client, admin_user, test_user, admin_headers):
        """An admin can update a user's full name."""
        payload = {"full_name": "Updated Name"}
        response = client.put(
            f"/api/v1/users/{test_user.id}", json=payload, headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"

    def test_update_user_invalid_role(self, client, admin_user, test_user, admin_headers):
        """An unknown role value is rejected with 422."""
        payload = {"role": "superuser"}
        response = client.put(
            f"/api/v1/users/{test_user.id}", json=payload, headers=admin_headers
        )

        assert response.status_code == 422

    def test_update_user_non_admin_forbidden(
        self, client, test_user, admin_user, auth_headers
    ):
        """A non-admin cannot update another user."""
        payload = {"role": "admin"}
        response = client.put(
            f"/api/v1/users/{admin_user.id}", json=payload, headers=auth_headers
        )

        assert response.status_code == 403


class TestDeleteUser:
    """Tests for DELETE /api/v1/users/{user_id}."""

    def test_delete_user_admin(
        self, client, admin_user, test_user, admin_headers, db_session
    ):
        """An admin can delete a user account."""
        response = client.delete(
            f"/api/v1/users/{test_user.id}", headers=admin_headers
        )

        assert response.status_code == 204

        from app.models.user import User

        deleted_user = (
            db_session.query(User).filter(User.id == test_user.id).first()
        )
        assert deleted_user is None

    def test_delete_user_not_found(self, client, admin_user, admin_headers):
        """Deleting a non-existent user returns 404."""
        response = client.delete("/api/v1/users/999999", headers=admin_headers)

        assert response.status_code == 404


class TestActivateDeactivate:
    """Tests for POST /api/v1/users/{user_id}/deactivate and /activate."""

    def test_deactivate_user(self, client, admin_user, test_user, admin_headers):
        """An admin can deactivate a user account."""
        response = client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_activate_user(self, client, admin_user, test_user, admin_headers):
        """An admin can re-activate a deactivated user."""
        client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )
        response = client.post(
            f"/api/v1/users/{test_user.id}/activate", headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is True

    def test_deactivate_self_forbidden(self, client, admin_user, admin_headers):
        """An admin cannot deactivate their own account."""
        response = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=admin_headers
        )

        assert response.status_code == 400

    def test_deactivate_user_non_admin_forbidden(
        self, client, test_user, admin_user, auth_headers
    ):
        """A non-admin cannot deactivate another user."""
        response = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=auth_headers
        )

        assert response.status_code == 403
