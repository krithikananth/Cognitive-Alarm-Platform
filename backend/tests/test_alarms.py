"""Tests for alarm management endpoints.

Aligned with the actual wired API (``app/api/v1/endpoints/alarms.py`` +
``app/schemas/alarm.py``):
- Integer alarm/user IDs.
- ``alarm_time`` is serialized as ``HH:MM:SS``.
- Listing returns a paginated ``{alarms, total, page, per_page}`` object.
- Toggle is ``PATCH /{id}/toggle`` with ``{"is_active": ...}``.
- Snooze/dismiss return the full ``AlarmResponse``.
"""

from datetime import date, datetime, time, timezone

import pytest

from app.api.v1.endpoints import alarms as alarms_module
from app.models.alarm import Alarm, AlarmType

# Reference calendar used by the scheduling tests (August 2026):
#   Mon 10 · Tue 11 · Wed 12 · Thu 13 · Fri 14 · Sat 15 · Sun 16 · Mon 17
WED = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
FRI = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)
SAT = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
SUN = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


def _freeze_now(monkeypatch, moment):
    """Pin ``datetime.now`` inside the alarms endpoint module to ``moment``."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(alarms_module, "datetime", _Frozen)


def _alarm(alarm_type, alarm_time, days_of_week=None, one_time_date=None):
    """Build an unpersisted Alarm for direct next-trigger calculations."""
    return Alarm(
        user_id=1,
        title="Scheduling",
        alarm_time=alarm_time,
        alarm_type=alarm_type,
        days_of_week=days_of_week,
        one_time_date=one_time_date,
    )


def _next_trigger(alarm, user_tz="UTC"):
    """Next trigger as a naive UTC datetime (matches the stored column)."""
    return alarms_module._calculate_next_trigger(alarm, user_tz=user_tz)


class TestCreateAlarm:
    """Tests for POST /api/v1/alarms/."""

    def test_create_alarm(self, client, test_user, auth_headers):
        """An authenticated user can create an alarm with valid data."""
        payload = {
            "title": "Morning Workout",
            "description": "Time to exercise!",
            "alarm_time": "06:30",
            "alarm_type": "one_time",
            "one_time_date": "2026-07-15",
            "snooze_interval_minutes": 5,
            "snooze_limit": 3,
            "challenge_type": "math",
            "challenge_count": 2,
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Morning Workout"
        assert data["description"] == "Time to exercise!"
        assert data["alarm_time"] == "06:30:00"
        assert data["is_active"] is True
        assert data["user_id"] == test_user.id
        assert data["challenge_type"] == "math"
        assert data["challenge_count"] == 2
        assert data["challenge_difficulty"] == "medium"
        assert data["snooze_limit"] == 3
        assert "id" in data

    def test_create_alarm_with_difficulty(self, client, test_user, auth_headers):
        """Per-alarm challenge_difficulty is persisted for storage/UI."""
        payload = {
            "title": "Hard Morning",
            "alarm_time": "06:00",
            "challenge_type": "math",
            "challenge_difficulty": "hard",
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["challenge_difficulty"] == "hard"

        # Challenge adaptive baseline uses profile preference (default medium),
        # not the per-alarm stored value — profile is the adaptive SSOT.
        ch = client.get(
            f"/api/v1/alarms/{data['id']}/challenge", headers=auth_headers
        )
        assert ch.status_code == 200
        body = ch.json()
        assert body["difficulty"] in {
            "beginner", "easy", "medium", "hard", "expert"
        }
        assert body["adaptive_difficulty"]["difficulty"] == "medium"
        assert body["adaptive_difficulty"]["adjustment"] == 0

    def test_create_alarm_seeds_difficulty_from_profile(
        self, client, test_user, auth_headers
    ):
        """Omitting challenge_difficulty seeds from profile preference."""
        pref = client.put(
            "/api/v1/profiles/me",
            json={"difficulty_preference": "beginner"},
            headers=auth_headers,
        )
        assert pref.status_code == 200

        response = client.post(
            "/api/v1/alarms/",
            json={"title": "Seeded", "alarm_time": "08:00", "challenge_type": "math"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["challenge_difficulty"] == "beginner"

    def test_challenge_uses_profile_preference_baseline(
        self, client, test_user, auth_headers
    ):
        """Future challenges use profile preference as the adaptive baseline."""
        # Existing-style alarm stored at medium
        created = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Existing",
                "alarm_time": "09:00",
                "challenge_type": "math",
                "challenge_difficulty": "medium",
            },
            headers=auth_headers,
        )
        assert created.status_code == 201
        alarm_id = created.json()["id"]

        pref = client.put(
            "/api/v1/users/profile/preferences",
            json={"difficulty_preference": "expert"},
            headers=auth_headers,
        )
        assert pref.status_code == 200

        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        assert ch.status_code == 200
        body = ch.json()
        # Adaptive center (pre time-of-day) should be the preferred level
        assert body["adaptive_difficulty"]["difficulty"] == "expert"
        assert body["adaptive_difficulty"]["adjustment"] == 0
        assert body["difficulty"] in {
            "beginner", "easy", "medium", "hard", "expert"
        }

    def test_adaptive_difficulty_persists_to_adapted_level(
        self, client, test_user, auth_headers, db_session
    ):
        """Adaptive ±1 is saved to adapted_difficulty; preference stays user-set."""
        from app.models.profile import DifficultyPreference, UserProfile
        from app.services.challenge_service import _adaptive_streak_threshold

        # Ensure profile exists at medium
        pref = client.get("/api/v1/profiles/me", headers=auth_headers)
        assert pref.status_code == 200
        assert pref.json()["difficulty_preference"] == "medium"

        created = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Adaptive Persist",
                "alarm_time": "07:30",
                "challenge_type": "math",
                "challenge_difficulty": "medium",
            },
            headers=auth_headers,
        )
        assert created.status_code == 201
        alarm_id = created.json()["id"]

        # Seed N consecutive successes on the stored streak counters
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        profile.consecutive_success_streak = _adaptive_streak_threshold()
        profile.consecutive_failure_streak = 0
        db_session.commit()

        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        assert ch.status_code == 200
        assert ch.json()["adaptive_difficulty"]["adjustment"] == 1
        assert ch.json()["adaptive_difficulty"]["difficulty"] == "hard"

        db_session.refresh(profile)
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM
        assert profile.adapted_difficulty == DifficultyPreference.HARD
        assert profile.consecutive_success_streak == _adaptive_streak_threshold()
        assert profile.consecutive_failure_streak == 0

        # Preference API still reflects the user-controlled value
        again = client.get("/api/v1/profiles/me", headers=auth_headers)
        assert again.status_code == 200
        assert again.json()["difficulty_preference"] == "medium"
        assert again.json()["adapted_difficulty"] == "hard"

        # Alarm baseline stays aligned with adapted level for future sessions
        alarm = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert alarm.status_code == 200
        assert alarm.json()["challenge_difficulty"] == "hard"

        # Display streak survives adapt; next challenge must not re-raise.
        ch2 = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        assert ch2.status_code == 200
        assert ch2.json()["adaptive_difficulty"]["adjustment"] == 0
        assert ch2.json()["adaptive_difficulty"]["success_streak"] == (
            _adaptive_streak_threshold()
        )
        assert ch2.json()["adaptive_difficulty"]["difficulty"] == "hard"

    def test_create_alarm_minimal(self, client, test_user, auth_headers):
        """Creating an alarm with only the required fields uses sensible defaults."""
        payload = {
            "title": "Quick Alarm",
            "alarm_time": "08:00",
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Quick Alarm"
        assert data["alarm_time"] == "08:00:00"
        assert data["alarm_type"] == "daily"
        assert data["challenge_type"] == "random"
        assert data["challenge_difficulty"] == "medium"
        assert data["vibrate"] is True
        assert data["volume"] == 80

    def test_create_alarm_invalid_time(self, client, test_user, auth_headers):
        """Creating an alarm with an out-of-range time returns 422."""
        payload = {
            "title": "Bad Alarm",
            "alarm_time": "25:99",  # Invalid time
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 422

    def test_create_alarm_invalid_time_format(self, client, test_user, auth_headers):
        """A non HH:MM(:SS) time format is rejected."""
        payload = {
            "title": "Bad Format",
            "alarm_time": "6:30am",  # Wrong format
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 422


class TestListAlarms:
    """Tests for GET /api/v1/alarms/ (paginated)."""

    def test_list_alarms(self, client, test_user, auth_headers):
        """A user can list their own alarms in a paginated envelope."""
        for title in ["Alarm A", "Alarm B"]:
            client.post(
                "/api/v1/alarms/",
                json={"title": title, "alarm_time": "07:00"},
                headers=auth_headers,
            )

        response = client.get("/api/v1/alarms/", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["page"] == 1
        assert isinstance(data["alarms"], list)
        titles = [a["title"] for a in data["alarms"]]
        assert "Alarm A" in titles
        assert "Alarm B" in titles

    def test_list_alarms_empty(self, client, test_user, auth_headers):
        """Listing with no alarms returns an empty page."""
        response = client.get("/api/v1/alarms/", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["alarms"] == []


class TestGetAlarm:
    """Tests for GET /api/v1/alarms/{alarm_id}."""

    def test_get_alarm(self, client, test_user, auth_headers):
        """A user can retrieve a specific alarm by its ID."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Fetch Me", "alarm_time": "09:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == alarm_id
        assert data["title"] == "Fetch Me"

    def test_get_alarm_not_found(self, client, test_user, auth_headers):
        """Requesting a non-existent alarm ID returns 404."""
        response = client.get("/api/v1/alarms/999999", headers=auth_headers)

        assert response.status_code == 404
        assert "Alarm not found" in response.json()["detail"]


