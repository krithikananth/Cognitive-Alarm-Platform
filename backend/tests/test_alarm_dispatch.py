"""
End-to-end tests for server-side alarm dispatch.

The frontend can only ring an alarm while a tab is open. These tests cover the
backend safety net that makes a ring survive a closed browser:

- a due alarm queues exactly one ``ALARM_TRIGGER`` push per trigger instant
- the push is delivered through the normal notification pipeline
- user preferences, quiet hours and the master toggle never silence a ring
- the alarm still rings for one-time, recurring and smart-adaptive alarms
- the existing wake cycle (challenge → verify → dismiss) is unchanged
- unattended alarms roll forward instead of parking in the past forever

All three alarm types are exercised through the public API, so scheduling
semantics come from the same ``_calculate_next_trigger`` the app uses.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.alarm import Alarm, AlarmType
from app.models.challenge_session import ChallengeSession
from app.models.notification import (
    Notification,
    NotificationPreference,
    NotificationStatus,
    NotificationType,
)
from app.models.profile import UserProfile
from app.services.alarm_dispatch_service import AlarmDispatchService
from app.services.fcm_service import FCMService
from app.services.notification_service import NotificationService


# ── Helpers ──────────────────────────────────────────────────────

def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fake_send(success: bool = True):
    """Stand-in for ``FCMService.send_detailed`` that never touches network."""
    calls = []

    def _send(fcm_tokens, title, body, data=None, *, image_url=None):
        tokens = list(fcm_tokens)
        calls.append({"title": title, "body": body, "data": dict(data or {})})
        return {
            "success_count": len(tokens) if success else 0,
            "failure_count": 0 if success else len(tokens),
            "failed_tokens": [] if success else tokens,
            "invalid_tokens": [],
            "retryable": not success,
            "errors": [] if success else ["transient: simulated"],
        }

    _send.calls = calls
    return _send


def _create_alarm(client, headers, **payload):
    body = {"title": "Alarm", "alarm_time": "07:00", **payload}
    response = client.post("/api/v1/alarms/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _make_due(db_session, alarm_id: int, seconds_ago: int = 30) -> datetime:
    """Move an alarm's trigger into the recent past so a sweep picks it up."""
    alarm = db_session.query(Alarm).filter(Alarm.id == alarm_id).one()
    alarm.next_trigger_at = _naive_utc_now() - timedelta(seconds=seconds_ago)
    db_session.commit()
    return alarm.next_trigger_at


def _rings(db_session, alarm_id: int):
    return (
        db_session.query(Notification)
        .filter(
            Notification.notification_type == NotificationType.ALARM_TRIGGER,
            Notification.related_alarm_id == alarm_id,
        )
        .order_by(Notification.id)
        .all()
    )


def _register_device(client, headers, token="dispatch-test-token"):
    response = client.post(
        "/api/v1/notifications/device-token",
        json={"fcm_token": token, "device_type": "web"},
        headers=headers,
    )
    assert response.status_code in (200, 201), response.text


def _deliver_rings(db_session):
    return NotificationService.process_pending_notifications(
        db_session, only_types=[NotificationType.ALARM_TRIGGER]
    )


@pytest.fixture
def user_profile(db_session, test_user):
    """Give the test user a UTC profile so trigger maths is predictable."""
    profile = (
        db_session.query(UserProfile)
        .filter(UserProfile.user_id == test_user.id)
        .first()
    )
    if profile is None:
        profile = UserProfile(user_id=test_user.id)
        db_session.add(profile)
    profile.timezone = "UTC"
    profile.preferred_wake_time = time(7, 0)
    profile.sleep_duration_hours = 8.0
    db_session.commit()
    return profile


# ── Dispatch mechanics ───────────────────────────────────────────

