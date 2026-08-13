"""
Security regression tests for authentication hardening.

Covers the runtime protections added on top of the existing RBAC suite:
- brute-force lockout on login and password-reset abuse
- logout / token revocation and revoke-all-sessions
- HttpOnly, SameSite auth cookies and cookie-based authentication
- OAuth callback never exposing tokens in the redirect URL
- OAuth login-CSRF: bound, single-use, expiring ``state``
- SECRET_KEY validation (missing / weak / short in production)
"""

import time
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from pydantic import ValidationError

from app.core import rate_limit
from app.core.config import DEV_SECRET_KEY, Settings, settings
from app.core.oauth_state import generate_state
from app.core.security import create_access_token, verify_token
from app.models.revoked_token import RevokedToken
from app.models.user import User


LOGIN_URL = "/api/v1/auth/login"
CALLBACK_URL = "/api/v1/auth/oauth/google/callback"
PASSWORD = "TestPass123"


def _configure_google(monkeypatch):
    """Enable the Google provider with throwaway credentials."""
    monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "OAUTH2_GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:3000")


def _google_http_client():
    """Stub httpx client returning a successful token + userinfo exchange."""
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "google-access-token"}

    userinfo_resp = MagicMock()
    userinfo_resp.status_code = 200
    userinfo_resp.json.return_value = {
        "id": "google-secure-1",
        "email": "secure.oauth@example.com",
        "name": "Secure OAuth",
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.post.return_value = token_resp
    mock_client.get.return_value = userinfo_resp
    return mock_client


def _force_state_cookie(client, value):
    """Replace the jar's state cookie (plain ``set`` would add a duplicate)."""
    client.cookies.delete(settings.OAUTH_STATE_COOKIE_NAME)
    client.cookies.set(settings.OAUTH_STATE_COOKIE_NAME, value)


@pytest.fixture
def rate_limits_on(monkeypatch):
    """Enable the limiter for a single test with small, fast thresholds."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 50)
    monkeypatch.setattr(settings, "LOGIN_ATTEMPT_WINDOW_SECONDS", 300)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 60)
    monkeypatch.setattr(settings, "PASSWORD_RESET_MAX_REQUESTS", 2)
    monkeypatch.setattr(settings, "PASSWORD_RESET_WINDOW_SECONDS", 60)
    rate_limit.reset_all_limiters()
    yield
    rate_limit.reset_all_limiters()


# ═══════════════════════════════════════════════════════════════
# Brute-force / rate limiting
# ═══════════════════════════════════════════════════════════════

class TestLoginBruteForceProtection:
    def test_repeated_failed_logins_are_locked_out(
        self, client, test_user, rate_limits_on
    ):
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            res = client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )
            assert res.status_code == 401

        blocked = client.post(
            LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
        )
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert int(blocked.headers["Retry-After"]) > 0

    def test_lockout_blocks_even_the_correct_password(
        self, client, test_user, rate_limits_on
    ):
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )

        res = client.post(
            LOGIN_URL, json={"email": test_user.email, "password": PASSWORD}
        )
        assert res.status_code == 429

    def test_successful_login_clears_failed_attempts(
        self, client, test_user, rate_limits_on
    ):
        for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
            client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )

        ok = client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        assert ok.status_code == 200

        # Counter reset — a fresh streak of failures is needed to lock again.
        for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
            res = client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )
            assert res.status_code == 401

    def test_oauth2_token_endpoint_is_rate_limited(
        self, client, test_user, rate_limits_on
    ):
        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            res = client.post(
                "/api/v1/auth/token",
                data={"username": test_user.email, "password": "WrongPass1"},
            )
            assert res.status_code == 401

        blocked = client.post(
            "/api/v1/auth/token",
            data={"username": test_user.email, "password": "WrongPass1"},
        )
        assert blocked.status_code == 429

    def test_limiter_disabled_allows_unlimited_attempts(self, client, test_user):
        # The autouse conftest fixture disables the limiter for other suites.
        for _ in range(8):
            res = client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )
            assert res.status_code == 401

    def test_per_address_cap_is_independent_of_the_account_cap(
        self, client, test_user, admin_user, rate_limits_on, monkeypatch
    ):
        """Locking one account must not lock another account on the same IP."""
        monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 50)

        for _ in range(settings.LOGIN_MAX_ATTEMPTS):
            client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            )
        assert (
            client.post(
                LOGIN_URL, json={"email": test_user.email, "password": "WrongPass1"}
            ).status_code
            == 429
        )

        other = client.post(
            LOGIN_URL, json={"email": admin_user.email, "password": "WrongPass1"}
        )
        assert other.status_code == 401

    def test_address_cap_blocks_account_spraying(
        self, client, test_user, rate_limits_on, monkeypatch
    ):
        """Rotating the target account still trips the per-address cap."""
        monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 4)

        statuses = [
            client.post(
                LOGIN_URL,
                json={"email": f"nobody{i}@example.com", "password": "WrongPass1"},
            ).status_code
            for i in range(6)
        ]
        assert 429 in statuses


class TestPasswordResetAbuseProtection:
    def test_forgot_password_is_rate_limited(self, client, test_user, rate_limits_on):
        for _ in range(settings.PASSWORD_RESET_MAX_REQUESTS):
            res = client.post(
                "/api/v1/auth/forgot-password", json={"email": test_user.email}
            )
            assert res.status_code == 200

        blocked = client.post(
            "/api/v1/auth/forgot-password", json={"email": test_user.email}
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0

    def test_reset_password_endpoint_is_rate_limited(self, client, rate_limits_on):
        for _ in range(settings.PASSWORD_RESET_MAX_REQUESTS):
            res = client.post(
                "/api/v1/auth/reset-password",
                json={"token": "bogus-token", "new_password": "NewPass123"},
            )
            assert res.status_code == 400

        blocked = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "bogus-token", "new_password": "NewPass123"},
        )
        assert blocked.status_code == 429

    def test_resend_verification_is_rate_limited(
        self, client, test_user, rate_limits_on
    ):
        for _ in range(settings.PASSWORD_RESET_MAX_REQUESTS):
            assert (
                client.post(
                    "/api/v1/auth/resend-verification", json={"email": test_user.email}
                ).status_code
                == 200
            )

        blocked = client.post(
            "/api/v1/auth/resend-verification", json={"email": test_user.email}
        )
        assert blocked.status_code == 429


# ═══════════════════════════════════════════════════════════════
# Token revocation / logout
# ═══════════════════════════════════════════════════════════════

class TestTokenRevocation:
    def _login(self, client, test_user):
        res = client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        assert res.status_code == 200
        return res.json()

    def test_access_token_stops_working_after_logout(
        self, client, test_user, db_session
    ):
        tokens = self._login(client, test_user)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200

        after = client.get("/api/v1/auth/me", headers=headers)
        assert after.status_code == 401
        assert "revoked" in after.json()["detail"].lower()

    def test_logout_records_the_revocation(self, client, test_user, db_session):
        tokens = self._login(client, test_user)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        jti = verify_token(tokens["access_token"])["jti"]

        client.post("/api/v1/auth/logout", headers=headers)

        row = db_session.query(RevokedToken).filter(RevokedToken.jti == jti).first()
        assert row is not None
        assert row.user_id == test_user.id
        assert row.reason == "logout"

    def test_refresh_token_is_revoked_by_logout(self, client, test_user):
        tokens = self._login(client, test_user)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        client.post("/api/v1/auth/logout", headers=headers)

        # Cookie-based refresh token was revoked with the session.
        res = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert res.status_code == 401
        assert "revoked" in res.json()["detail"].lower()

    def test_revoked_token_cannot_reach_protected_resources(self, client, test_user):
        tokens = self._login(client, test_user)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        client.post("/api/v1/auth/logout", headers=headers)

        assert client.get("/api/v1/alarms/", headers=headers).status_code == 401
        assert client.get("/api/v1/dashboard/summary", headers=headers).status_code == 401

    def test_other_sessions_survive_a_single_logout(self, client, test_user):
        first = self._login(client, test_user)
        second = self._login(client, test_user)

        client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )

        still_valid = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {second['access_token']}"},
        )
        assert still_valid.status_code == 200

    def test_logout_all_revokes_every_session(self, client, test_user):
        first = self._login(client, test_user)
        second = self._login(client, test_user)

        res = client.post(
            "/api/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {first['access_token']}"},
        )
        assert res.status_code == 200

        for tokens in (first, second):
            probe = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            assert probe.status_code == 401

    def test_password_reset_invalidates_existing_sessions(
        self, client, test_user, db_session
    ):
        from app.core.security import create_password_reset_token

        tokens = self._login(client, test_user)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        reset = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": create_password_reset_token(test_user.id),
                "new_password": "BrandNewPass1",
            },
        )
        assert reset.status_code == 200

        after = client.get("/api/v1/auth/me", headers=headers)
        assert after.status_code == 401

    def test_legacy_token_without_jti_is_fully_revoked(self, client, test_user):
        """Tokens minted before jti existed fall back to revoke-all."""
        from datetime import datetime, timedelta, timezone

        from jose import jwt

        payload = {
            "sub": str(test_user.id),
            "role": test_user.role.value,
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        }
        legacy = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        headers = {"Authorization": f"Bearer {legacy}"}

        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401

    def test_tokens_carry_unique_ids(self, test_user):
        first = verify_token(create_access_token({"sub": str(test_user.id)}))
        second = verify_token(create_access_token({"sub": str(test_user.id)}))
        assert first["jti"] and second["jti"]
        assert first["jti"] != second["jti"]
        assert first["iat"] and second["iat"]

    def test_refresh_revokes_the_replaced_access_token(self, client, test_user):
        tokens = self._login(client, test_user)
        old_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        rotated = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
            headers=old_headers,
        )
        assert rotated.status_code == 200

        # The replaced token dies immediately; the new one works.
        assert client.get("/api/v1/auth/me", headers=old_headers).status_code == 401
        new_headers = {
            "Authorization": f"Bearer {rotated.json()['access_token']}"
        }
        assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 200

    def test_logout_after_refresh_leaves_no_usable_token(self, client, test_user):
        tokens = self._login(client, test_user)
        first_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        rotated = client.post("/api/v1/auth/refresh", json={}, headers=first_headers)
        assert rotated.status_code == 200
        second_headers = {
            "Authorization": f"Bearer {rotated.json()['access_token']}"
        }

        assert client.post("/api/v1/auth/logout", headers=second_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=first_headers).status_code == 401
        assert client.get("/api/v1/auth/me", headers=second_headers).status_code == 401


# ═══════════════════════════════════════════════════════════════
# Secure cookie session
# ═══════════════════════════════════════════════════════════════

def _set_cookie_header(response, name):
    for raw in response.headers.get_list("set-cookie"):
        if raw.startswith(f"{name}="):
            return raw
    return None


class TestAuthCookies:
    def test_login_sets_httponly_samesite_cookies(self, client, test_user):
        res = client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        assert res.status_code == 200

        access = _set_cookie_header(res, settings.ACCESS_COOKIE_NAME)
        refresh = _set_cookie_header(res, settings.REFRESH_COOKIE_NAME)
        assert access and refresh

        for header in (access, refresh):
            assert "HttpOnly" in header
            assert "SameSite=lax" in header.lower().replace("samesite=lax", "SameSite=lax")
            assert "Path=/" in header

    def test_cookie_alone_authenticates_without_authorization_header(
        self, client, test_user
    ):
        login = client.post(
            LOGIN_URL, json={"email": test_user.email, "password": PASSWORD}
        )
        assert settings.ACCESS_COOKIE_NAME in login.cookies

        # TestClient keeps the cookie jar — no Authorization header sent.
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == test_user.email

    def test_refresh_works_from_cookie_without_body(self, client, test_user):
        client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        res = client.post("/api/v1/auth/refresh", json={})
        assert res.status_code == 200
        assert res.json()["access_token"]

    def test_refresh_without_token_or_cookie_is_rejected(self, client):
        res = client.post("/api/v1/auth/refresh", json={})
        assert res.status_code == 401

    def test_logout_clears_cookies_and_blocks_cookie_auth(self, client, test_user):
        client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        assert client.get("/api/v1/auth/me").status_code == 200

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 200
        cleared = _set_cookie_header(logout, settings.ACCESS_COOKIE_NAME)
        assert cleared is not None and ('Max-Age=0' in cleared or 'expires=' in cleared.lower())

        assert client.get("/api/v1/auth/me").status_code == 401

    def test_secure_flag_follows_configuration(self, client, test_user, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", True)
        res = client.post(LOGIN_URL, json={"email": test_user.email, "password": PASSWORD})
        assert "Secure" in _set_cookie_header(res, settings.ACCESS_COOKIE_NAME)

    def test_unauthenticated_request_is_rejected(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401


# ═══════════════════════════════════════════════════════════════
# OAuth callback token exposure
# ═══════════════════════════════════════════════════════════════

class TestOAuthCallbackExposure:
    def _google_callback(self, client, monkeypatch, start_google_oauth):
        _configure_google(monkeypatch)
        state = start_google_oauth()

        with patch(
            "app.api.v1.endpoints.auth.httpx.Client",
            return_value=_google_http_client(),
        ):
            return client.get(
                CALLBACK_URL,
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )

    def test_callback_redirect_contains_no_tokens(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        res = self._google_callback(client, monkeypatch, start_google_oauth)
        assert res.status_code == 302

        location = res.headers["location"]
        assert "access_token" not in location
        assert "refresh_token" not in location
        assert "token=" not in location
        assert location.endswith("/oauth/callback?status=success")

    def test_callback_sets_httponly_session_cookies(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        res = self._google_callback(client, monkeypatch, start_google_oauth)
        header = _set_cookie_header(res, settings.ACCESS_COOKIE_NAME)
        assert header is not None
        assert "HttpOnly" in header

    def test_callback_session_authenticates(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        self._google_callback(client, monkeypatch, start_google_oauth)
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "secure.oauth@example.com"


# ═══════════════════════════════════════════════════════════════
# OAuth login-CSRF (anti-forgery `state`)
# ═══════════════════════════════════════════════════════════════

class TestOAuthStateCSRF:
    """The callback must only honour flows this browser actually started.

    Without a bound, single-use ``state`` an attacker can plant their own
    Google authorization code in a victim's browser and silently sign the
    victim into the attacker's account.
    """

    def _callback(self, client, *, code="auth-code", state=None):
        params = {"code": code}
        if state is not None:
            params["state"] = state

        http_client = _google_http_client()
        with patch(
            "app.api.v1.endpoints.auth.httpx.Client", return_value=http_client
        ):
            response = client.get(
                CALLBACK_URL, params=params, follow_redirects=False
            )
        return response, http_client

    def _assert_rejected(self, client, response, reason):
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("http://localhost:3000/login?error=")
        assert reason in location
        assert _set_cookie_header(response, settings.ACCESS_COOKIE_NAME) is None
        assert _set_cookie_header(response, settings.REFRESH_COOKIE_NAME) is None
        assert client.get("/api/v1/auth/me").status_code == 401

    # ── Authorization request ─────────────────────────────────────

    def test_authorization_request_carries_state_bound_to_a_cookie(
        self, client, monkeypatch
    ):
        _configure_google(monkeypatch)

        res = client.get("/api/v1/auth/oauth/google", follow_redirects=False)
        query = parse_qs(urlparse(res.headers["location"]).query)

        assert "state" in query
        assert query["state"][0] == res.cookies[settings.OAUTH_STATE_COOKIE_NAME]

    def test_state_cookie_is_httponly_and_short_lived(self, client, monkeypatch):
        _configure_google(monkeypatch)

        res = client.get("/api/v1/auth/oauth/google", follow_redirects=False)
        header = _set_cookie_header(res, settings.OAUTH_STATE_COOKIE_NAME)

        assert "HttpOnly" in header
        # Strict would drop the cookie on Google's top-level redirect back.
        assert "samesite=lax" in header.lower()
        assert f"Max-Age={settings.OAUTH_STATE_TTL_SECONDS}" in header

    def test_state_is_unpredictable_across_flows(self, client, monkeypatch):
        _configure_google(monkeypatch)

        issued = set()
        for _ in range(5):
            res = client.get("/api/v1/auth/oauth/google", follow_redirects=False)
            issued.add(parse_qs(urlparse(res.headers["location"]).query)["state"][0])

        assert len(issued) == 5
        assert all(len(value) > 40 for value in issued)

    # ── Callback validation ───────────────────────────────────────

    def test_valid_state_completes_the_login(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        _configure_google(monkeypatch)
        state = start_google_oauth()

        response, _ = self._callback(client, state=state)

        assert response.status_code == 302
        assert response.headers["location"].endswith("/oauth/callback?status=success")
        assert client.get("/api/v1/auth/me").status_code == 200

    def test_missing_state_is_rejected(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        _configure_google(monkeypatch)
        start_google_oauth()

        response, _ = self._callback(client, state=None)

        self._assert_rejected(client, response, "oauth_state_missing")

    def test_state_without_a_bound_cookie_is_rejected(
        self, client, db_session, monkeypatch
    ):
        """The classic forgery: an attacker's code + state, no prior flow."""
        _configure_google(monkeypatch)

        response, _ = self._callback(client, state=generate_state())

        self._assert_rejected(client, response, "oauth_state_missing")

    def test_mismatched_state_is_rejected(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        _configure_google(monkeypatch)
        start_google_oauth()

        response, _ = self._callback(client, state=generate_state())

        self._assert_rejected(client, response, "oauth_state_mismatch")

    def test_tampered_state_is_rejected(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        """Re-signing is impossible without SECRET_KEY, so edits are caught."""
        _configure_google(monkeypatch)
        state = start_google_oauth()

        version, nonce, expires, signature = state.split(".")
        forged = f"{version}.{nonce}.{int(expires) + 86400}.{signature}"
        _force_state_cookie(client, forged)

        response, _ = self._callback(client, state=forged)

        self._assert_rejected(client, response, "oauth_state_invalid")

    def test_replayed_state_is_rejected(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        """Single use is enforced server-side, not just by clearing the cookie."""
        _configure_google(monkeypatch)
        state = start_google_oauth()

        first, _ = self._callback(client, state=state)
        assert first.headers["location"].endswith("/oauth/callback?status=success")

        # Simulate an attacker who captured both the state and its cookie.
        _force_state_cookie(client, state)
        replay, _ = self._callback(client, state=state)

        assert replay.status_code == 302
        assert "oauth_state_replayed" in replay.headers["location"]

    def test_expired_state_is_rejected(self, client, db_session, monkeypatch):
        _configure_google(monkeypatch)

        with patch("app.core.oauth_state.time.time", return_value=time.time() - 3600):
            expired = generate_state()
        _force_state_cookie(client, expired)

        response, _ = self._callback(client, state=expired)

        self._assert_rejected(client, response, "oauth_state_expired")

    def test_rejected_state_never_exchanges_the_authorization_code(
        self, client, db_session, monkeypatch
    ):
        _configure_google(monkeypatch)

        response, http_client = self._callback(client, state=generate_state())

        assert response.status_code == 302
        http_client.post.assert_not_called()
        http_client.get.assert_not_called()

    def test_provider_error_short_circuits_without_state(self, client, monkeypatch):
        """Existing behaviour preserved: a provider error still bounces home."""
        _configure_google(monkeypatch)

        res = client.get(
            CALLBACK_URL, params={"error": "access_denied"}, follow_redirects=False
        )

        assert res.status_code == 302
        assert "access_denied" in res.headers["location"]

    def test_state_cookie_is_cleared_after_the_flow(
        self, client, db_session, monkeypatch, start_google_oauth
    ):
        _configure_google(monkeypatch)
        state = start_google_oauth()

        response, _ = self._callback(client, state=state)

        header = _set_cookie_header(response, settings.OAUTH_STATE_COOKIE_NAME)
        assert "Max-Age=0" in header
        assert settings.OAUTH_STATE_COOKIE_NAME not in client.cookies


# ═══════════════════════════════════════════════════════════════
# SECRET_KEY validation
# ═══════════════════════════════════════════════════════════════

def _settings(**overrides):
    """Build a Settings instance ignoring the developer's local .env."""
    base = {
        "_env_file": None,
        "ENVIRONMENT": "production",
        "SECRET_KEY": "x" * 64,
    }
    base.update(overrides)
    return Settings(**base)


class TestSecretKeyPolicy:
    def test_production_requires_a_secret_key(self):
        with pytest.raises(ValidationError) as exc:
            _settings(SECRET_KEY=None)
        assert "SECRET_KEY" in str(exc.value)

    def test_production_rejects_empty_secret_key(self):
        with pytest.raises(ValidationError):
            _settings(SECRET_KEY="   ")

    def test_production_rejects_short_secret_key(self):
        with pytest.raises(ValidationError) as exc:
            _settings(SECRET_KEY="tooshort")
        assert "32" in str(exc.value)

    @pytest.mark.parametrize(
        "weak", ["changeme", "your-secret-key", "secret", DEV_SECRET_KEY]
    )
    def test_production_rejects_placeholder_keys(self, weak):
        with pytest.raises(ValidationError):
            _settings(SECRET_KEY=weak)

    def test_production_rejects_insecure_cookies(self):
        with pytest.raises(ValidationError):
            _settings(AUTH_COOKIE_SECURE=False)

    def test_production_accepts_a_strong_key(self):
        cfg = _settings(SECRET_KEY="a" * 64)
        assert cfg.is_production is True
        assert cfg.cookies_secure is True

    def test_development_falls_back_to_a_stable_key(self):
        cfg = _settings(ENVIRONMENT="development", SECRET_KEY=None)
        # Stable (not random) so restarts do not silently invalidate sessions.
        assert cfg.SECRET_KEY == DEV_SECRET_KEY
        assert _settings(ENVIRONMENT="development", SECRET_KEY=None).SECRET_KEY == (
            cfg.SECRET_KEY
        )
        assert cfg.cookies_secure is False


# ═══════════════════════════════════════════════════════════════
# RBAC still holds after the hardening
# ═══════════════════════════════════════════════════════════════

class TestRbacUnchanged:
    def test_user_cannot_reach_admin_endpoints(self, client, auth_headers):
        assert client.get("/api/v1/admin/users", headers=auth_headers).status_code == 403

    def test_admin_can_reach_admin_endpoints(self, client, admin_headers):
        assert client.get("/api/v1/admin/users", headers=admin_headers).status_code == 200

    def test_coach_endpoints_require_coach_role(self, client, auth_headers, coach_headers):
        assert client.get("/api/v1/coach/clients", headers=auth_headers).status_code == 403
        assert client.get("/api/v1/coach/clients", headers=coach_headers).status_code == 200

    def test_forged_role_claim_is_ignored(self, client, test_user):
        forged = create_access_token({"sub": str(test_user.id), "role": "admin"})
        res = client.get(
            "/api/v1/admin/users", headers={"Authorization": f"Bearer {forged}"}
        )
        assert res.status_code == 403

    def test_deactivated_account_loses_access(self, client, test_user, db_session):
        login = client.post(
            LOGIN_URL, json={"email": test_user.email, "password": PASSWORD}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

        db_session.query(User).filter(User.id == test_user.id).update(
            {"is_active": False}
        )
        db_session.commit()

        assert client.get("/api/v1/auth/me", headers=headers).status_code == 403
