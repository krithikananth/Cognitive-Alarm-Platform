"""Tests for the native-client backend additions (Phase A §4).

Covers:
- ``GET /api/v1/alarms/schedule`` occurrence expansion
- ``POST /api/v1/alarms/{id}/offline-wake`` queued offline dismissals
- the Android FCM overrides used for alarm ring pushes
"""

from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.api.v1.endpoints import alarms as alarms_module
from app.models.alarm import Alarm, AlarmType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile

# Reference calendar (August 2026):
#   Mon 10 · Tue 11 · Wed 12 · Thu 13 · Fri 14 · Sat 15 · Sun 16 · Mon 17
MON = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
FRI = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


def _freeze_now(monkeypatch, moment):
    """Pin ``datetime.now`` inside the alarms endpoint module to ``moment``."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(alarms_module, "datetime", _Frozen)


def _make_alarm(db, user, **overrides):
    """Persist an alarm with sensible defaults for schedule expansion."""
    fields = {
        "title": "Scheduling",
        "alarm_time": time(7, 0),
        "alarm_type": AlarmType.DAILY,
        "is_active": True,
        "snooze_limit": 3,
        "snooze_interval_minutes": 5,
        "challenge_count": 1,
        "challenge_difficulty": "medium",
        "volume": 80,
        "vibrate": True,
    }
    fields.update(overrides)
    alarm = Alarm(user_id=user.id, **fields)
    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    return alarm


def _set_timezone(db, user, tz_name):
    profile = (
        db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    )
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    profile.timezone = tz_name
    db.commit()


def _triggers(payload, alarm_id=None):
    """Trigger instants from a schedule payload, optionally for one alarm."""
    return [
        datetime.fromisoformat(o["trigger_at"])
        for o in payload["occurrences"]
        if alarm_id is None or o["alarm_id"] == alarm_id
    ]


class TestScheduleEndpoint:
    """GET /api/v1/alarms/schedule."""

    def test_requires_authentication(self, client):
        assert client.get("/api/v1/alarms/schedule").status_code == 401

    def test_empty_schedule_is_well_formed(self, client, auth_headers):
        response = client.get("/api/v1/alarms/schedule", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["horizon_days"] == 7
        assert body["occurrences"] == []
        assert body["generated_at"].endswith("+00:00")

    def test_daily_alarm_expands_once_per_day(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(db_session, test_user)
        _freeze_now(monkeypatch, MON)

        response = client.get(
            "/api/v1/alarms/schedule?days=7", headers=auth_headers
        )
        assert response.status_code == 200
        triggers = _triggers(response.json(), alarm.id)

        # 09:00 Mon 10 → first ring is Tue 11 at 07:00, then every day.
        assert triggers == [
            datetime(2026, 8, day, 7, 0, tzinfo=timezone.utc)
            for day in range(11, 18)
        ]

    def test_weekday_alarm_skips_the_weekend(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session, test_user, alarm_type=AlarmType.WEEKDAY
        )
        _freeze_now(monkeypatch, FRI)

        response = client.get(
            "/api/v1/alarms/schedule?days=7", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert [t.date() for t in triggers] == [
            date(2026, 8, 17),
            date(2026, 8, 18),
            date(2026, 8, 19),
            date(2026, 8, 20),
            date(2026, 8, 21),
        ]

    def test_weekend_alarm_only_expands_saturday_and_sunday(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session, test_user, alarm_type=AlarmType.WEEKEND
        )
        _freeze_now(monkeypatch, MON)

        response = client.get(
            "/api/v1/alarms/schedule?days=7", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert [t.date() for t in triggers] == [
            date(2026, 8, 15),
            date(2026, 8, 16),
        ]

    def test_smart_adaptive_alarm_expands_like_a_daily_alarm(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session, test_user, alarm_type=AlarmType.SMART_ADAPTIVE
        )
        _freeze_now(monkeypatch, MON)

        response = client.get(
            "/api/v1/alarms/schedule?days=3", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert len(triggers) == 3
        # No wake history, so adaptation leaves the configured time alone and
        # the expansion repeats it on consecutive days.
        assert [t.date() for t in triggers] == [
            date(2026, 8, 11),
            date(2026, 8, 12),
            date(2026, 8, 13),
        ]

    def test_one_time_alarm_does_not_repeat(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session,
            test_user,
            alarm_type=AlarmType.ONE_TIME,
            one_time_date=date(2026, 8, 12),
        )
        _freeze_now(monkeypatch, MON)

        response = client.get(
            "/api/v1/alarms/schedule?days=7", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert triggers == [datetime(2026, 8, 12, 7, 0, tzinfo=timezone.utc)]

    def test_past_one_time_alarm_yields_no_occurrences(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session,
            test_user,
            alarm_type=AlarmType.ONE_TIME,
            one_time_date=date(2026, 8, 1),
        )
        _freeze_now(monkeypatch, MON)

        response = client.get("/api/v1/alarms/schedule", headers=auth_headers)
        assert _triggers(response.json(), alarm.id) == []

    def test_days_of_week_narrows_the_pattern(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session,
            test_user,
            alarm_type=AlarmType.DAILY,
            days_of_week=[0, 2],  # Monday + Wednesday
        )
        _freeze_now(monkeypatch, MON)

        response = client.get(
            "/api/v1/alarms/schedule?days=14", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert [t.weekday() for t in triggers] == [2, 0, 2, 0]
        assert [t.date() for t in triggers] == [
            date(2026, 8, 12),
            date(2026, 8, 17),
            date(2026, 8, 19),
            date(2026, 8, 24),
        ]

    def test_inactive_alarms_are_excluded(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        active = _make_alarm(db_session, test_user, title="Active")
        inactive = _make_alarm(
            db_session, test_user, title="Inactive", is_active=False
        )
        _freeze_now(monkeypatch, MON)

        body = client.get(
            "/api/v1/alarms/schedule", headers=auth_headers
        ).json()
        alarm_ids = {o["alarm_id"] for o in body["occurrences"]}

        assert active.id in alarm_ids
        assert inactive.id not in alarm_ids

    def test_another_users_alarms_are_never_expanded(
        self, client, db_session, test_user, admin_user, auth_headers,
        monkeypatch,
    ):
        mine = _make_alarm(db_session, test_user)
        theirs = _make_alarm(db_session, admin_user, title="Not mine")
        _freeze_now(monkeypatch, MON)

        body = client.get(
            "/api/v1/alarms/schedule", headers=auth_headers
        ).json()
        alarm_ids = {o["alarm_id"] for o in body["occurrences"]}

        assert alarm_ids == {mine.id}
        assert theirs.id not in alarm_ids

    def test_occurrences_are_sorted_across_alarms(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        _make_alarm(db_session, test_user, title="Late", alarm_time=time(9, 30))
        _make_alarm(db_session, test_user, title="Early", alarm_time=time(6, 0))
        _freeze_now(monkeypatch, MON)

        triggers = _triggers(
            client.get(
                "/api/v1/alarms/schedule?days=3", headers=auth_headers
            ).json()
        )
        assert triggers == sorted(triggers)

    def test_occurrence_carries_the_full_ring_configuration(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        alarm = _make_alarm(
            db_session,
            test_user,
            title="Morning Alarm",
            challenge_count=2,
            challenge_difficulty="hard",
            snooze_limit=1,
            snooze_interval_minutes=9,
            volume=55,
            vibrate=False,
        )
        _freeze_now(monkeypatch, MON)

        occurrence = client.get(
            "/api/v1/alarms/schedule?days=1", headers=auth_headers
        ).json()["occurrences"][0]

        assert occurrence == {
            "alarm_id": alarm.id,
            "trigger_at": "2026-08-11T07:00:00+00:00",
            "title": "Morning Alarm",
            "challenge_type": "random",
            "challenge_count": 2,
            "challenge_difficulty": "hard",
            "snooze_limit": 1,
            "snooze_interval_minutes": 9,
            "volume": 55,
            "vibrate": False,
        }

    def test_horizon_is_bounded(self, client, auth_headers):
        assert (
            client.get(
                "/api/v1/alarms/schedule?days=0", headers=auth_headers
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/alarms/schedule?days=31", headers=auth_headers
            ).status_code
            == 422
        )

    def test_expansion_keeps_local_wall_clock_across_a_dst_change(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        """A 07:00 alarm stays 07:00 locally, so its UTC offset must shift."""
        _set_timezone(db_session, test_user, "America/New_York")
        alarm = _make_alarm(db_session, test_user)
        # US DST ends Sunday 1 November 2026 (UTC-4 → UTC-5).
        _freeze_now(
            monkeypatch, datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc)
        )

        response = client.get(
            "/api/v1/alarms/schedule?days=5", headers=auth_headers
        )
        triggers = _triggers(response.json(), alarm.id)

        assert datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc) in triggers
        assert datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc) in triggers
        # Every ring is 07:00 in the user's own timezone.
        assert {
            t.astimezone(alarms_module._resolve_timezone("America/New_York"))
            .time()
            for t in triggers
        } == {time(7, 0)}

    def test_first_occurrence_matches_the_stored_next_trigger(
        self, client, db_session, test_user, auth_headers, monkeypatch
    ):
        """The expansion must not disagree with the alarm's own schedule."""
        _freeze_now(monkeypatch, MON)
        created = client.post(
            "/api/v1/alarms/",
            json={"alarm_time": "07:00", "alarm_type": "daily"},
            headers=auth_headers,
        ).json()

        triggers = _triggers(
            client.get(
                "/api/v1/alarms/schedule", headers=auth_headers
            ).json(),
            created["id"],
        )
        stored = datetime.fromisoformat(
            created["next_trigger_at"].replace("Z", "+00:00")
        )
        assert triggers[0] == stored


