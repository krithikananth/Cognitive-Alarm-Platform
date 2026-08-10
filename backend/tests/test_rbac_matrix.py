"""Role-matrix security tests: every role against every other role's surface.

Complements ``test_rbac.py`` (which covers the admin user-management happy
path) by asserting the full deny-matrix across all wired admin and coach
routes, plus the session/token attack surface: expired tokens, forged role
claims, refresh-token replay, deactivated accounts and cross-tenant IDOR.
"""

from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.models.coach_assignment import CoachAssignment
from app.models.user import User, UserRole
from app.utils.hashing import get_password_hash

# ── Route inventory (method, path) for each protected surface ───────────

ADMIN_ROUTES = [
    ("GET", "/api/v1/admin/dashboard"),
    ("GET", "/api/v1/admin/statistics"),
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/users/1"),
    ("GET", "/api/v1/admin/alarms"),
    ("GET", "/api/v1/admin/analytics"),
    ("GET", "/api/v1/admin/reports"),
    ("GET", "/api/v1/admin/recommendations"),
    ("GET", "/api/v1/admin/system-reports"),
    ("GET", "/api/v1/admin/system-reports/user_growth"),
    ("GET", "/api/v1/admin/system-reports/user_growth/export"),
    ("GET", "/api/v1/admin/notification-settings"),
    ("PUT", "/api/v1/admin/notification-settings"),
    ("GET", "/api/v1/admin/coach-assignments"),
    ("POST", "/api/v1/admin/coach-assignments"),
    ("DELETE", "/api/v1/admin/coach-assignments"),
    ("POST", "/api/v1/admin/announcements/broadcast"),
]

COACH_ROUTES = [
    ("GET", "/api/v1/coach/overview"),
    ("GET", "/api/v1/coach/clients"),
    ("GET", "/api/v1/coach/clients/1"),
    ("GET", "/api/v1/coach/clients/1/behavioral"),
    ("GET", "/api/v1/coach/clients/1/sleep-trends"),
    ("GET", "/api/v1/coach/clients/1/wake-consistency"),
    ("GET", "/api/v1/coach/clients/1/habit-score"),
    ("GET", "/api/v1/coach/clients/1/challenge-performance"),
    ("GET", "/api/v1/coach/clients/1/productivity"),
    ("GET", "/api/v1/coach/clients/1/recommendations"),
]

ADMIN_USER_MGMT_ROUTES = [
    ("GET", "/api/v1/users/"),
    ("GET", "/api/v1/users/1"),
    ("PUT", "/api/v1/users/1"),
    ("DELETE", "/api/v1/users/1"),
    ("POST", "/api/v1/users/1/activate"),
    ("POST", "/api/v1/users/1/deactivate"),
]


def call(client, method, path, headers=None):
    """Issue ``method path`` with an empty JSON body for write verbs."""
    kwargs = {"headers": headers} if headers else {}
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = {}
    elif method == "DELETE":
        kwargs.setdefault("params", {})
    return client.request(method, path, **kwargs)


# ── 1. USER role — denied everything privileged ─────────────────────────


class TestUserRoleDenied:
    """A ``user`` must be refused every admin and coach surface."""

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_user_cannot_reach_admin_routes(
        self, client, test_user, auth_headers, method, path
    ):
        assert call(client, method, path, auth_headers).status_code == 403

    @pytest.mark.parametrize("method,path", COACH_ROUTES)
    def test_user_cannot_reach_coach_routes(
        self, client, test_user, auth_headers, method, path
    ):
        assert call(client, method, path, auth_headers).status_code == 403

    @pytest.mark.parametrize("method,path", ADMIN_USER_MGMT_ROUTES)
    def test_user_cannot_reach_user_management(
        self, client, test_user, auth_headers, method, path
    ):
        assert call(client, method, path, auth_headers).status_code == 403


# ── 2. COACH role — denied admin, allowed own surface ───────────────────


