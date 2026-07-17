"""Tests for alarm management endpoints.

Aligned with the actual wired API (``app/api/v1/endpoints/alarms.py`` +
``app/schemas/alarm.py``):
- Integer alarm/user IDs.
- ``alarm_time`` is serialized as ``HH:MM:SS``.
- Listing returns a paginated ``{alarms, total, page, per_page}`` object.
- Toggle is ``PATCH /{id}/toggle`` with ``{"is_active": ...}``.
- Snooze/dismiss return the full ``AlarmResponse``.
"""


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
        """Per-alarm challenge_difficulty is persisted and returned."""
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

        # Without a profile preference, challenge baseline falls back to alarm
        ch = client.get(
            f"/api/v1/alarms/{data['id']}/challenge", headers=auth_headers
        )
        assert ch.status_code == 200
        body = ch.json()
        assert body["difficulty"] in {
            "beginner", "easy", "medium", "hard", "expert"
        }
        assert body["adaptive_difficulty"]["difficulty"] == "hard"

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
