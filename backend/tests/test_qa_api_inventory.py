"""QA API inventory: route presence, auth gates, and known client mismatches."""

EXPECTED_AUTHENTICATED_GETS = [
    "/api/v1/auth/me",
    "/api/v1/users/profile",
    "/api/v1/users/profile/stats",
    "/api/v1/users/profile/preferences",
    "/api/v1/profiles/me",
    "/api/v1/profiles/me/habit-score",
    "/api/v1/alarms/",
    "/api/v1/alarms/upcoming",
    "/api/v1/alarms/challenge/stats",
    "/api/v1/alarms/challenge/analysis",
    "/api/v1/alarms/challenge/history",
    "/api/v1/recommendations",
    "/api/v1/recommendations/daily",
    "/api/v1/analytics/summary",
    "/api/v1/analytics/behavioral",
    "/api/v1/analytics/behavioral/snooze",
    "/api/v1/analytics/behavioral/wake-consistency",
    "/api/v1/analytics/behavioral/sleep-adherence",
    "/api/v1/analytics/behavioral/trends/weekly",
    "/api/v1/analytics/behavioral/trends/monthly",
    "/api/v1/analytics/behavioral/habits",
    "/api/v1/analytics/events",
]

# Password reset is intentionally not shipped (Login shows "not available yet")
UNIMPLEMENTED_AUTH_ROUTES = [
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
]


def _route_set(app):
    paths = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", None)
        if path:
            for method in methods:
                if method != "HEAD":
                    paths.add((method, path))
    return paths


class TestQaApiInventory:
    def test_public_health_and_root(self, client):
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"
        assert client.get("/").status_code == 200

    def test_expected_routes_registered(self):
        from app.main import app

        registered = _route_set(app)
        for path in EXPECTED_AUTHENTICATED_GETS:
            assert ("GET", path) in registered, f"Missing GET {path}"

    def test_authenticated_gets_return_200(self, client, auth_headers):
        for path in EXPECTED_AUTHENTICATED_GETS:
            res = client.get(path, headers=auth_headers)
            assert res.status_code == 200, f"{path} -> {res.status_code} {res.text}"

    def test_authenticated_gets_require_auth(self, client):
        for path in EXPECTED_AUTHENTICATED_GETS:
            res = client.get(path)
            assert res.status_code == 401, f"{path} should require auth"

    def test_habit_score_endpoints_agree(self, client, auth_headers, db_session, test_user):
        from app.models.profile import UserProfile
        from app.services.habit_score import calculate_habit_score

        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .first()
        )
        if profile is None:
            profile = UserProfile(
                user_id=test_user.id,
                wake_up_consistency_score=80.0,
                total_alarms_dismissed=8,
                total_snoozes=2,
                streak_days=15,
            )
            db_session.add(profile)
        else:
            profile.wake_up_consistency_score = 80.0
            profile.total_alarms_dismissed = 8
            profile.total_snoozes = 2
            profile.streak_days = 15
        db_session.commit()

        expected = calculate_habit_score(profile)["habit_score"]

        habit = client.get("/api/v1/profiles/me/habit-score", headers=auth_headers)
        assert habit.status_code == 200
        assert habit.json()["habit_score"] == expected

        stats = client.get("/api/v1/users/profile/stats", headers=auth_headers)
        assert stats.status_code == 200
        assert stats.json()["current_habit_score"] == expected

        behavioral = client.get(
            "/api/v1/analytics/behavioral/habits", headers=auth_headers
        )
        assert behavioral.status_code == 200
        assert behavioral.json()["current_habit_score"] == expected

    def test_preferences_get_returns_expected_shape(self, client, auth_headers):
        """BUG-001 fix: GET preferences mirrors the fields the SPA can PUT."""
        res = client.get("/api/v1/users/profile/preferences", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert "preferred_challenge_types" in body
        assert "difficulty_preference" in body
        assert "productivity_goals" in body
        assert isinstance(body["preferred_challenge_types"], list)

    def test_password_reset_routes_not_implemented(self, client):
        """Password reset is deferred; Login UI shows a not-available toast."""
        forgot = client.post(
            "/api/v1/auth/forgot-password", json={"email": "a@b.com"}
        )
        assert forgot.status_code in (404, 405)

        reset = client.post(
            "/api/v1/auth/reset-password",
            json={"token": "x", "new_password": "Password1!"},
        )
        assert reset.status_code in (404, 405)

        from app.main import app

        registered = _route_set(app)
        for method, path in UNIMPLEMENTED_AUTH_ROUTES:
            assert (method, path) not in registered
