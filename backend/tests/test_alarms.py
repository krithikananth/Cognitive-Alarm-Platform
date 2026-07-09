"""Tests for alarm management endpoints.

Covers creating alarms (valid and invalid), listing, retrieving by ID,
updating, deleting, toggling, snoozing (including limit enforcement),
dismissing, upcoming alarms, and unauthorized access.
"""


class TestCreateAlarm:
    """Tests for POST /api/v1/alarms/."""

    def test_create_alarm(self, client, test_user, auth_headers):
        """Test that an authenticated user can create an alarm with valid data."""
        payload = {
            "title": "Morning Workout",
            "description": "Time to exercise!",
            "alarm_time": "06:30",
            "alarm_date": "2026-07-15",
            "repeat_pattern": "once",
            "snooze_duration": 5,
            "max_snooze": 3,
            "cognitive_challenge": True,
            "challenge_difficulty": "hard",
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Morning Workout"
        assert data["description"] == "Time to exercise!"
        assert data["alarm_time"] == "06:30"
        assert data["alarm_date"] == "2026-07-15"
        assert data["is_enabled"] is True
        assert data["status"] == "active"
        assert data["owner_id"] == str(test_user.id)
        assert data["cognitive_challenge"] is True
        assert data["challenge_difficulty"] == "hard"
        assert "id" in data

    def test_create_alarm_minimal(self, client, test_user, auth_headers):
        """Test creating an alarm with only the required fields."""
        payload = {
            "title": "Quick Alarm",
            "alarm_time": "08:00",
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Quick Alarm"
        assert data["alarm_time"] == "08:00"
        assert data["repeat_pattern"] == "once"
        assert data["sound"] == "default"
        assert data["vibration"] is True
        assert data["cognitive_challenge"] is False

    def test_create_alarm_invalid_time(self, client, test_user, auth_headers):
        """Test that creating an alarm with an invalid time format returns 422."""
        payload = {
            "title": "Bad Alarm",
            "alarm_time": "25:99",  # Invalid time
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 422

    def test_create_alarm_invalid_time_format(self, client, test_user, auth_headers):
        """Test that a non-HH:MM time format is rejected."""
        payload = {
            "title": "Bad Format",
            "alarm_time": "6:30am",  # Wrong format
        }
        response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)

        assert response.status_code == 422


class TestListAlarms:
    """Tests for GET /api/v1/alarms/."""

    def test_list_alarms(self, client, test_user, auth_headers):
        """Test that a user can list their own alarms."""
        # Create two alarms first
        for title in ["Alarm A", "Alarm B"]:
            client.post(
                "/api/v1/alarms/",
                json={"title": title, "alarm_time": "07:00"},
                headers=auth_headers,
            )

        response = client.get("/api/v1/alarms/", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        titles = [a["title"] for a in data]
        assert "Alarm A" in titles
        assert "Alarm B" in titles

    def test_list_alarms_empty(self, client, test_user, auth_headers):
        """Test listing alarms when the user has none returns an empty list."""
        response = client.get("/api/v1/alarms/", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data == []


class TestGetAlarm:
    """Tests for GET /api/v1/alarms/{alarm_id}."""

    def test_get_alarm(self, client, test_user, auth_headers):
        """Test that a user can retrieve a specific alarm by its ID."""
        # Create an alarm
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
        """Test that requesting a non-existent alarm ID returns 404."""
        response = client.get(
            "/api/v1/alarms/nonexistent-alarm-id", headers=auth_headers
        )

        assert response.status_code == 404
        assert "Alarm not found" in response.json()["detail"]


class TestUpdateAlarm:
    """Tests for PUT /api/v1/alarms/{alarm_id}."""

    def test_update_alarm(self, client, test_user, auth_headers):
        """Test that a user can update an alarm's title and time."""
        # Create an alarm
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Original Title", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        # Update it
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
        assert data["alarm_time"] == "08:30"
        assert data["description"] == "Updated description"

    def test_update_alarm_partial(self, client, test_user, auth_headers):
        """Test that only specified fields are updated; others remain unchanged."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Keep This", "alarm_time": "07:00", "sound": "birds"},
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
        assert data["alarm_time"] == "07:00"  # Unchanged
        assert data["sound"] == "birds"  # Unchanged
        assert data["description"] == "Added description"  # Updated

    def test_update_alarm_not_found(self, client, test_user, auth_headers):
        """Test that updating a non-existent alarm returns 404."""
        response = client.put(
            "/api/v1/alarms/nonexistent-id",
            json={"title": "Nope"},
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestDeleteAlarm:
    """Tests for DELETE /api/v1/alarms/{alarm_id}."""

    def test_delete_alarm(self, client, test_user, auth_headers):
        """Test that a user can delete their own alarm."""
        # Create an alarm
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Delete Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        # Delete it
        response = client.delete(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify it's gone
        get_response = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers)
        assert get_response.status_code == 404

    def test_delete_alarm_not_found(self, client, test_user, auth_headers):
        """Test that deleting a non-existent alarm returns 404."""
        response = client.delete(
            "/api/v1/alarms/nonexistent-id", headers=auth_headers
        )

        assert response.status_code == 404


class TestToggleAlarm:
    """Tests for POST /api/v1/alarms/{alarm_id}/toggle."""

    def test_toggle_alarm_disable(self, client, test_user, auth_headers):
        """Test disabling an alarm via toggle sets is_enabled=False and status=inactive."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Toggle Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_enabled": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_enabled"] is False
        assert data["status"] == "inactive"

    def test_toggle_alarm_enable(self, client, test_user, auth_headers):
        """Test re-enabling a disabled alarm resets status to active and clears snooze count."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Re-enable Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        # Disable first
        client.post(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_enabled": False},
            headers=auth_headers,
        )

        # Re-enable
        response = client.post(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_enabled": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_enabled"] is True
        assert data["status"] == "active"
        assert data["snooze_count"] == 0


class TestUpcomingAlarms:
    """Tests for GET /api/v1/alarms/upcoming."""

    def test_get_upcoming_alarms(self, client, test_user, auth_headers):
        """Test retrieving upcoming enabled alarms sorted by time."""
        # Create alarms at different times
        for time in ["09:00", "06:00", "12:00"]:
            client.post(
                "/api/v1/alarms/",
                json={"title": f"Alarm at {time}", "alarm_time": time},
                headers=auth_headers,
            )

        response = client.get("/api/v1/alarms/upcoming", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should be sorted by time
        times = [a["alarm_time"] for a in data]
        assert times == sorted(times)

    def test_get_upcoming_alarms_excludes_disabled(self, client, test_user, auth_headers):
        """Test that disabled alarms are not included in upcoming results."""
        # Create and disable an alarm
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Disabled", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]
        client.post(
            f"/api/v1/alarms/{alarm_id}/toggle",
            json={"is_enabled": False},
            headers=auth_headers,
        )

        # Create an enabled alarm
        client.post(
            "/api/v1/alarms/",
            json={"title": "Enabled", "alarm_time": "08:00"},
            headers=auth_headers,
        )

        response = client.get("/api/v1/alarms/upcoming", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        titles = [a["title"] for a in data]
        assert "Disabled" not in titles
        assert "Enabled" in titles


class TestSnoozeAlarm:
    """Tests for POST /api/v1/alarms/{alarm_id}/snooze."""

    def test_snooze_alarm(self, client, test_user, auth_headers):
        """Test that snoozing an alarm increments the snooze count and sets status to snoozed."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Snooze Me", "alarm_time": "07:00", "max_snooze": 3},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", json={}, headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snooze_count"] == 1
        assert data["status"] == "snoozed"

    def test_snooze_alarm_custom_duration(self, client, test_user, auth_headers):
        """Test that a custom snooze duration overrides the default."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Custom Snooze", "alarm_time": "07:00", "snooze_duration": 5},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze",
            json={"snooze_duration": 10},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["snooze_duration"] == 10

    def test_snooze_alarm_max_reached(self, client, test_user, auth_headers):
        """Test that snoozing beyond the max limit returns 400."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Limited Snooze", "alarm_time": "07:00", "max_snooze": 1},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        # First snooze (allowed)
        response1 = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", json={}, headers=auth_headers
        )
        assert response1.status_code == 200

        # Second snooze (should be rejected)
        response2 = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", json={}, headers=auth_headers
        )
        assert response2.status_code == 400
        assert "Maximum snooze limit reached" in response2.json()["detail"]