class TestCoachRoleBoundary:
    """A ``wellness_coach`` gets the coach surface but never the admin one."""

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES)
    def test_coach_cannot_reach_admin_routes(
        self, client, coach_user, coach_headers, method, path
    ):
        assert call(client, method, path, coach_headers).status_code == 403

    @pytest.mark.parametrize("method,path", ADMIN_USER_MGMT_ROUTES)
    def test_coach_cannot_reach_user_management(
        self, client, coach_user, coach_headers, method, path
    ):
        assert call(client, method, path, coach_headers).status_code == 403

    def test_coach_can_read_own_roster(self, client, coach_user, coach_headers):
        assert client.get("/api/v1/coach/overview", headers=coach_headers).status_code == 200
        assert client.get("/api/v1/coach/clients", headers=coach_headers).status_code == 200

    def test_coach_cannot_read_unassigned_client(
        self, client, coach_user, test_user, coach_headers
    ):
        """No assignment row means the client is invisible (404, not 200)."""
        res = client.get(f"/api/v1/coach/clients/{test_user.id}", headers=coach_headers)
        assert res.status_code == 404

    def test_coach_can_read_assigned_client(
        self, client, db_session, coach_user, test_user, admin_user, coach_headers
    ):
        db_session.add(
            CoachAssignment(
                coach_id=coach_user.id,
                client_id=test_user.id,
                assigned_by_user_id=admin_user.id,
                is_active=True,
            )
        )
        db_session.commit()
        res = client.get(f"/api/v1/coach/clients/{test_user.id}", headers=coach_headers)
        assert res.status_code == 200
        assert res.json()["client"]["client_id"] == test_user.id

    def test_revoked_assignment_immediately_blocks_access(
        self, client, db_session, coach_user, test_user, admin_user, coach_headers
    ):
        assignment = CoachAssignment(
            coach_id=coach_user.id,
            client_id=test_user.id,
            assigned_by_user_id=admin_user.id,
            is_active=False,
        )
        db_session.add(assignment)
        db_session.commit()
        res = client.get(f"/api/v1/coach/clients/{test_user.id}", headers=coach_headers)
        assert res.status_code == 404

    def test_coach_cannot_read_other_coachs_client(
        self, client, db_session, coach_user, test_user, admin_user, coach_headers
    ):
        other_coach = User(
            email="coach2@example.com",
            username="coach2",
            hashed_password=get_password_hash("CoachPass123"),
            role=UserRole.WELLNESS_COACH,
            is_active=True,
            is_verified=True,
        )
        db_session.add(other_coach)
        db_session.commit()
        db_session.refresh(other_coach)
        db_session.add(
            CoachAssignment(
                coach_id=other_coach.id,
                client_id=test_user.id,
                assigned_by_user_id=admin_user.id,
                is_active=True,
            )
        )
        db_session.commit()
        res = client.get(f"/api/v1/coach/clients/{test_user.id}", headers=coach_headers)
        assert res.status_code == 404


# ── 3. ADMIN role — intended access is actually granted ─────────────────


