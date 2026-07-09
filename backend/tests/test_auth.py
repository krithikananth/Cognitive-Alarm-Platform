"""Comprehensive tests for authentication endpoints.

Covers registration (success, duplicate email, duplicate username, weak password),
login (success, wrong password, nonexistent user), current user retrieval, and
token refresh flow.
"""


class TestRegister:
    """Tests for POST /api/v1/auth/register."""

    def test_register_user_success(self, client):
        """Test that a new user can register successfully with valid data."""
        payload = {
            "email": "newuser@example.com",
            "username": "newuser",
            "password": "StrongPass1",
            "full_name": "New User",
        }
        response = client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["username"] == "newuser"
        assert data["full_name"] == "New User"
        assert data["role"] == "user"
        assert data["is_active"] is True
        assert "id" in data
        # Password should never be returned
        assert "hashed_password" not in data
        assert "password" not in data

    def test_register_user_duplicate_email(self, client, test_user):
        """Test that registration fails when the email is already in use."""
        payload = {
            "email": "test@example.com",  # same as test_user
            "username": "differentuser",
            "password": "StrongPass1",
        }
        response = client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 400
        assert "Email already registered" in response.json()["detail"]

    def test_register_user_duplicate_username(self, client, test_user):
        """Test that registration fails when the username is already taken."""
        payload = {
            "email": "different@example.com",
            "username": "testuser",  # same as test_user
            "password": "StrongPass1",
        }
        response = client.post("/api/v1/auth/register", json=payload)

        assert response.status_code == 400
        assert "Username already taken" in response.json()["detail"]

    def test_register_user_weak_password(self, client):
        """Test that registration rejects a password that doesn't meet strength requirements."""
        # Too short
        payload = {
            "email": "weak@example.com",
            "username": "weakuser",
            "password": "short",
        }
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422  # Validation error

        # No uppercase
        payload["password"] = "alllowercase1"
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422

        # No digit
        payload["password"] = "NoDigitHere"
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422

        # No lowercase
        payload["password"] = "ALLUPPERCASE1"
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 422


class TestLogin:
    """Tests for POST /api/v1/auth/login."""

    def test_login_success(self, client, test_user):
        """Test that a registered user can log in with correct credentials and receive tokens."""
        payload = {
            "email": "test@example.com",
            "password": "TestPass123",
        }
        response = client.post("/api/v1/auth/login", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0
        assert len(data["refresh_token"]) > 0

    def test_login_wrong_password(self, client, test_user):
        """Test that login fails with an incorrect password."""
        payload = {
            "email": "test@example.com",
            "password": "WrongPassword1",
        }
        response = client.post("/api/v1/auth/login", json=payload)

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """Test that login fails for a non-registered email address."""
        payload = {
            "email": "noone@example.com",
            "password": "SomePass123",
        }
        response = client.post("/api/v1/auth/login", json=payload)

        assert response.status_code == 401
        assert "Invalid email or password" in response.json()["detail"]


class TestCurrentUser:
    """Tests for GET /api/v1/auth/me."""

    def test_get_current_user(self, client, test_user, auth_headers):
        """Test that an authenticated user can retrieve their own information."""
        response = client.get("/api/v1/auth/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"
        assert data["id"] == str(test_user.id)

    def test_get_current_user_unauthorized(self, client):
        """Test that accessing /me without a token returns 401."""
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401

    def test_get_current_user_invalid_token(self, client):
        """Test that accessing /me with a malformed token returns 401."""
        headers = {"Authorization": "Bearer invalid.token.here"}
        response = client.get("/api/v1/auth/me", headers=headers)

        assert response.status_code == 401


class TestTokenRefresh:
    """Tests for POST /api/v1/auth/refresh."""

    def test_refresh_token(self, client, test_user):
        """Test that a valid refresh token produces new access and refresh tokens."""
        # First log in to get a refresh token
        login_payload = {
            "email": "test@example.com",
            "password": "TestPass123",
        }
        login_response = client.post("/api/v1/auth/login", json=login_payload)
        assert login_response.status_code == 200
        refresh_token = login_response.json()["refresh_token"]

        # Use the refresh token to get new tokens
        refresh_payload = {"refresh_token": refresh_token}
        response = client.post("/api/v1/auth/refresh", json=refresh_payload)

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        # New tokens should be different from old ones
        assert data["refresh_token"] != refresh_token or data["access_token"] != login_response.json()["access_token"]

    def test_refresh_token_invalid(self, client):
        """Test that an invalid refresh token is rejected."""
        payload = {"refresh_token": "invalid.refresh.token"}
        response = client.post("/api/v1/auth/refresh", json=payload)

        assert response.status_code == 401

    def test_refresh_token_using_access_token(self, client, test_user, auth_headers):
        """Test that an access token cannot be used as a refresh token."""
        # Extract the access token from headers
        access_token = auth_headers["Authorization"].replace("Bearer ", "")
        payload = {"refresh_token": access_token}
        response = client.post("/api/v1/auth/refresh", json=payload)

        assert response.status_code == 401