class TestOfflineWake:
    """POST /api/v1/alarms/{alarm_id}/offline-wake."""

    def _payload(self, triggered_at, **overrides):
        body = {
            "triggered_at": triggered_at.isoformat(),
            "dismissed_at": (
                triggered_at + timedelta(seconds=45)
            ).isoformat(),
            "challenges_required": 1,
            "challenges_completed": 1,
        }
        body.update(overrides)
        return body

    def test_requires_authentication(self, client, db_session, test_user):
        alarm = _make_alarm(db_session, test_user)
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(datetime.now(timezone.utc) - timedelta(hours=1)),
        )
        assert response.status_code == 401

    def test_unknown_alarm_is_not_found(self, client, auth_headers):
        response = client.post(
            "/api/v1/alarms/999999/offline-wake",
            json=self._payload(datetime.now(timezone.utc) - timedelta(hours=1)),
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_another_users_alarm_is_not_found(
        self, client, db_session, admin_user, auth_headers
    ):
        alarm = _make_alarm(db_session, admin_user)
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(datetime.now(timezone.utc) - timedelta(hours=1)),
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_records_an_unverified_wake_event(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)

        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(rang_at),
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "recorded"
        assert body["verified"] is False
        assert body["dismiss_method"] == "offline_challenge"

        event = (
            db_session.query(AlarmWakeEvent)
            .filter(AlarmWakeEvent.id == body["wake_event_id"])
            .one()
        )
        assert event.verified is False
        assert event.dismiss_method == "offline_challenge"
        assert event.time_to_dismiss_seconds == 45
        # An unverifiable dismissal must not carry a graded wakefulness score.
        assert event.wakefulness_score is None
        assert event.wakefulness_level is None

    def test_it_never_counts_as_a_verified_wake(
        self, client, db_session, test_user, auth_headers
    ):
        """The whole point of the trust boundary: no habit-score credit."""
        alarm = _make_alarm(db_session, test_user)
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)

        client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(rang_at),
            headers=auth_headers,
        )

        confirmations = client.get(
            "/api/v1/alarms/wake-confirmations", headers=auth_headers
        ).json()
        assert confirmations["total"] == 1
        assert confirmations["events"][0]["verified"] is False

        db_session.expire_all()
        alarm = db_session.query(Alarm).filter(Alarm.id == alarm.id).one()
        assert alarm.total_dismissals == 0

    def test_replaying_the_same_queued_item_is_idempotent(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)
        payload = self._payload(rang_at)

        first = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=payload,
            headers=auth_headers,
        ).json()
        second = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=payload,
            headers=auth_headers,
        ).json()

        assert first["status"] == "recorded"
        assert second["status"] == "duplicate"
        assert second["wake_event_id"] == first["wake_event_id"]
        assert (
            db_session.query(AlarmWakeEvent)
            .filter(AlarmWakeEvent.user_id == test_user.id)
            .count()
            == 1
        )

    def test_future_timestamps_are_rejected(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(datetime.now(timezone.utc) + timedelta(hours=1)),
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "future" in response.json()["detail"].lower()

    def test_dismissal_before_the_ring_is_rejected(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(
                rang_at,
                dismissed_at=(rang_at - timedelta(minutes=1)).isoformat(),
            ),
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_stale_queue_entries_are_rejected(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(datetime.now(timezone.utc) - timedelta(days=45)),
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "older" in response.json()["detail"].lower()

    def test_a_naive_timestamp_is_read_as_utc(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        rang_at = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(
            tzinfo=None, microsecond=0
        )
        response = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(rang_at),
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["triggered_at"] == (
            rang_at.replace(tzinfo=timezone.utc).isoformat()
        )

    def test_a_recurring_alarm_is_rescheduled(
        self, client, db_session, test_user, auth_headers
    ):
        alarm = _make_alarm(db_session, test_user)
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)
        alarm.next_trigger_at = rang_at.replace(tzinfo=None)
        db_session.commit()

        body = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(rang_at),
            headers=auth_headers,
        ).json()

        assert body["next_trigger_at"] is not None
        assert datetime.fromisoformat(
            body["next_trigger_at"]
        ) > datetime.now(timezone.utc)

    def test_a_one_time_alarm_is_retired(
        self, client, db_session, test_user, auth_headers
    ):
        rang_at = datetime.now(timezone.utc) - timedelta(hours=2)
        alarm = _make_alarm(
            db_session,
            test_user,
            alarm_type=AlarmType.ONE_TIME,
            one_time_date=rang_at.date(),
        )
        alarm.next_trigger_at = rang_at.replace(tzinfo=None)
        db_session.commit()

        body = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(rang_at),
            headers=auth_headers,
        ).json()

        assert body["next_trigger_at"] is None
        db_session.expire_all()
        assert (
            db_session.query(Alarm).filter(Alarm.id == alarm.id).one().is_active
            is False
        )

    def test_a_newer_cycle_keeps_its_schedule(
        self, client, db_session, test_user, auth_headers
    ):
        """A late flush must not drag an already-advanced alarm backwards."""
        alarm = _make_alarm(db_session, test_user)
        future = (
            datetime.now(timezone.utc) + timedelta(hours=6)
        ).replace(tzinfo=None, microsecond=0)
        alarm.next_trigger_at = future
        db_session.commit()

        body = client.post(
            f"/api/v1/alarms/{alarm.id}/offline-wake",
            json=self._payload(datetime.now(timezone.utc) - timedelta(days=1)),
            headers=auth_headers,
        ).json()

        assert datetime.fromisoformat(body["next_trigger_at"]) == (
            future.replace(tzinfo=timezone.utc)
        )


class TestAndroidPushConfig:
    """``_android_config`` — Phase A §4.2."""

    @pytest.fixture
    def messaging(self):
        pytest.importorskip("firebase_admin")
        from firebase_admin import messaging as m

        return m

    def _ring_payload(self):
        return {
            "alarm_id": "42",
            "action": "ring_alarm",
            "requires_interaction": "True",
            "notification_id": "7",
        }

    def test_ordinary_notifications_get_no_android_overrides(self, messaging):
        from app.services.fcm_service import _android_config

        assert _android_config("Hi", "There", {"action": "open"}) is None

    def test_ring_pushes_are_high_priority_on_the_alarm_channel(
        self, messaging
    ):
        from app.services.fcm_service import (
            ANDROID_ALARM_CHANNEL_ID,
            _android_config,
        )

        config = _android_config("Alarm", "Solve it", self._ring_payload())

        assert config is not None
        assert config.priority == "high"
        # A ring that could not be delivered now is worthless later.
        assert config.ttl == 0
        assert config.notification.channel_id == ANDROID_ALARM_CHANNEL_ID
        assert config.notification.priority == "max"
        assert config.notification.visibility == "public"
        assert config.notification.sticky is True

    def test_the_flag_is_read_case_insensitively(self, messaging):
        from app.services.fcm_service import _android_config

        for flag in ("true", "True", "1"):
            payload = dict(self._ring_payload(), requires_interaction=flag)
            assert _android_config("A", "B", payload) is not None
        for flag in ("false", "False", "0", ""):
            payload = dict(self._ring_payload(), requires_interaction=flag)
            assert _android_config("A", "B", payload) is None

    def test_the_dispatch_payload_actually_triggers_it(self, messaging):
        """The ring notification the dispatcher builds must opt in."""
        from app.services.alarm_dispatch_service import AlarmDispatchService
        from app.services.fcm_service import _android_config

        alarm = Alarm(
            id=1,
            user_id=1,
            title="Morning",
            alarm_time=time(7, 0),
            alarm_type=AlarmType.DAILY,
            next_trigger_at=datetime(2026, 8, 15, 7, 0),
        )
        data = AlarmDispatchService._build_notification(alarm).data
        payload = {k: str(v) for k, v in data.items()}

        assert _android_config("Alarm", "Body", payload) is not None