class TestAlarmDispatch:
    """Ring queueing, de-duplication and lateness limits."""

    def test_due_alarm_queues_exactly_one_ring(
        self, client, db_session, test_user, auth_headers, user_profile
    ):
        alarm = _create_alarm(client, auth_headers, title="Wake Up")
        trigger = _make_due(db_session, alarm["id"])

        result = AlarmDispatchService.run_once(db_session)

        assert result["dispatched"] == 1
        rings = _rings(db_session, alarm["id"])
        assert len(rings) == 1
        assert rings[0].status == NotificationStatus.PENDING
        assert rings[0].scheduled_at == trigger
        assert rings[0].data["alarm_id"] == alarm["id"]
        assert rings[0].data["action"] == "ring_alarm"
        assert rings[0].data["requires_interaction"] is True

    def test_repeat_sweeps_never_double_ring(
        self, client, db_session, test_user, auth_headers, user_profile
    ):
        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"])

        AlarmDispatchService.run_once(db_session)
        second = AlarmDispatchService.run_once(db_session)

        assert second["dispatched"] == 0
        assert len(_rings(db_session, alarm["id"])) == 1

    def test_future_alarm_is_not_dispatched(
        self, client, db_session, test_user, auth_headers, user_profile
    ):
        alarm = _create_alarm(client, auth_headers, alarm_time="23:59")

        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 0
        assert _rings(db_session, alarm["id"]) == []

    def test_inactive_alarm_is_not_dispatched(
        self, client, db_session, test_user, auth_headers, user_profile
    ):
        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"])
        client.patch(
            f"/api/v1/alarms/{alarm['id']}/toggle",
            json={"is_active": False},
            headers=auth_headers,
        )

        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 0
        assert _rings(db_session, alarm["id"]) == []

    def test_alarm_later_than_catch_up_window_is_skipped(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        """A server that was down overnight must not ring at lunchtime."""
        monkeypatch.setattr(settings, "ALARM_DISPATCH_MAX_LATENESS_MINUTES", 15)
        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"], seconds_ago=3600)

        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 0
        assert _rings(db_session, alarm["id"]) == []

    def test_snooze_re_ring_is_dispatched(
        self, client, db_session, test_user, auth_headers, user_profile
    ):
        """Snooze moves the trigger, so the next instant rings again."""
        alarm = _create_alarm(client, auth_headers, snooze_interval_minutes=5)
        _make_due(db_session, alarm["id"])
        AlarmDispatchService.run_once(db_session)

        response = client.post(
            f"/api/v1/alarms/{alarm['id']}/snooze", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        _make_due(db_session, alarm["id"])

        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 1
        assert len(_rings(db_session, alarm["id"])) == 2


# ── Delivery ─────────────────────────────────────────────────────

class TestAlarmRingDelivery:
    """A queued ring reaches the device and outranks notification settings."""

    def test_ring_is_pushed_to_registered_device(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        sender = _fake_send()
        monkeypatch.setattr(FCMService, "send_detailed", staticmethod(sender))
        _register_device(client, auth_headers)

        alarm = _create_alarm(client, auth_headers, title="Rise")
        _make_due(db_session, alarm["id"])
        AlarmDispatchService.run_once(db_session)

        result = _deliver_rings(db_session)

        assert result["delivered"] == 1
        ring = _rings(db_session, alarm["id"])[0]
        assert ring.status == NotificationStatus.DELIVERED
        assert sender.calls[0]["data"]["alarm_id"] == alarm["id"]
        assert (
            sender.calls[0]["data"]["notification_type"] == "alarm_trigger"
        )

    def test_master_toggle_and_quiet_hours_never_silence_a_ring(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        """Ringing is the alarm itself, not a discretionary reminder."""
        sender = _fake_send()
        monkeypatch.setattr(FCMService, "send_detailed", staticmethod(sender))
        _register_device(client, auth_headers)

        prefs = NotificationService._get_or_create_preferences(
            db_session, test_user.id
        )
        prefs.notifications_enabled = False
        prefs.push_enabled = False
        prefs.wake_reminder_enabled = False
        prefs.quiet_hours_start = time(0, 0)
        prefs.quiet_hours_end = time(23, 59)
        db_session.commit()

        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"])
        AlarmDispatchService.run_once(db_session)

        result = _deliver_rings(db_session)

        assert result["quiet_hours_skipped"] == 0
        assert result["delivered"] == 1
        assert (
            _rings(db_session, alarm["id"])[0].status
            == NotificationStatus.DELIVERED
        )

    def test_superseded_ring_is_cancelled_not_sent(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        """A ring for an instant the alarm already moved past is a phantom."""
        sender = _fake_send()
        monkeypatch.setattr(FCMService, "send_detailed", staticmethod(sender))
        _register_device(client, auth_headers)

        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"])
        AlarmDispatchService.run_once(db_session)

        # User acted on another device: the alarm advanced to tomorrow.
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        row.next_trigger_at = _naive_utc_now() + timedelta(days=1)
        db_session.commit()

        _deliver_rings(db_session)

        ring = _rings(db_session, alarm["id"])[0]
        assert ring.status == NotificationStatus.FAILED
        assert ring.last_error == "alarm_trigger_superseded"
        assert sender.calls == []

    def test_general_queue_leaves_rings_to_the_alarm_job(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        """Disjoint slices keep the two scheduler jobs from double-sending."""
        sender = _fake_send()
        monkeypatch.setattr(FCMService, "send_detailed", staticmethod(sender))
        _register_device(client, auth_headers)

        alarm = _create_alarm(client, auth_headers)
        _make_due(db_session, alarm["id"])
        AlarmDispatchService.run_once(db_session)

        NotificationService.process_pending_notifications(
            db_session, exclude_types=[NotificationType.ALARM_TRIGGER]
        )

        assert (
            _rings(db_session, alarm["id"])[0].status
            == NotificationStatus.PENDING
        )
        assert sender.calls == []


# ── End-to-end per alarm type ────────────────────────────────────

class TestOneTimeAlarmEndToEnd:
    """One-time alarm: dispatch → wake cycle → retirement."""

    def test_ring_then_solve_then_retire(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send())
        )
        _register_device(client, auth_headers)

        alarm = _create_alarm(
            client,
            auth_headers,
            title="One Shot",
            alarm_type="one_time",
            challenge_type="math",
            challenge_count=1,
        )
        assert alarm["alarm_type"] == "one_time"

        _make_due(db_session, alarm["id"])
        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 1
        assert _deliver_rings(db_session)["delivered"] == 1

        # The push only opens the app — the existing wake cycle is unchanged.
        challenge = client.get(
            f"/api/v1/alarms/{alarm['id']}/challenge", headers=auth_headers
        )
        assert challenge.status_code == 200, challenge.text
        assert "answer" not in challenge.json()

        answer = (
            db_session.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == test_user.id,
                ChallengeSession.alarm_id == alarm["id"],
            )
            .order_by(ChallengeSession.id.desc())
            .first()
        ).answer

        verify = client.post(
            f"/api/v1/alarms/{alarm['id']}/verify",
            json={"user_answer": answer, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()["is_dismissed"] is True

        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.is_active is False
        assert row.next_trigger_at is None

    def test_unattended_one_time_alarm_is_retired(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "ALARM_MISSED_ROLLOVER_MINUTES", 30)
        alarm = _create_alarm(
            client, auth_headers, alarm_type="one_time", title="Missed Once"
        )
        _make_due(db_session, alarm["id"], seconds_ago=7200)

        result = AlarmDispatchService.run_once(db_session)

        assert result["retired"] == 1
        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.is_active is False
        assert row.next_trigger_at is None


class TestRecurringAlarmEndToEnd:
    """Daily alarm: rings today, and keeps ringing on later days."""

    def test_ring_then_solve_then_reschedules(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send())
        )
        _register_device(client, auth_headers)

        alarm = _create_alarm(
            client,
            auth_headers,
            title="Every Day",
            alarm_type="daily",
            challenge_type="math",
            challenge_count=1,
        )

        _make_due(db_session, alarm["id"])
        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 1
        assert _deliver_rings(db_session)["delivered"] == 1

        client.get(
            f"/api/v1/alarms/{alarm['id']}/challenge", headers=auth_headers
        )
        answer = (
            db_session.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == test_user.id,
                ChallengeSession.alarm_id == alarm["id"],
            )
            .order_by(ChallengeSession.id.desc())
            .first()
        ).answer
        verify = client.post(
            f"/api/v1/alarms/{alarm['id']}/verify",
            json={"user_answer": answer, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert verify.status_code == 200, verify.text

        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.is_active is True
        assert row.next_trigger_at > _naive_utc_now()

        # Tomorrow's instant is a new one, so it rings again.
        _make_due(db_session, alarm["id"])
        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 1
        assert len(_rings(db_session, alarm["id"])) == 2

    def test_unattended_recurring_alarm_rolls_forward(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        """A single missed morning must not disarm a daily alarm forever."""
        monkeypatch.setattr(settings, "ALARM_MISSED_ROLLOVER_MINUTES", 30)
        alarm = _create_alarm(client, auth_headers, alarm_type="daily")
        _make_due(db_session, alarm["id"], seconds_ago=7200)

        result = AlarmDispatchService.run_once(db_session)

        assert result["rolled_over"] == 1
        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.is_active is True
        assert row.next_trigger_at > _naive_utc_now()


class TestSmartAdaptiveAlarmEndToEnd:
    """Smart-adaptive alarms dispatch and reschedule through the same path."""

    def test_ring_then_solve_then_adaptive_reschedule(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send())
        )
        _register_device(client, auth_headers)

        alarm = _create_alarm(
            client,
            auth_headers,
            title="Smart",
            alarm_type="smart_adaptive",
            challenge_type="math",
            challenge_count=1,
        )
        assert alarm["alarm_type"] == "smart_adaptive"
        assert alarm["next_trigger_at"] is not None

        _make_due(db_session, alarm["id"])
        assert AlarmDispatchService.run_once(db_session)["dispatched"] == 1
        assert _deliver_rings(db_session)["delivered"] == 1

        client.get(
            f"/api/v1/alarms/{alarm['id']}/challenge", headers=auth_headers
        )
        answer = (
            db_session.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == test_user.id,
                ChallengeSession.alarm_id == alarm["id"],
            )
            .order_by(ChallengeSession.id.desc())
            .first()
        ).answer
        verify = client.post(
            f"/api/v1/alarms/{alarm['id']}/verify",
            json={"user_answer": answer, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert verify.status_code == 200, verify.text

        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.alarm_type == AlarmType.SMART_ADAPTIVE
        assert row.is_active is True
        assert row.next_trigger_at > _naive_utc_now()

    def test_unattended_smart_alarm_rolls_forward(
        self, client, db_session, test_user, auth_headers, user_profile,
        monkeypatch,
    ):
        monkeypatch.setattr(settings, "ALARM_MISSED_ROLLOVER_MINUTES", 30)
        alarm = _create_alarm(
            client, auth_headers, alarm_type="smart_adaptive"
        )
        _make_due(db_session, alarm["id"], seconds_ago=7200)

        result = AlarmDispatchService.run_once(db_session)

        assert result["rolled_over"] == 1
        db_session.expire_all()
        row = db_session.query(Alarm).filter(Alarm.id == alarm["id"]).one()
        assert row.next_trigger_at > _naive_utc_now()


# ── Scheduler wiring ─────────────────────────────────────────────

def test_scheduler_registers_the_alarm_dispatch_job(monkeypatch):
    """The safety net is worthless if the job is never scheduled."""
    from app.services import notification_scheduler

    monkeypatch.setattr(notification_scheduler, "_scheduler", None)
    scheduler = notification_scheduler.get_scheduler()
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(
        type(scheduler), "running", property(lambda self: False)
    )

    notification_scheduler.start_notification_scheduler()

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "alarm_dispatch_due" in job_ids
