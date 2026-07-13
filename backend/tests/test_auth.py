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


def test_cors_allows_localhost_loopback_origins(client):
    """Local frontend origins should be accepted for auth requests during development."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


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
        assert data["id"] == test_user.id

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
        # The newly-issued access token must be usable for authenticated requests.
        # (We avoid asserting the raw token strings differ, since tokens minted
        # within the same second share identical claims and therefore encode
        # identically.)
        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {data['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == "test@example.com"

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


class TestGoogleOAuth:
    """Tests for Google OAuth2 redirect and callback endpoints."""

    def test_google_oauth_not_configured(self, client, monkeypatch):
        """Without client credentials the start endpoint redirects back to login.

        The browser navigates directly to this endpoint, so instead of a raw
        error page we bounce back to the SPA login route with an ``error``
        query param the frontend can surface as a toast.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", None)
        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", None)
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")

        response = client.get(
            "/api/v1/auth/oauth/google",
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("http://localhost:3000/login?error=")
        assert "not+configured" in location or "not%20configured" in location

    def test_google_oauth_redirect(self, client, monkeypatch):
        """Configured start endpoint redirects to Google's consent screen."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", "test-secret")
        monkeypatch.setattr(
            settings,
            "OAUTH2_GOOGLE_REDIRECT_URI",
            "http://localhost:8000/api/v1/auth/oauth/google/callback",
        )

        response = client.get(
            "/api/v1/auth/oauth/google",
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-client-id" in location
        assert "openid" in location and "email" in location and "profile" in location

    def test_google_oauth_callback_creates_user(self, client, db_session, monkeypatch):
        """Successful Google callback creates a verified user and redirects with JWTs."""
        from unittest.mock import MagicMock, patch

        from app.core.config import settings
        from app.models.user import User

        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", "test-secret")
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "google-access-token"}

        userinfo_resp = MagicMock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = {
            "id": "google-user-123",
            "email": "oauth.user@example.com",
            "name": "OAuth User",
        }

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = token_resp
        mock_client.get.return_value = userinfo_resp

        with patch("app.api.v1.endpoints.auth.httpx.Client", return_value=mock_client):
            response = client.get(
                "/api/v1/auth/oauth/google/callback",
                params={"code": "auth-code"},
                follow_redirects=False,
            )

        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("http://localhost:3000/oauth/callback?")
        assert "access_token=" in location
        assert "refresh_token=" in location

        user = (
            db_session.query(User)
            .filter(User.email == "oauth.user@example.com")
            .first()
        )
        assert user is not None
        assert user.oauth_provider == "google"
        assert user.oauth_id == "google-user-123"
        assert user.is_verified is True
        assert user.full_name == "OAuth User"
        assert user.profile is not None

    def test_google_oauth_callback_links_existing_email(
        self, client, db_session, test_user, monkeypatch
    ):
        """Existing email/password accounts are linked when signing in with Google."""
        from unittest.mock import MagicMock, patch

        from app.core.config import settings

        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", "test-secret")
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "google-access-token"}

        userinfo_resp = MagicMock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = {
            "id": "google-linked-id",
            "email": test_user.email,
            "name": "Linked Name",
        }

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = token_resp
        mock_client.get.return_value = userinfo_resp

        with patch("app.api.v1.endpoints.auth.httpx.Client", return_value=mock_client):
            response = client.get(
                "/api/v1/auth/oauth/google/callback",
                params={"code": "auth-code"},
                follow_redirects=False,
            )

        assert response.status_code == 302
        db_session.refresh(test_user)
        assert test_user.oauth_provider == "google"
        assert test_user.oauth_id == "google-linked-id"
        assert test_user.is_verified is True

    def test_google_oauth_callback_provider_error(self, client, monkeypatch):
        """Provider error query param redirects back to the login page."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", "test-secret")
        monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")

        response = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"].startswith(
            "http://localhost:3000/login?error="
        )