class TestUpdateAlarm:
    """Tests for PUT /api/v1/alarms/{alarm_id}."""

    def test_update_alarm(self, client, test_user, auth_headers):
        """A user can update an alarm's title and time."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Original Title", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        update_payload = {
            "title": "Updated Title",
            "alarm_time": "08:30",
            "description": "Updated description",
        }
        response = client.put(
            f"/api/v1/alarms/{alarm_id}", json=update_payload, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["alarm_time"] == "08:30:00"
        assert data["description"] == "Updated description"

    def test_update_alarm_partial(self, client, test_user, auth_headers):
        """Only supplied fields are updated; others remain unchanged."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Keep This", "alarm_time": "07:00", "volume": 55},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.put(
            f"/api/v1/alarms/{alarm_id}",
            json={"description": "Added description"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Keep This"  # Unchanged
        assert data["alarm_time"] == "07:00:00"  # Unchanged
        assert data["volume"] == 55  # Unchanged
        assert data["description"] == "Added description"  # Updated

    def test_update_alarm_not_found(self, client, test_user, auth_headers):
        """Updating a non-existent alarm returns 404."""
        response = client.put(
            "/api/v1/alarms/999999",
            json={"title": "Nope"},
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestDeleteAlarm:
    """Tests for DELETE /api/v1/alarms/{alarm_id}."""

    def test_delete_alarm(self, client, test_user, auth_headers):
        """A user can delete their own alarm."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Delete Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.delete(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert response.status_code == 204

        get_response = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert get_response.status_code == 404

    def test_delete_alarm_not_found(self, client, test_user, auth_headers):
        """Deleting a non-existent alarm returns 404."""
        response = client.delete("/api/v1/alarms/999999", headers=auth_headers)

        assert response.status_code == 404


class TestToggleAlarm:
    """Tests for PATCH /api/v1/alarms/{alarm_id}/toggle."""

    def test_toggle_alarm_disable(self, client, test_user, auth_headers):
        """Disabling an alarm via toggle sets is_active=False."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Toggle Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    def test_toggle_alarm_enable(self, client, test_user, auth_headers):
        """Re-enabling a disabled alarm sets is_active=True and recomputes trigger."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Re-enable Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": False},
            headers=auth_headers,
        )

        response = client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True
        assert data["next_trigger_at"] is not None


class TestUpcomingAlarms:
    """Tests for GET /api/v1/alarms/upcoming."""

    def test_get_upcoming_alarms(self, client, test_user, auth_headers):
        """Retrieving upcoming active alarms returns them as a list."""
        for t in ["09:00", "06:00", "12:00"]:
            client.post(
                "/api/v1/alarms/",
                json={"title": f"Alarm at {t}", "alarm_time": t},
                headers=auth_headers,
            )

        response = client.get("/api/v1/alarms/upcoming", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3
        # Results are ordered by next_trigger_at (non-decreasing).
        triggers = [a["next_trigger_at"] for a in data]
        assert triggers == sorted(triggers)

    def test_get_upcoming_alarms_excludes_disabled(self, client, test_user, auth_headers):
        """Disabled alarms are not included in upcoming results."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Disabled", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]
        client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": False},
            headers=auth_headers,
        )

        client.post(
            "/api/v1/alarms/",
            json={"title": "Enabled", "alarm_time": "08:00"},
            headers=auth_headers,
        )

        response = client.get("/api/v1/alarms/upcoming", headers=auth_headers)

        assert response.status_code == 200
        titles = [a["title"] for a in response.json()]
        assert "Disabled" not in titles
        assert "Enabled" in titles


class TestSnoozeAlarm:
    """Tests for POST /api/v1/alarms/{alarm_id}/snooze."""

    def test_snooze_alarm(self, client, test_user, auth_headers):
        """Snoozing an alarm increments its snooze counter."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Snooze Me", "alarm_time": "07:00", "snooze_limit": 3},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_snoozes"] == 1
        assert data["next_trigger_at"] is not None

    def test_snooze_alarm_max_reached(self, client, test_user, auth_headers):
        """Snoozing beyond the configured limit returns 400."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Limited Snooze", "alarm_time": "07:00", "snooze_limit": 1},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        # First snooze (allowed)
        response1 = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert response1.status_code == 200

        # Second snooze (limit reached)
        response2 = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert response2.status_code == 400
        assert "Maximum snooze limit reached" in response2.json()["detail"]

    def test_snooze_disabled_when_limit_zero(self, client, test_user, auth_headers):
        """snooze_limit=0 is strict anti-snooze — first snooze is rejected."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "No Snooze", "alarm_time": "07:00", "snooze_limit": 0},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        info = client.get(
            f"/api/v1/alarms/{alarm_id}/snooze-info", headers=auth_headers
        ).json()
        assert info["can_snooze"] is False
        assert info["anti_snooze_enforced"] is True

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert response.status_code == 400


class TestDismissAlarm:
    """Tests for POST /api/v1/alarms/{alarm_id}/dismiss."""

    def test_dismiss_without_challenge_forbidden(self, client, test_user, auth_headers):
        """Dismiss without wake-up verification must be rejected."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Dismiss Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss", headers=auth_headers
        )

        assert response.status_code == 403
        assert "verification" in response.json()["detail"].lower()

    def test_dismiss_alarm_not_found(self, client, test_user, auth_headers):
        """Dismissing a non-existent alarm returns 404."""
        response = client.post(
            "/api/v1/alarms/999999/dismiss", headers=auth_headers
        )

        assert response.status_code == 404


