"""Tests for user profile endpoints.

Covers getting own profile, updating profile fields, sleep schedule,
goals, habit preferences, habit score retrieval, and unauthorized access.
"""


class TestGetProfile:
    """Tests for GET /api/v1/profiles/me."""

    def test_get_own_profile(self, client, test_user, auth_headers):
        """Test that an authenticated user can retrieve their own profile."""
        response = client.get("/api/v1/profiles/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(test_user.id)
        assert "id" in data
        assert data["timezone"] == "UTC"
        assert data["habit_score"] == 0.0

    def test_profile_unauthorized(self, client):
        """Test that accessing profile without authentication returns 401."""
        response = client.get("/api/v1/profiles/me")

        assert response.status_code == 401


class TestUpdateProfile:
    """Tests for PUT /api/v1/profiles/me."""

    def test_update_profile(self, client, test_user, auth_headers):
        """Test that a user can update their profile bio, avatar, and timezone."""
        payload = {
            "bio": "I love mornings!",
            "avatar_url": "https://example.com/avatar.png",
            "timezone": "America/New_York",
        }
        response = client.put(
            "/api/v1/profiles/me", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["bio"] == "I love mornings!"
        assert data["avatar_url"] == "https://example.com/avatar.png"
        assert data["timezone"] == "America/New_York"

    def test_update_profile_partial(self, client, test_user, auth_headers):
        """Test that a user can partially update their profile (only some fields)."""
        payload = {"bio": "Just updating bio"}
        response = client.put(
            "/api/v1/profiles/me", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["bio"] == "Just updating bio"
        # Other fields should remain at defaults
        assert data["timezone"] == "UTC"


class TestSleepSchedule:
    """Tests for PUT /api/v1/profiles/me/sleep-schedule."""

    def test_update_sleep_schedule(self, client, test_user, auth_headers):
        """Test that a user can set their sleep schedule with valid times."""
        payload = {
            "sleep_time": "22:30",
            "wake_time": "06:30",
            "sleep_duration_target": 8.0,
        }
        response = client.put(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sleep_time"] == "22:30"
        assert data["wake_time"] == "06:30"
        assert data["sleep_duration_target"] == 8.0

    def test_update_sleep_schedule_invalid_time(self, client, test_user, auth_headers):
        """Test that invalid time formats are rejected with 422."""
        payload = {
            "sleep_time": "25:00",  # Invalid hour
            "wake_time": "06:30",
        }
        response = client.put(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 422

    def test_update_sleep_schedule_partial(self, client, test_user, auth_headers):
        """Test that only some sleep schedule fields can be updated."""
        payload = {"wake_time": "07:00"}
        response = client.put(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["wake_time"] == "07:00"


class TestGoals:
    """Tests for PUT /api/v1/profiles/me/goals."""

    def test_update_goals(self, client, test_user, auth_headers):
        """Test that a user can set their goals list."""
        payload = {"goals": ["Wake up early", "Exercise daily", "Read 30 minutes"]}
        response = client.put(
            "/api/v1/profiles/me/goals", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["goals"] == ["Wake up early", "Exercise daily", "Read 30 minutes"]

    def test_update_goals_empty(self, client, test_user, auth_headers):
        """Test that a user can clear their goals by setting an empty list."""
        payload = {"goals": []}
        response = client.put(
            "/api/v1/profiles/me/goals", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["goals"] == []


class TestHabitPreferences:
    """Tests for PUT /api/v1/profiles/me/habits."""

    def test_update_habit_preferences(self, client, test_user, auth_headers):
        """Test that a user can set their habit preferences."""
        payload = {
            "habit_preferences": {
                "morning_routine": True,
                "meditation": True,
                "exercise_type": "yoga",
                "water_intake_glasses": 8,
            }
        }
        response = client.put(
            "/api/v1/profiles/me/habits", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["habit_preferences"]["morning_routine"] is True
        assert data["habit_preferences"]["meditation"] is True
        assert data["habit_preferences"]["exercise_type"] == "yoga"
        assert data["habit_preferences"]["water_intake_glasses"] == 8


class TestHabitScore:
    """Tests for GET /api/v1/profiles/me/habit-score."""

    def test_get_habit_score(self, client, test_user, auth_headers):
        """Test that a user can retrieve their habit score (defaults to 0.0)."""
        response = client.get(
            "/api/v1/profiles/me/habit-score", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == str(test_user.id)
        assert data["habit_score"] == 0.0

    def test_get_habit_score_unauthorized(self, client):
        """Test that unauthenticated access to habit score returns 401."""
        response = client.get("/api/v1/profiles/me/habit-score")

        assert response.status_code == 401
