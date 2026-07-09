"""Tests for user management endpoints (admin-only).

Covers listing users, getting a user by ID, updating user roles,
deleting users, and activating/deactivating user accounts.
"""


class TestListUsers:
    """Tests for GET /api/v1/users/."""

    def test_list_users_admin(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can list all users."""
        response = client.get("/api/v1/users/", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2  # admin_user + test_user
        emails = [u["email"] for u in data]
        assert "admin@example.com" in emails
        assert "test@example.com" in emails

    def test_list_users_non_admin_forbidden(self, client, test_user, auth_headers):
        """Test that a non-admin user receives 403 when trying to list users."""
        response = client.get("/api/v1/users/", headers=auth_headers)

        assert response.status_code == 403
        assert "Admin privileges required" in response.json()["detail"]

    def test_list_users_unauthenticated(self, client):
        """Test that unauthenticated requests to list users return 401."""
        response = client.get("/api/v1/users/")

        assert response.status_code == 401


class TestGetUser:
    """Tests for GET /api/v1/users/{user_id}."""

    def test_get_user_admin(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can retrieve a specific user by ID."""
        response = client.get(
            f"/api/v1/users/{test_user.id}", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user.id)
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"

    def test_get_user_not_found(self, client, admin_user, admin_headers):
        """Test that requesting a non-existent user ID returns 404."""
        response = client.get(
            "/api/v1/users/nonexistent-id-12345", headers=admin_headers
        )

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]


class TestUpdateUser:
    """Tests for PUT /api/v1/users/{user_id}."""

    def test_update_user_role(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can change a user's role from user to admin."""
        payload = {"role": "admin"}
        response = client.put(
            f"/api/v1/users/{test_user.id}", json=payload, headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"

    def test_update_user_full_name(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can update a user's full name."""
        payload = {"full_name": "Updated Name"}
        response = client.put(
            f"/api/v1/users/{test_user.id}", json=payload, headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"

    def test_update_user_non_admin_forbidden(
        self, client, test_user, admin_user, auth_headers
    ):
        """Test that a non-admin cannot update another user."""
        payload = {"role": "admin"}
        response = client.put(
            f"/api/v1/users/{admin_user.id}", json=payload, headers=auth_headers
        )

        assert response.status_code == 403


class TestDeleteUser:
    """Tests for DELETE /api/v1/users/{user_id}."""

    def test_delete_user_admin(self, client, admin_user, test_user, admin_headers, db_session):
        """Test that an admin can delete a user account."""
        response = client.delete(
            f"/api/v1/users/{test_user.id}", headers=admin_headers
        )

        assert response.status_code == 204

        # Verify user is actually deleted
        from app.models.user import User

        deleted_user = db_session.query(User).filter(User.id == test_user.id).first()
        assert deleted_user is None

    def test_delete_user_not_found(self, client, admin_user, admin_headers):
        """Test that deleting a non-existent user returns 404."""
        response = client.delete(
            "/api/v1/users/nonexistent-id", headers=admin_headers
        )

        assert response.status_code == 404


class TestActivateDeactivate:
    """Tests for POST /api/v1/users/{user_id}/deactivate and /activate."""

    def test_deactivate_user(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can deactivate a user account."""
        response = client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    def test_activate_user(self, client, admin_user, test_user, admin_headers):
        """Test that an admin can re-activate a previously deactivated user."""
        # First deactivate
        client.post(
            f"/api/v1/users/{test_user.id}/deactivate", headers=admin_headers
        )

        # Then activate
        response = client.post(
            f"/api/v1/users/{test_user.id}/activate", headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True

    def test_deactivate_user_non_admin_forbidden(
        self, client, test_user, admin_user, auth_headers
    ):
        """Test that a non-admin cannot deactivate another user."""
        response = client.post(
            f"/api/v1/users/{admin_user.id}/deactivate", headers=auth_headers
        )

        assert response.status_code == 403