class TestDismissAlarm:
    """Tests for POST /api/v1/alarms/{alarm_id}/dismiss."""

    def test_dismiss_alarm(self, client, test_user, auth_headers):
        """Test that dismissing an alarm sets its status to dismissed."""
        create_response = client.post(
            "/api/v1/alarms/",
            json={"title": "Dismiss Me", "alarm_time": "07:00"},
            headers=auth_headers,
        )
        alarm_id = create_response.json()["id"]

        response = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss", headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dismissed"

    def test_dismiss_alarm_not_found(self, client, test_user, auth_headers):
        """Test that dismissing a non-existent alarm returns 404."""
        response = client.post(
            "/api/v1/alarms/nonexistent-id/dismiss", headers=auth_headers
        )

        assert response.status_code == 404


class TestAlarmUnauthorized:
    """Tests for unauthorized access to alarm endpoints."""

    def test_alarm_unauthorized(self, client):
        """Test that all alarm endpoints require authentication."""
        # Create
        response = client.post(
            "/api/v1/alarms/",
            json={"title": "No Auth", "alarm_time": "07:00"},
        )
        assert response.status_code == 401

        # List
        response = client.get("/api/v1/alarms/")
        assert response.status_code == 401

        # Get by ID
        response = client.get("/api/v1/alarms/some-id")
        assert response.status_code == 401

        # Update
        response = client.put(
            "/api/v1/alarms/some-id", json={"title": "Updated"}
        )
        assert response.status_code == 401

        # Delete
        response = client.delete("/api/v1/alarms/some-id")
        assert response.status_code == 401

        # Toggle
        response = client.post(
            "/api/v1/alarms/some-id/toggle", json={"is_enabled": False}
        )
        assert response.status_code == 401

        # Snooze
        response = client.post("/api/v1/alarms/some-id/snooze", json={})
        assert response.status_code == 401

        # Dismiss
        response = client.post("/api/v1/alarms/some-id/dismiss")
        assert response.status_code == 401

        # Upcoming
        response = client.get("/api/v1/alarms/upcoming")
        assert response.status_code == 401
