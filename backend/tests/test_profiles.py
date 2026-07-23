"""Tests for user profile endpoints.

Aligned with the actual wired API (``app/api/v1/endpoints/profiles.py`` +
``app/schemas/profile.py``):
- Integer user IDs.
- Sleep-schedule / goals / habits updates are ``PATCH`` requests.
- Fields are ``preferred_wake_time`` (HH:MM:SS), ``sleep_duration_hours``,
  ``productivity_goals``, ``habit_preferences`` — there is no bio/avatar.
- ``habit_score`` is a computed float; the breakdown lives on
  ``GET /me/habit-score``.
"""


class TestGetProfile:
    """Tests for GET /api/v1/profiles/me."""

    def test_get_own_profile(self, client, test_user, auth_headers):
        """An authenticated user can retrieve their own profile."""
        response = client.get("/api/v1/profiles/me", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == test_user.id
        assert "id" in data
        assert data["timezone"] == "UTC"
        assert data["difficulty_preference"] == "medium"
        assert isinstance(data["habit_score"], (int, float))

    def test_profile_unauthorized(self, client):
        """Accessing the profile without authentication returns 401."""
        response = client.get("/api/v1/profiles/me")

        assert response.status_code == 401


class TestUpdateProfile:
    """Tests for PUT /api/v1/profiles/me."""

    def test_update_profile(self, client, test_user, auth_headers):
        """A user can update timezone, sleep target, and difficulty."""
        payload = {
            "timezone": "America/New_York",
            "sleep_duration_hours": 7.5,
            "difficulty_preference": "hard",
        }
        response = client.put(
            "/api/v1/profiles/me", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["timezone"] == "America/New_York"
        assert data["sleep_duration_hours"] == 7.5
        assert data["difficulty_preference"] == "hard"
        assert data["adapted_difficulty"] == "hard"

    def test_difficulty_preference_syncs_existing_alarms(
        self, client, test_user, auth_headers
    ):
        """Updating preference aligns existing alarms for future challenges."""
        created = client.post(
            "/api/v1/alarms/",
            json={"title": "Legacy", "alarm_time": "07:00", "challenge_difficulty": "easy"},
            headers=auth_headers,
        )
        assert created.status_code == 201
        alarm_id = created.json()["id"]
        assert created.json()["challenge_difficulty"] == "easy"

        updated = client.put(
            "/api/v1/profiles/me",
            json={"difficulty_preference": "expert"},
            headers=auth_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["difficulty_preference"] == "expert"

        alarm = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert alarm.status_code == 200
        assert alarm.json()["challenge_difficulty"] == "expert"

    def test_update_profile_partial(self, client, test_user, auth_headers):
        """Partial updates leave other fields at their defaults."""
        payload = {"sleep_duration_hours": 6.0}
        response = client.put(
            "/api/v1/profiles/me", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sleep_duration_hours"] == 6.0
        assert data["timezone"] == "UTC"  # Unchanged default

    def test_update_profile_invalid_timezone(self, client, test_user, auth_headers):
        """An unknown timezone is rejected with 422."""
        response = client.put(
            "/api/v1/profiles/me",
            json={"timezone": "Mars/Olympus_Mons"},
            headers=auth_headers,
        )

        assert response.status_code == 422


class TestAdaptiveDifficultyPersistence:
    """Tests for persisting adaptive difficulty onto adapted_difficulty only."""

    def test_persist_raises_adapted_on_consecutive_success(
        self, db_session, test_user
    ):
        """N consecutive successes raise adapted level; preference stays put."""
        from app.models.profile import UserProfile, DifficultyPreference
        from app.services.challenge_service import _adaptive_streak_threshold
        from app.services.profile_service import ProfileService

        profile = UserProfile(
            user_id=test_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            adapted_difficulty=DifficultyPreference.MEDIUM,
            consecutive_success_streak=_adaptive_streak_threshold(),
            consecutive_failure_streak=0,
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        updated = ProfileService.persist_adaptive_difficulty_if_needed(
            db_session, profile
        )
        assert updated is True
        db_session.refresh(profile)
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM
        assert profile.adapted_difficulty == DifficultyPreference.HARD
        assert profile.consecutive_success_streak == _adaptive_streak_threshold()
        assert profile.consecutive_failure_streak == 0
        assert (
            profile.last_adapted_success_streak == _adaptive_streak_threshold()
        )

    def test_persist_lowers_adapted_on_consecutive_failure(
        self, db_session, test_user
    ):
        """N consecutive failures lower adapted level; preference stays put."""
        from app.models.profile import UserProfile, DifficultyPreference
        from app.services.challenge_service import _adaptive_streak_threshold
        from app.services.profile_service import ProfileService

        profile = UserProfile(
            user_id=test_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.HARD,
            adapted_difficulty=DifficultyPreference.HARD,
            consecutive_success_streak=0,
            consecutive_failure_streak=_adaptive_streak_threshold(),
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        updated = ProfileService.persist_adaptive_difficulty_if_needed(
            db_session, profile
        )
        assert updated is True
        db_session.refresh(profile)
        assert profile.difficulty_preference == DifficultyPreference.HARD
        assert profile.adapted_difficulty == DifficultyPreference.MEDIUM
        assert profile.consecutive_success_streak == 0
        assert profile.consecutive_failure_streak == _adaptive_streak_threshold()
        assert (
            profile.last_adapted_failure_streak == _adaptive_streak_threshold()
        )

    def test_persist_noop_below_streak_threshold(self, db_session, test_user):
        """Streaks below N must not change preference or adapted level."""
        from app.models.profile import UserProfile, DifficultyPreference
        from app.services.challenge_service import _adaptive_streak_threshold
        from app.services.profile_service import ProfileService

        below = _adaptive_streak_threshold() - 1
        profile = UserProfile(
            user_id=test_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            adapted_difficulty=DifficultyPreference.MEDIUM,
            consecutive_success_streak=below,
            consecutive_failure_streak=0,
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        updated = ProfileService.persist_adaptive_difficulty_if_needed(
            db_session, profile
        )
        assert updated is False
        db_session.refresh(profile)
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM
        assert profile.adapted_difficulty == DifficultyPreference.MEDIUM
        assert profile.consecutive_success_streak == below

    def test_persist_noop_when_profile_missing(self, db_session):
        """Missing profile is a no-op (does not raise)."""
        from app.services.profile_service import ProfileService

        assert (
            ProfileService.persist_adaptive_difficulty_if_needed(
                db_session, None, []
            )
            is False
        )

    def test_update_adaptive_streaks_success_and_reset(
        self, db_session, test_user
    ):
        """Success increments success streak and clears failure streak."""
        from app.models.profile import UserProfile, DifficultyPreference
        from app.services.profile_service import ProfileService

        profile = UserProfile(
            user_id=test_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            consecutive_success_streak=2,
            consecutive_failure_streak=3,
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        ProfileService.update_adaptive_streaks(
            db_session, profile, is_correct=True
        )
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 3
        assert profile.consecutive_failure_streak == 0

    def test_update_adaptive_streaks_failure_resets_success(
        self, db_session, test_user
    ):
        """Failure increments failure streak and clears success streak."""
        from app.models.profile import UserProfile, DifficultyPreference
        from app.services.profile_service import ProfileService

        profile = UserProfile(
            user_id=test_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            consecutive_success_streak=4,
            consecutive_failure_streak=0,
        )
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)

        ProfileService.update_adaptive_streaks(
            db_session, profile, is_correct=False
        )
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 0
        assert profile.consecutive_failure_streak == 1


class TestSleepSchedule:
    """Tests for PATCH /api/v1/profiles/me/sleep-schedule."""

    def test_update_sleep_schedule(self, client, test_user, auth_headers):
        """A user can set their wake time and sleep duration target."""
        payload = {
            "preferred_wake_time": "06:30",
            "sleep_duration_hours": 8.0,
        }
        response = client.patch(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["preferred_wake_time"] == "06:30:00"
        assert data["sleep_duration_hours"] == 8.0

    def test_update_sleep_schedule_invalid_time(self, client, test_user, auth_headers):
        """An invalid time value is rejected with 422."""
        payload = {"preferred_wake_time": "25:00"}
        response = client.patch(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 422

    def test_update_sleep_schedule_partial(self, client, test_user, auth_headers):
        """Only supplied sleep-schedule fields are updated."""
        payload = {"preferred_wake_time": "07:00"}
        response = client.patch(
            "/api/v1/profiles/me/sleep-schedule", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["preferred_wake_time"] == "07:00:00"


class TestGoals:
    """Tests for PATCH /api/v1/profiles/me/goals."""

    def test_update_goals(self, client, test_user, auth_headers):
        """A user can set their productivity goals list."""
        payload = {
            "productivity_goals": ["Wake up early", "Exercise daily", "Read 30 minutes"]
        }
        response = client.patch(
            "/api/v1/profiles/me/goals", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["productivity_goals"] == [
            "Wake up early",
            "Exercise daily",
            "Read 30 minutes",
        ]

    def test_update_goals_empty(self, client, test_user, auth_headers):
        """A user can clear their goals with an empty list."""
        payload = {"productivity_goals": []}
        response = client.patch(
            "/api/v1/profiles/me/goals", json=payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["productivity_goals"] == []


class TestHabitPreferences:
    """Tests for PATCH /api/v1/profiles/me/habits."""

    def test_update_habit_preferences(self, client, test_user, auth_headers):
        """A user can set arbitrary habit preferences."""
        payload = {
            "habit_preferences": {
                "morning_routine": True,
                "meditation": True,
                "exercise_type": "yoga",
                "water_intake_glasses": 8,
            }
        }
        response = client.patch(
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
        """A user can retrieve their weighted habit score with breakdown."""
        response = client.get(
            "/api/v1/profiles/me/habit-score", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["habit_score"], (int, float))
        assert "breakdown" in data
        assert "weights" in data
        assert data["breakdown"].keys() >= {
            "wake_up_consistency",
            "challenge_completion",
            "snooze_reduction",
            "sleep_adherence",
        }
        assert data["weights"] == {
            "wake_up_consistency": 0.35,
            "challenge_completion": 0.25,
            "snooze_reduction": 0.20,
            "sleep_adherence": 0.20,
        }

    def test_get_habit_score_unauthorized(self, client):
        """Unauthenticated access to habit score returns 401."""
        response = client.get("/api/v1/profiles/me/habit-score")

        assert response.status_code == 401