class TestAdminRoleAccess:
    """An ``admin`` must not be locked out of the surfaces they own."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/admin/dashboard",
            "/api/v1/admin/statistics",
            "/api/v1/admin/users",
            "/api/v1/admin/alarms",
            "/api/v1/admin/analytics",
            "/api/v1/admin/reports",
            "/api/v1/admin/recommendations",
            "/api/v1/admin/system-reports",
            "/api/v1/admin/notification-settings",
            "/api/v1/admin/coach-assignments",
        ],
    )
    def test_admin_can_read_admin_routes(self, client, admin_user, admin_headers, path):
        assert client.get(path, headers=admin_headers).status_code == 200

    def test_admin_can_inspect_coach_surface(self, client, admin_user, admin_headers):
        assert client.get("/api/v1/coach/overview", headers=admin_headers).status_code == 200

    def test_admin_can_read_any_user(self, client, admin_user, test_user, admin_headers):
        res = client.get(f"/api/v1/admin/users/{test_user.id}", headers=admin_headers)
        assert res.status_code == 200


# ── 4. Unauthenticated / anonymous access ───────────────────────────────


class TestUnauthenticatedAccess:
    """Every protected route rejects a request carrying no credentials."""

    @pytest.mark.parametrize("method,path", ADMIN_ROUTES + COACH_ROUTES)
    def test_no_token_is_rejected(self, client, method, path):
        assert call(client, method, path).status_code == 401


# ── 5. Session / token attack surface ───────────────────────────────────


class TestTokenAndSessionSecurity:
    """Expired, forged, replayed and revoked credentials must all fail."""

    def test_expired_token_rejected(self, client, test_user):
        token = create_access_token(
            data={"sub": str(test_user.id), "role": test_user.role.value},
            expires_delta=timedelta(minutes=-5),
        )
        res = client.get(
            "/api/v1/users/profile", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401

    def test_token_signed_with_wrong_key_rejected(self, client, test_user):
        token = jwt.encode(
            {"sub": str(test_user.id), "role": "admin", "type": "access"},
            "attacker-controlled-secret",
            algorithm=settings.ALGORITHM,
        )
        res = client.get(
            "/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401

    def test_malformed_token_rejected(self, client):
        res = client.get(
            "/api/v1/admin/dashboard", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert res.status_code == 401

    def test_refresh_token_cannot_be_used_as_access_token(self, client, admin_user):
        token = create_refresh_token(
            data={"sub": str(admin_user.id), "role": admin_user.role.value}
        )
        res = client.get(
            "/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401

    def test_forged_admin_role_claim_is_ignored(self, client, test_user):
        """Privilege comes from the DB row, never from the token's role claim."""
        token = create_access_token(data={"sub": str(test_user.id), "role": "admin"})
        res = client.get(
            "/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 403

    def test_forged_coach_role_claim_is_ignored(self, client, test_user):
        token = create_access_token(
            data={"sub": str(test_user.id), "role": "wellness_coach"}
        )
        res = client.get(
            "/api/v1/coach/overview", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 403

    def test_token_for_unknown_subject_rejected(self, client):
        token = create_access_token(data={"sub": "999999", "role": "admin"})
        res = client.get(
            "/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 401

    def test_deactivated_admin_token_stops_working(
        self, client, db_session, admin_user, admin_headers
    ):
        """A still-valid JWT must not outlive the account's deactivation."""
        assert client.get("/api/v1/admin/dashboard", headers=admin_headers).status_code == 200
        admin_user.is_active = False
        db_session.commit()
        assert client.get("/api/v1/admin/dashboard", headers=admin_headers).status_code == 403

    def test_demoted_admin_loses_access_with_same_token(
        self, client, db_session, admin_user, admin_headers
    ):
        """Role downgrade takes effect on the next request, not next login."""
        assert client.get("/api/v1/admin/dashboard", headers=admin_headers).status_code == 200
        admin_user.role = UserRole.USER
        db_session.commit()
        assert client.get("/api/v1/admin/dashboard", headers=admin_headers).status_code == 403

    def test_promoted_user_gains_access_with_same_token(
        self, client, db_session, test_user, auth_headers
    ):
        assert client.get("/api/v1/admin/dashboard", headers=auth_headers).status_code == 403
        test_user.role = UserRole.ADMIN
        db_session.commit()
        assert client.get("/api/v1/admin/dashboard", headers=auth_headers).status_code == 200

    def test_missing_bearer_scheme_rejected(self, client, admin_user, admin_headers):
        raw = admin_headers["Authorization"].split(" ", 1)[1]
        res = client.get("/api/v1/admin/dashboard", headers={"Authorization": raw})
        assert res.status_code == 401


# ── 6. Horizontal privilege escalation (IDOR) ───────────────────────────


class TestHorizontalEscalation:
    """One user must never read or mutate another user's records."""

    def test_user_cannot_read_another_users_record(
        self, client, test_user, admin_user, auth_headers
    ):
        res = client.get(f"/api/v1/users/{admin_user.id}", headers=auth_headers)
        assert res.status_code == 403

    def test_user_cannot_escalate_own_role(self, client, test_user, auth_headers):
        res = client.put(
            f"/api/v1/users/{test_user.id}",
            json={"role": "admin"},
            headers=auth_headers,
        )
        assert res.status_code == 403

    def test_user_cannot_read_another_users_alarms(
        self, client, db_session, test_user, admin_user, auth_headers
    ):
        from datetime import time

        from app.models.alarm import Alarm

        alarm = Alarm(
            user_id=admin_user.id, title="Admin alarm", alarm_time=time(7, 0)
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)
        res = client.get(f"/api/v1/alarms/{alarm.id}", headers=auth_headers)
        assert res.status_code in (403, 404)