class TestAlarmUnauthorized:
    """Tests that alarm endpoints require authentication."""

    def test_alarm_unauthorized(self, client):
        """All alarm endpoints reject unauthenticated access with 401."""
        assert client.post(
            "/api/v1/alarms/",
            json={"title": "No Auth", "alarm_time": "07:00"},
        ).status_code == 401

        assert client.get("/api/v1/alarms/").status_code == 401
        assert client.get("/api/v1/alarms/upcoming").status_code == 401
        assert client.get("/api/v1/alarms/1").status_code == 401
        assert client.put(
            "/api/v1/alarms/1", json={"title": "Updated"}
        ).status_code == 401
        assert client.delete("/api/v1/alarms/1").status_code == 401
        assert client.patch(
            "/api/v1/alarms/1/toggle", json={"is_active": False}
        ).status_code == 401
        assert client.post("/api/v1/alarms/1/snooze").status_code == 401
        assert client.post("/api/v1/alarms/1/dismiss").status_code == 401


class TestNextTriggerCalculation:
    """Regression tests for ``_calculate_next_trigger`` on every alarm type.

    ``now`` is frozen so each expected trigger is an exact datetime rather than
    a property that happens to hold on the day the suite runs.
    """

    # ── Daily ────────────────────────────────────────────────────

    def test_daily_later_today(self, monkeypatch):
        """A daily alarm still ahead of now fires today."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(10, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 12, 10, 0)

    def test_daily_rolls_to_tomorrow(self, monkeypatch):
        """A daily alarm whose time has passed fires tomorrow."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 13, 7, 0)

    def test_daily_respects_user_timezone(self, monkeypatch):
        """alarm_time is wall-clock local and is converted to UTC."""
        # 20:00 UTC Wed == 01:30 Thu in Asia/Kolkata (UTC+5:30)
        _freeze_now(monkeypatch, datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc))
        alarm = _alarm(AlarmType.DAILY, time(7, 0))
        assert _next_trigger(alarm, "Asia/Kolkata") == datetime(2026, 8, 13, 1, 30)

    # ── Weekday ──────────────────────────────────────────────────

    def test_weekday_midweek_rolls_to_next_day(self, monkeypatch):
        """Wednesday → Thursday for a Mon-Fri alarm."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.WEEKDAY, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 13, 7, 0)

    def test_weekday_skips_the_weekend(self, monkeypatch):
        """Friday after the alarm time jumps the weekend to Monday."""
        _freeze_now(monkeypatch, FRI)
        alarm = _alarm(AlarmType.WEEKDAY, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 17, 7, 0)

    def test_weekday_on_saturday_targets_monday(self, monkeypatch):
        """A weekday alarm never fires on a Saturday or Sunday."""
        _freeze_now(monkeypatch, SAT)
        alarm = _alarm(AlarmType.WEEKDAY, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 17, 7, 0)

    # ── Weekend ──────────────────────────────────────────────────

    def test_weekend_from_midweek_targets_saturday(self, monkeypatch):
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.WEEKEND, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 15, 7, 0)

    def test_weekend_on_saturday_rolls_to_sunday(self, monkeypatch):
        _freeze_now(monkeypatch, SAT)
        alarm = _alarm(AlarmType.WEEKEND, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 16, 7, 0)

    def test_weekend_on_sunday_wraps_to_next_saturday(self, monkeypatch):
        """The forward scan must wrap a full week, not stop at 7 offsets."""
        _freeze_now(monkeypatch, SUN)
        alarm = _alarm(AlarmType.WEEKEND, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 22, 7, 0)

    # ── Custom days ──────────────────────────────────────────────

    def test_custom_days_pick_the_next_selected_weekday(self, monkeypatch):
        """Mon/Wed/Fri from Wednesday morning-passed → Friday."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(7, 0), days_of_week=[0, 2, 4])
        assert _next_trigger(alarm) == datetime(2026, 8, 14, 7, 0)

    def test_custom_days_can_still_fire_later_today(self, monkeypatch):
        """Today is selected and the time has not passed → today."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(10, 0), days_of_week=[0, 2, 4])
        assert _next_trigger(alarm) == datetime(2026, 8, 12, 10, 0)

    def test_single_custom_day_wraps_a_full_week(self, monkeypatch):
        """Wednesday-only, already past → the following Wednesday."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(7, 0), days_of_week=[2])
        assert _next_trigger(alarm) == datetime(2026, 8, 19, 7, 0)

    def test_custom_days_narrow_the_weekday_pattern(self, monkeypatch):
        """Mon/Sat/Sun on a weekday alarm resolves to Monday only."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.WEEKDAY, time(7, 0), days_of_week=[0, 5, 6])
        assert _next_trigger(alarm) == datetime(2026, 8, 17, 7, 0)

    def test_custom_days_disjoint_from_pattern_fall_back_to_pattern(
        self, monkeypatch
    ):
        """A selection excluding every base day must not strand the alarm."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.WEEKEND, time(7, 0), days_of_week=[0, 1, 2])
        assert _next_trigger(alarm) == datetime(2026, 8, 15, 7, 0)

    def test_empty_custom_days_keep_pattern_defaults(self, monkeypatch):
        """An empty list behaves exactly like no selection at all."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.DAILY, time(7, 0), days_of_week=[])
        assert _next_trigger(alarm) == datetime(2026, 8, 13, 7, 0)

    def test_custom_days_apply_to_smart_adaptive(self, monkeypatch):
        """Smart alarms without DB context still honour the day filter."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.SMART_ADAPTIVE, time(7, 0), days_of_week=[5, 6])
        assert _next_trigger(alarm) == datetime(2026, 8, 15, 7, 0)

    # ── One-time ─────────────────────────────────────────────────

    def test_one_time_uses_stored_date(self, monkeypatch):
        """The stored date drives the trigger, not 'today or tomorrow'."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(
            AlarmType.ONE_TIME, time(7, 0), one_time_date=date(2026, 8, 20)
        )
        assert _next_trigger(alarm) == datetime(2026, 8, 20, 7, 0)

    def test_one_time_explicit_argument_wins(self, monkeypatch):
        """The create request's date takes precedence over a stored one."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(
            AlarmType.ONE_TIME, time(7, 0), one_time_date=date(2026, 8, 20)
        )
        result = alarms_module._calculate_next_trigger(
            alarm, user_tz="UTC", one_time_date=date(2026, 8, 18)
        )
        assert result == datetime(2026, 8, 18, 7, 0)

    def test_one_time_in_the_past_has_no_trigger(self, monkeypatch):
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(
            AlarmType.ONE_TIME, time(7, 0), one_time_date=date(2026, 8, 11)
        )
        assert _next_trigger(alarm) is None

    def test_one_time_ignores_days_of_week(self, monkeypatch):
        """A dated one-time alarm fires on its date whatever days are set."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(
            AlarmType.ONE_TIME,
            time(7, 0),
            days_of_week=[0],
            one_time_date=date(2026, 8, 20),
        )
        assert _next_trigger(alarm) == datetime(2026, 8, 20, 7, 0)

    def test_legacy_one_time_without_date_keeps_old_behaviour(self, monkeypatch):
        """Rows created before the date was stored still schedule sensibly."""
        _freeze_now(monkeypatch, WED)
        alarm = _alarm(AlarmType.ONE_TIME, time(7, 0))
        assert _next_trigger(alarm) == datetime(2026, 8, 13, 7, 0)


class TestOneTimeDatePersistence:
    """A one-time alarm must keep its date across edits and re-enables."""

    @pytest.fixture
    def one_time_alarm(self, client, auth_headers):
        """Create a one-time alarm well into the future."""
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Flight",
                "alarm_time": "04:30",
                "alarm_type": "one_time",
                "one_time_date": "2030-03-09",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        return response.json()

    def test_one_time_date_is_returned(self, one_time_alarm):
        assert one_time_alarm["one_time_date"] == "2030-03-09"
        assert one_time_alarm["next_trigger_at"] == "2030-03-09T04:30:00Z"

    def test_unrelated_edit_keeps_the_trigger(
        self, client, auth_headers, one_time_alarm
    ):
        """Renaming an alarm must not touch its schedule."""
        response = client.put(
            f"/api/v1/alarms/{one_time_alarm['id']}",
            json={"label": "Airport run"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["next_trigger_at"] == "2030-03-09T04:30:00Z"

    def test_time_edit_stays_on_the_same_date(
        self, client, auth_headers, one_time_alarm
    ):
        """Changing only the time used to silently reschedule to tomorrow."""
        response = client.put(
            f"/api/v1/alarms/{one_time_alarm['id']}",
            json={"alarm_time": "05:15"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["one_time_date"] == "2030-03-09"
        assert body["next_trigger_at"] == "2030-03-09T05:15:00Z"

    def test_date_can_be_moved(self, client, auth_headers, one_time_alarm):
        response = client.put(
            f"/api/v1/alarms/{one_time_alarm['id']}",
            json={"one_time_date": "2030-03-11"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["one_time_date"] == "2030-03-11"
        assert body["next_trigger_at"] == "2030-03-11T04:30:00Z"

    def test_toggle_off_and_on_keeps_the_date(
        self, client, auth_headers, one_time_alarm
    ):
        """Re-enabling used to reschedule the alarm to today/tomorrow."""
        alarm_id = one_time_alarm["id"]
        off = client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": False},
            headers=auth_headers,
        )
        assert off.status_code == 200

        on = client.patch(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_active": True},
            headers=auth_headers,
        )
        assert on.status_code == 200
        body = on.json()
        assert body["one_time_date"] == "2030-03-09"
        assert body["next_trigger_at"] == "2030-03-09T04:30:00Z"


class TestDaysOfWeekApi:
    """days_of_week must round-trip and actually shape the schedule."""

    def test_custom_days_round_trip_and_constrain_trigger(
        self, client, auth_headers
    ):
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Gym",
                "alarm_time": "06:00",
                "alarm_type": "daily",
                "days_of_week": [1, 3],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["days_of_week"] == [1, 3]

        trigger = datetime.fromisoformat(
            body["next_trigger_at"].replace("Z", "+00:00")
        )
        assert trigger.weekday() in {1, 3}

    def test_updating_days_recomputes_the_trigger(self, client, auth_headers):
        created = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Gym",
                "alarm_time": "06:00",
                "alarm_type": "daily",
                "days_of_week": [1, 3],
            },
            headers=auth_headers,
        )
        alarm_id = created.json()["id"]

        response = client.put(
            f"/api/v1/alarms/{alarm_id}",
            json={"days_of_week": [5, 6]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["days_of_week"] == [5, 6]

        trigger = datetime.fromisoformat(
            body["next_trigger_at"].replace("Z", "+00:00")
        )
        assert trigger.weekday() in {5, 6}

    def test_smart_adaptive_honours_custom_days(self, client, auth_headers):
        """Adaptive time selection still lands on an allowed weekday."""
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Smart weekend",
                "alarm_time": "07:00",
                "alarm_type": "smart_adaptive",
                "days_of_week": [5, 6],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()

        trigger = datetime.fromisoformat(
            body["next_trigger_at"].replace("Z", "+00:00")
        )
        assert trigger.weekday() in {5, 6}

    def test_out_of_range_day_is_rejected(self, client, auth_headers):
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Bad days",
                "alarm_time": "06:00",
                "days_of_week": [0, 9],
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestAlarmCustomizationFields:
    """Every backend-supported customization option must round-trip."""

    def test_full_customization_round_trip(self, client, auth_headers):
        payload = {
            "title": "Fully configured",
            "label": "Fully configured",
            "description": "Deep work start",
            "alarm_time": "05:45",
            "alarm_type": "daily",
            "days_of_week": [0, 1, 2, 3, 4],
            "snooze_limit": 0,
            "snooze_interval_minutes": 9,
            "challenge_type": "logic",
            "challenge_count": 3,
            "challenge_difficulty": "hard",
            "volume": 35,
            "vibrate": False,
        }
        response = client.post(
            "/api/v1/alarms/", json=payload, headers=auth_headers
        )
        assert response.status_code == 201
        body = response.json()

        assert body["description"] == "Deep work start"
        assert body["days_of_week"] == [0, 1, 2, 3, 4]
        assert body["snooze_limit"] == 0
        assert body["snooze_interval_minutes"] == 9
        assert body["challenge_type"] == "logic"
        assert body["challenge_count"] == 3
        assert body["challenge_difficulty"] == "hard"
        assert body["volume"] == 35
        assert body["vibrate"] is False

    def test_customization_can_be_updated(self, client, auth_headers):
        created = client.post(
            "/api/v1/alarms/",
            json={"title": "Plain", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = created.json()["id"]

        response = client.put(
            f"/api/v1/alarms/{alarm_id}",
            json={
                "description": "Updated note",
                "volume": 15,
                "vibrate": False,
                "challenge_count": 4,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["description"] == "Updated note"
        assert body["volume"] == 15
        assert body["vibrate"] is False
        assert body["challenge_count"] == 4
