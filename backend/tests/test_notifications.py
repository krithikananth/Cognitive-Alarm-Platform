"""
Tests for the notification system.

Covers:
- Notification model CRUD
- Device token registration / deactivation / invalid-token cleanup
- Preference create / update / read
- Bedtime reminder computation, scheduling, and dispatch
- Wake reminder from next_trigger_at, through dispatch
- Habit alert trigger conditions and dispatch
- Motivational scheduling
- Delivery status tracking and failed-push retry
- Email channel delivery and opt-in mirroring
- FCM outcome reporting (no silent degradation)
- API endpoint responses
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.db.session import SessionLocal, engine
from app.db.base import Base
from app.models.user import User
from app.models.profile import UserProfile, DifficultyPreference
from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationStatus,
    NotificationType,
    UserDeviceToken,
)
from app.services import fcm_service, notification_service
from app.services.email_service import EmailService
from app.services.notification_service import NotificationService
from app.services.fcm_service import FCMService
from app.utils.hashing import get_password_hash


# ── Helpers ──────────────────────────────────────────────────────

def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fake_send(*, successes=0, invalid=None, retryable=False):
    """Build a stand-in for ``FCMService.send_detailed``.

    Keeps delivery tests off the network while exercising the exact result
    contract the notification pipeline depends on.
    """
    invalid = list(invalid or [])

    def _send(fcm_tokens, title, body, data=None, *, image_url=None):
        tokens = list(fcm_tokens)
        failed = [t for t in tokens if t in invalid]
        if retryable:
            failed = [t for t in tokens if t not in invalid][successes:] + failed
        return {
            "success_count": min(successes, len(tokens)),
            "failure_count": len(failed),
            "failed_tokens": failed,
            "invalid_tokens": [t for t in tokens if t in invalid],
            "retryable": retryable,
            "errors": ["transient: simulated" if retryable else "invalid_token: simulated"]
            if failed
            else [],
        }

    return _send


def _capture_emails(monkeypatch):
    """Route EmailService through a list instead of SMTP; return that list."""
    captured = []

    def _send_email(*, to_email, subject, text_body, html_body=None):
        captured.append(
            {
                "to_email": to_email,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            }
        )
        return True

    monkeypatch.setattr(EmailService, "is_configured", staticmethod(lambda: True))
    monkeypatch.setattr(EmailService, "send_email", staticmethod(_send_email))
    return captured


def _make_due_notification(db, user_id, channel, *, ntype=None):
    """Insert a PENDING notification that is already due for dispatch."""
    notif = Notification(
        user_id=user_id,
        notification_type=ntype or NotificationType.MOTIVATIONAL,
        title="Delivery Probe",
        body="Checking delivery tracking.",
        channel=channel,
        status=NotificationStatus.PENDING,
        scheduled_at=_naive_utc_now() - timedelta(minutes=1),
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def _reset_prefs(db, user_id):
    """Return the user to permissive defaults between delivery tests."""
    return NotificationService.update_preferences(
        db,
        user_id,
        {
            "notifications_enabled": True,
            "notification_frequency": "all",
            "notification_sound": "default",
            "push_enabled": True,
            "email_notifications_enabled": False,
            "bedtime_reminder_enabled": True,
            "bedtime_reminder_minutes_before": 30,
            "wake_reminder_enabled": True,
            "wake_reminder_minutes_before": 15,
            "habit_alerts_enabled": True,
            "motivational_enabled": True,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        },
    )


def _deactivate_tokens(db, user_id):
    db.query(UserDeviceToken).filter(
        UserDeviceToken.user_id == user_id
    ).update({"is_active": False})
    db.commit()


def _clear_notifications(db, user_id, ntype):
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.notification_type == ntype,
    ).delete()
    db.commit()


@pytest.fixture(scope="module")
def db():
    """Provide a test database session."""
    Base.metadata.create_all(bind=engine)
    # create_all does not alter existing tables — add preference columns.
    from app.main import _ensure_sqlite_columns
    _ensure_sqlite_columns()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def test_user(db):
    """Create a test user with profile."""
    user = db.query(User).filter(User.email == "notif_test@test.com").first()
    if not user:
        user = User(
            email="notif_test@test.com",
            username="notif_tester",
            hashed_password=get_password_hash("Test@12345"),
            full_name="Notification Tester",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.flush()

        profile = UserProfile(
            user_id=user.id,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
            timezone="Asia/Kolkata",
            difficulty_preference=DifficultyPreference.MEDIUM,
            adapted_difficulty=DifficultyPreference.MEDIUM,
        )
        db.add(profile)
        db.commit()
        db.refresh(user)
    return user


@pytest.fixture(scope="module")
def test_alarm(db, test_user):
    """Create a test alarm for notification testing."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    alarm = Alarm(
        user_id=test_user.id,
        title="Morning Alarm",
        alarm_time=time(7, 0),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        challenge_difficulty="medium",
        is_active=True,
        next_trigger_at=now_utc + timedelta(hours=12),
    )
    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    return alarm


@pytest.fixture(scope="module")
def auth_headers(test_user):
    """Get auth headers for API requests."""
    client = TestClient(app)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "notif_test@test.com", "password": "Test@12345"},
    )
    if login_resp.status_code == 200:
        token = login_resp.json().get("access_token")
        return {"Authorization": f"Bearer {token}"}
    # Fallback: register then login
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "notif_test@test.com",
            "username": "notif_tester",
            "password": "Test@12345",
        },
    )
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "notif_test@test.com", "password": "Test@12345"},
    )
    token = login_resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


# ── Model Tests ──────────────────────────────────────────────────

class TestNotificationModels:
    """Test notification model creation and relationships."""

    def test_create_notification(self, db, test_user):
        """Create a notification and verify fields."""
        notif = Notification(
            user_id=test_user.id,
            notification_type=NotificationType.MOTIVATIONAL,
            title="Test Title",
            body="Test body content",
            channel=NotificationChannel.IN_APP,
            status=NotificationStatus.PENDING,
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)

        assert notif.id is not None
        assert notif.user_id == test_user.id
        assert notif.notification_type == NotificationType.MOTIVATIONAL
        assert notif.status == NotificationStatus.PENDING
        assert notif.created_at is not None

    def test_create_device_token(self, db, test_user):
        """Create a device token and verify uniqueness."""
        token = UserDeviceToken(
            user_id=test_user.id,
            fcm_token="test_fcm_token_12345_model",
            device_type="web",
            is_active=True,
        )
        db.add(token)
        db.commit()
        db.refresh(token)

        assert token.id is not None
        assert token.is_active is True

        # Cleanup
        db.delete(token)
        db.commit()

    def test_create_notification_preference(self, db, test_user):
        """Create notification preferences."""
        # Remove any existing
        existing = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == test_user.id)
            .first()
        )
        if existing:
            db.delete(existing)
            db.commit()

        prefs = NotificationPreference(
            user_id=test_user.id,
            bedtime_reminder_enabled=True,
            wake_reminder_enabled=True,
            habit_alerts_enabled=True,
            motivational_enabled=True,
        )
        db.add(prefs)
        db.commit()
        db.refresh(prefs)

        assert prefs.id is not None
        assert prefs.bedtime_reminder_minutes_before == 30
        assert prefs.wake_reminder_minutes_before == 15


# ── Service Tests ────────────────────────────────────────────────

class TestNotificationService:
    """Test notification service methods."""

    def test_compute_bedtime(self):
        """Bedtime computation from wake time and sleep duration."""
        # 7:00 AM wake, 8h sleep → 11:00 PM bedtime
        bedtime = NotificationService.compute_bedtime(time(7, 0), 8.0)
        assert bedtime == time(23, 0)

        # 6:00 AM wake, 7.5h sleep → 10:30 PM bedtime
        bedtime = NotificationService.compute_bedtime(time(6, 0), 7.5)
        assert bedtime == time(22, 30)

        # None wake time → None
        bedtime = NotificationService.compute_bedtime(None, 8.0)
        assert bedtime is None

        # Midnight wrap: 5:00 AM wake, 9h sleep → 8:00 PM
        bedtime = NotificationService.compute_bedtime(time(5, 0), 9.0)
        assert bedtime == time(20, 0)

    def test_schedule_bedtime_reminder(self, db, test_user):
        """Bedtime reminder scheduling from profile data."""
        # Clear any existing pending
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.BEDTIME_REMINDER,
        ).delete()
        db.commit()

        notif = NotificationService.schedule_bedtime_reminder(
            db, test_user.id
        )
        # Should create a notification (user has wake time 07:00, 8h sleep)
        assert notif is not None
        assert notif.notification_type == NotificationType.BEDTIME_REMINDER
        assert "11:00 PM" in notif.body or "11:00" in notif.body
        assert notif.status == NotificationStatus.PENDING

    def test_schedule_wake_reminders(self, db, test_user, test_alarm):
        """Wake reminder scheduling from alarm next_trigger_at."""
        # Clear existing
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()

        reminders = NotificationService.schedule_wake_reminders(
            db, test_user.id
        )
        assert len(reminders) >= 1
        assert reminders[0].notification_type == NotificationType.WAKE_REMINDER
        matching = [r for r in reminders if r.related_alarm_id == test_alarm.id]
        assert len(matching) == 1

    def test_schedule_wake_reminders_dedup(self, db, test_user, test_alarm):
        """Second call should not create duplicates."""
        first = NotificationService.schedule_wake_reminders(db, test_user.id)
        second = NotificationService.schedule_wake_reminders(db, test_user.id)
        # Second call returns empty (already scheduled)
        assert len(second) == 0

    def test_schedule_motivational(self, db, test_user):
        """Motivational notification scheduling."""
        # Clear existing recent motivational so dedup window is empty
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.MOTIVATIONAL,
        ).delete()
        db.commit()

        notif = NotificationService.schedule_motivational(db, test_user.id)
        assert notif is not None
        assert notif.notification_type == NotificationType.MOTIVATIONAL
        assert len(notif.title) > 0
        assert len(notif.body) > 0

    def test_schedule_motivational_dedup(self, db, test_user):
        """Second motivational within 24h must not create another row."""
        before = (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.notification_type == NotificationType.MOTIVATIONAL,
            )
            .count()
        )
        notif = NotificationService.schedule_motivational(db, test_user.id)
        after = (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.notification_type == NotificationType.MOTIVATIONAL,
            )
            .count()
        )
        # Returns existing pending or None — never inserts a duplicate
        assert after == before
        if notif is not None:
            assert notif.status == NotificationStatus.PENDING

    def test_get_or_create_preferences(self, db, test_user):
        """Preferences are lazily created if missing."""
        # Delete existing
        db.query(NotificationPreference).filter(
            NotificationPreference.user_id == test_user.id
        ).delete()
        db.commit()

        prefs = NotificationService.get_preferences(db, test_user.id)
        assert prefs is not None
        assert prefs.user_id == test_user.id
        assert prefs.bedtime_reminder_enabled is True

    def test_update_preferences(self, db, test_user):
        """Partial preference updates work correctly."""
        prefs = NotificationService.update_preferences(
            db, test_user.id,
            {"bedtime_reminder_minutes_before": 45, "push_enabled": False}
        )
        assert prefs.bedtime_reminder_minutes_before == 45
        assert prefs.push_enabled is False

        # Restore
        NotificationService.update_preferences(
            db, test_user.id,
            {"bedtime_reminder_minutes_before": 30, "push_enabled": True}
        )

    def test_register_device_token(self, db, test_user):
        """Device token registration."""
        token = NotificationService.register_device_token(
            db, test_user.id,
            fcm_token="test_fcm_token_service_12345",
            device_type="web",
            device_name="Test Browser",
        )
        assert token.id is not None
        assert token.is_active is True
        assert token.fcm_token == "test_fcm_token_service_12345"

    def test_register_device_token_reactivate(self, db, test_user):
        """Re-registering same token should reactivate it."""
        token = NotificationService.register_device_token(
            db, test_user.id,
            fcm_token="test_fcm_token_service_12345",
        )
        assert token.is_active is True

    def test_remove_device_token(self, db, test_user):
        """Token removal deactivates it."""
        removed = NotificationService.remove_device_token(
            db, test_user.id, "test_fcm_token_service_12345"
        )
        assert removed is True

        # Verify deactivated
        token = (
            db.query(UserDeviceToken)
            .filter(UserDeviceToken.fcm_token == "test_fcm_token_service_12345")
            .first()
        )
        assert token.is_active is False

    def test_process_pending_notifications(self, db, test_user):
        """Queue processing dispatches pending notifications."""
        # Create a ready notification
        notif = Notification(
            user_id=test_user.id,
            notification_type=NotificationType.MOTIVATIONAL,
            title="Ready to Send",
            body="This should be processed",
            channel=NotificationChannel.IN_APP,
            status=NotificationStatus.PENDING,
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)

        result = NotificationService.process_pending_notifications(db)
        assert result["sent"] >= 1

        # Verify status updated
        db.refresh(notif)
        assert notif.status == NotificationStatus.SENT
        assert notif.sent_at is not None

    def test_get_user_notifications(self, db, test_user):
        """Notification feed returns sent notifications."""
        result = NotificationService.get_user_notifications(
            db, test_user.id, page=1, per_page=10
        )
        assert "notifications" in result
        assert "total" in result
        assert "unread_count" in result

    def test_mark_read(self, db, test_user):
        """Mark-read updates status and read_at."""
        # Find an unread notification
        notif = (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.status == NotificationStatus.SENT,
                Notification.read_at.is_(None),
            )
            .first()
        )
        if notif:
            count = NotificationService.mark_read(
                db, test_user.id, [notif.id]
            )
            assert count == 1
            db.refresh(notif)
            assert notif.status == NotificationStatus.READ
            assert notif.read_at is not None

    def test_unread_count(self, db, test_user):
        """Unread count returns integer >= 0."""
        count = NotificationService.get_unread_count(db, test_user.id)
        assert isinstance(count, int)
        assert count >= 0

    def test_cancel_pending_for_alarm(self, db, test_user, test_alarm):
        """Deleting/disabling an alarm cancels its pending wake reminder."""
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()

        created = NotificationService.schedule_wake_reminders(db, test_user.id)
        assert len(created) >= 1

        cancelled = NotificationService.cancel_pending_for_alarm(db, test_alarm.id)
        assert cancelled >= 1

        pending = (
            db.query(Notification)
            .filter(
                Notification.related_alarm_id == test_alarm.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .count()
        )
        assert pending == 0

    def test_cancel_orphaned_wake_reminders(self, db, test_user, test_alarm):
        """Inactive alarms leave no pending wake reminders after cleanup."""
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()

        NotificationService.schedule_wake_reminders(db, test_user.id)
        test_alarm.is_active = False
        db.commit()

        cancelled = NotificationService.cancel_orphaned_wake_reminders(
            db, test_user.id
        )
        assert cancelled >= 1

        test_alarm.is_active = True
        db.commit()

    def test_disabled_type_not_scheduled(self, db, test_user):
        """Disabled preference types produce no new notifications."""
        NotificationService.update_preferences(
            db, test_user.id, {"bedtime_reminder_enabled": False}
        )
        notif = NotificationService.schedule_bedtime_reminder(db, test_user.id)
        assert notif is None

        NotificationService.update_preferences(
            db, test_user.id, {"bedtime_reminder_enabled": True}
        )

    def test_push_disabled_still_creates_in_app(self, db, test_user):
        """When push_enabled is False, queue still marks in-app as SENT."""
        NotificationService.update_preferences(
            db, test_user.id, {"push_enabled": False}
        )
        notif = Notification(
            user_id=test_user.id,
            notification_type=NotificationType.MOTIVATIONAL,
            title="In-app only",
            body="Should not push",
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(minutes=1),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)

        result = NotificationService.process_pending_notifications(db)
        assert result["sent"] >= 1
        db.refresh(notif)
        assert notif.status == NotificationStatus.SENT
        assert (notif.data or {}).get("push_delivered") is False

        NotificationService.update_preferences(
            db, test_user.id, {"push_enabled": True}
        )

    def test_quiet_hours_skips_dispatch(self, db, test_user):
        """Notifications due during quiet hours remain PENDING."""
        from zoneinfo import ZoneInfo

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .first()
        )
        tz = ZoneInfo(profile.timezone or "UTC")
        now_local = datetime.now(tz).time()
        # Quiet window that always includes "now"
        start = (datetime.combine(datetime.today(), now_local) - timedelta(minutes=30)).time()
        end = (datetime.combine(datetime.today(), now_local) + timedelta(minutes=30)).time()

        NotificationService.update_preferences(
            db,
            test_user.id,
            {"quiet_hours_start": start, "quiet_hours_end": end},
        )

        notif = Notification(
            user_id=test_user.id,
            notification_type=NotificationType.HABIT_ALERT,
            title="Quiet test",
            body="Should wait",
            channel=NotificationChannel.IN_APP,
            status=NotificationStatus.PENDING,
            scheduled_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(minutes=1),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)

        result = NotificationService.process_pending_notifications(db)
        assert result.get("quiet_hours_skipped", 0) >= 1
        db.refresh(notif)
        assert notif.status == NotificationStatus.PENDING

        # Clear quiet hours
        prefs = NotificationService.get_preferences(db, test_user.id)
        prefs.quiet_hours_start = None
        prefs.quiet_hours_end = None
        db.commit()

    def test_wake_reminder_resync_no_duplicate(self, db, test_user, test_alarm):
        """Changing next_trigger_at updates the same pending row (no duplicate)."""
        db.query(Notification).filter(
            Notification.related_alarm_id == test_alarm.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()

        # Ensure alarm is far enough out for a reminder
        test_alarm.is_active = True
        test_alarm.next_trigger_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=12)
        )
        db.commit()

        first = NotificationService.schedule_wake_reminders(db, test_user.id)
        for_alarm = [n for n in first if n.related_alarm_id == test_alarm.id]
        assert len(for_alarm) == 1
        original_id = for_alarm[0].id

        test_alarm.next_trigger_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=20)
        )
        db.commit()

        second = NotificationService.schedule_wake_reminders(db, test_user.id)
        assert all(n.related_alarm_id != test_alarm.id for n in second)

        pending = (
            db.query(Notification)
            .filter(
                Notification.related_alarm_id == test_alarm.id,
                Notification.notification_type == NotificationType.WAKE_REMINDER,
                Notification.status == NotificationStatus.PENDING,
            )
            .all()
        )
        assert len(pending) == 1
        assert pending[0].id == original_id

    def test_master_disable_cancels_pending(self, db, test_user):
        """notifications_enabled=False cancels all pending and blocks scheduling."""
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.status == NotificationStatus.PENDING,
        ).delete()
        db.commit()

        NotificationService.schedule_bedtime_reminder(db, test_user.id)
        pending_before = (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .count()
        )
        assert pending_before >= 1

        NotificationService.update_preferences(
            db, test_user.id, {"notifications_enabled": False}
        )
        pending_after = (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .count()
        )
        assert pending_after == 0
        assert NotificationService.schedule_bedtime_reminder(db, test_user.id) is None
        assert NotificationService.schedule_wake_reminders(db, test_user.id) == []

        NotificationService.update_preferences(
            db, test_user.id, {"notifications_enabled": True}
        )

    def test_frequency_essential_blocks_habit_and_motivational(self, db, test_user):
        """essential frequency allows bedtime/wake but not habit/motivational."""
        NotificationService.update_preferences(
            db,
            test_user.id,
            {
                "notifications_enabled": True,
                "notification_frequency": "essential",
                "habit_alerts_enabled": True,
                "motivational_enabled": True,
                "bedtime_reminder_enabled": True,
            },
        )
        assert NotificationService.schedule_motivational(db, test_user.id) is None
        assert NotificationService.schedule_habit_alert(db, test_user.id) is None
        bedtime = NotificationService.schedule_bedtime_reminder(db, test_user.id)
        assert bedtime is not None

        NotificationService.update_preferences(
            db, test_user.id, {"notification_frequency": "all"}
        )

    def test_frequency_minimal_wake_only(self, db, test_user, test_alarm):
        """minimal frequency schedules wake reminders only."""
        NotificationService.update_preferences(
            db,
            test_user.id,
            {
                "notifications_enabled": True,
                "notification_frequency": "minimal",
                "wake_reminder_enabled": True,
                "bedtime_reminder_enabled": True,
            },
        )
        assert NotificationService.schedule_bedtime_reminder(db, test_user.id) is None

        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()
        test_alarm.is_active = True
        test_alarm.next_trigger_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=12)
        )
        db.commit()

        wakes = NotificationService.schedule_wake_reminders(db, test_user.id)
        assert len(wakes) >= 1

        NotificationService.update_preferences(
            db, test_user.id, {"notification_frequency": "all"}
        )

    def test_notification_sound_embedded_in_payload(self, db, test_user):
        """Scheduled notifications include the configured sound in data."""
        NotificationService.update_preferences(
            db,
            test_user.id,
            {
                "notifications_enabled": True,
                "notification_frequency": "all",
                "bedtime_reminder_enabled": True,
                "notification_sound": "chime",
            },
        )
        db.query(Notification).filter(
            Notification.user_id == test_user.id,
            Notification.notification_type == NotificationType.BEDTIME_REMINDER,
        ).delete()
        db.commit()

        notif = NotificationService.schedule_bedtime_reminder(db, test_user.id)
        assert notif is not None
        assert (notif.data or {}).get("sound") == "chime"
        assert (notif.data or {}).get("silent") is False

        NotificationService.update_preferences(
            db, test_user.id, {"notification_sound": "silent"}
        )
        notif = NotificationService.schedule_bedtime_reminder(db, test_user.id)
        assert (notif.data or {}).get("sound") == "silent"
        assert (notif.data or {}).get("silent") is True

        NotificationService.update_preferences(
            db, test_user.id, {"notification_sound": "default"}
        )

    def test_quiet_hours_clear_via_null(self, db, test_user):
        """Passing null for quiet hours clears the window immediately."""
        NotificationService.update_preferences(
            db,
            test_user.id,
            {"quiet_hours_start": time(22, 0), "quiet_hours_end": time(7, 0)},
        )
        prefs = NotificationService.get_preferences(db, test_user.id)
        assert prefs.quiet_hours_start == time(22, 0)

        NotificationService.update_preferences(
            db,
            test_user.id,
            {"quiet_hours_start": None, "quiet_hours_end": None},
        )
        prefs = NotificationService.get_preferences(db, test_user.id)
        assert prefs.quiet_hours_start is None
        assert prefs.quiet_hours_end is None

    def test_lead_time_change_reschedules_immediately(self, db, test_user, test_alarm):
        """Changing wake_reminder_minutes_before rebuilds the pending wake row."""
        db.query(Notification).filter(
            Notification.related_alarm_id == test_alarm.id,
            Notification.notification_type == NotificationType.WAKE_REMINDER,
        ).delete()
        db.commit()
        test_alarm.is_active = True
        test_alarm.next_trigger_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=12)
        )
        db.commit()

        NotificationService.update_preferences(
            db,
            test_user.id,
            {
                "notifications_enabled": True,
                "notification_frequency": "all",
                "wake_reminder_enabled": True,
                "wake_reminder_minutes_before": 15,
            },
        )
        first = (
            db.query(Notification)
            .filter(
                Notification.related_alarm_id == test_alarm.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .first()
        )
        assert first is not None
        first_at = first.scheduled_at

        NotificationService.update_preferences(
            db, test_user.id, {"wake_reminder_minutes_before": 30}
        )
        second = (
            db.query(Notification)
            .filter(
                Notification.related_alarm_id == test_alarm.id,
                Notification.status == NotificationStatus.PENDING,
            )
            .first()
        )
        assert second is not None
        assert second.scheduled_at != first_at
        assert second.scheduled_at == test_alarm.next_trigger_at - timedelta(minutes=30)

        NotificationService.update_preferences(
            db, test_user.id, {"wake_reminder_minutes_before": 15}
        )


# ── FCM Delivery Tests ───────────────────────────────────────────

class TestFCMDelivery:
    """Verify FCM reports concrete outcomes instead of degrading silently."""

    def test_availability_is_explicit(self):
        """Availability tracks configuration, and the reason is never vague."""
        available = FCMService.is_available()
        assert isinstance(available, bool)
        assert available == (FCMService.unavailable_reason() is None)
        if not available:
            # A coarse, non-secret code — never a credential path.
            assert FCMService.unavailable_reason() in {
                fcm_service.REASON_DISABLED,
                fcm_service.REASON_UNAVAILABLE,
            }

    def test_send_to_device_reports_failure_for_bogus_token(self):
        """A malformed token fails cleanly rather than raising."""
        assert FCMService.send_to_device("fake_token_12345", "Test", "Body") is False

    def test_send_to_multiple_reports_per_token_outcomes(self):
        """Failures come back counted and classified, never as fake successes."""
        result = FCMService.send_to_multiple(["token1", "token2"], "Test", "Body")
        assert result["success_count"] == 0
        assert result["failure_count"] == 2
        assert set(result["failed_tokens"]) == {"token1", "token2"}
        # Every failed token is classified as either retryable or invalid.
        assert result["retryable"] or result["invalid_tokens"]

    def test_send_to_user_devices_no_tokens(self, db, test_user):
        """A user with no active tokens is reported, not counted as failure."""
        db.query(UserDeviceToken).filter(
            UserDeviceToken.user_id == test_user.id
        ).update({"is_active": False})
        db.commit()

        result = FCMService.send_to_user_devices(db, test_user.id, "Test", "Body")
        assert result["success_count"] == 0
        assert result["failure_count"] == 0
        assert result["no_devices"] is True
        assert result["retryable"] is False

    def test_transient_failure_keeps_token_active(
        self, db, test_user, monkeypatch
    ):
        """A network blip must never retire a user's devices."""
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="transient_case_token_0001"
        )

        monkeypatch.setattr(
            FCMService,
            "send_detailed",
            staticmethod(_fake_send(retryable=True)),
        )
        result = FCMService.send_to_user_devices(db, test_user.id, "T", "B")

        assert result["retryable"] is True
        assert result["deactivated_count"] == 0
        db.refresh(token)
        assert token.is_active is True
        assert token.failure_count == 1
        assert token.deactivated_at is None

    def test_invalid_token_is_retired_with_reason(
        self, db, test_user, monkeypatch
    ):
        """Firebase reporting a dead token deactivates exactly that token."""
        dead = NotificationService.register_device_token(
            db, test_user.id, fcm_token="invalid_case_token_0001"
        )
        alive = NotificationService.register_device_token(
            db, test_user.id, fcm_token="invalid_case_token_0002"
        )

        monkeypatch.setattr(
            FCMService,
            "send_detailed",
            staticmethod(_fake_send(invalid=[dead.fcm_token], successes=1)),
        )
        result = FCMService.send_to_user_devices(db, test_user.id, "T", "B")

        assert result["deactivated_count"] == 1
        db.refresh(dead)
        db.refresh(alive)
        assert dead.is_active is False
        assert dead.deactivated_reason == "fcm_invalid_token"
        assert dead.deactivated_at is not None
        # The healthy token is untouched and its success is recorded.
        assert alive.is_active is True
        assert alive.last_success_at is not None

    def test_cleanup_purges_only_long_retired_tokens(self, db, test_user):
        """Recently retired tokens stay auditable; ancient ones are purged."""
        recent = NotificationService.register_device_token(
            db, test_user.id, fcm_token="cleanup_recent_token_0001"
        )
        stale = NotificationService.register_device_token(
            db, test_user.id, fcm_token="cleanup_stale_token_0001"
        )
        recent.is_active = False
        stale.is_active = False
        stale.updated_at = _naive_utc_now() - timedelta(days=400)
        db.commit()
        stale_id = stale.id

        FCMService.cleanup_invalid_tokens(db)

        assert db.get(UserDeviceToken, stale_id) is None
        assert db.get(UserDeviceToken, recent.id) is not None
        db.delete(recent)
        db.commit()


# ── Delivery Status / Retry Tests ────────────────────────────────

class TestDeliveryTracking:
    """Delivery outcome is recorded on every notification."""

    def test_successful_push_marks_delivered(
        self, db, test_user, monkeypatch
    ):
        """An accepted push upgrades the row to DELIVERED with a timestamp."""
        _reset_prefs(db, test_user.id)
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="delivery_success_token_0001"
        )
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )

        notif = _make_due_notification(db, test_user.id, NotificationChannel.PUSH)
        NotificationService.process_pending_notifications(db)

        db.refresh(notif)
        assert notif.status == NotificationStatus.DELIVERED
        assert notif.delivered_at is not None
        assert notif.sent_at is not None
        assert notif.push_attempts == 1
        assert notif.last_error is None
        assert notif.next_retry_at is None
        assert (notif.data or {}).get("push_delivered") is True

        _deactivate_tokens(db, test_user.id)
        db.delete(token)
        db.commit()

    def test_transient_push_failure_schedules_retry(
        self, db, test_user, monkeypatch
    ):
        """A retryable failure stays visible in-app and is queued for retry."""
        _reset_prefs(db, test_user.id)
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="delivery_retry_token_0001"
        )
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(retryable=True))
        )

        notif = _make_due_notification(db, test_user.id, NotificationChannel.PUSH)
        NotificationService.process_pending_notifications(db)

        db.refresh(notif)
        # In-app delivery is unaffected by a push failure.
        assert notif.status == NotificationStatus.SENT
        assert notif.delivered_at is None
        assert notif.push_attempts == 1
        assert notif.last_error
        assert notif.next_retry_at is not None
        assert (notif.data or {}).get("push_delivered") is False

        _deactivate_tokens(db, test_user.id)
        db.delete(token)
        db.commit()

    def test_retry_sweep_upgrades_to_delivered(
        self, db, test_user, monkeypatch
    ):
        """A later successful retry promotes the notification to DELIVERED."""
        _reset_prefs(db, test_user.id)
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="delivery_sweep_token_0001"
        )
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(retryable=True))
        )

        notif = _make_due_notification(db, test_user.id, NotificationChannel.PUSH)
        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.next_retry_at is not None

        # Make the retry due, then let the next attempt succeed.
        notif.next_retry_at = _naive_utc_now() - timedelta(seconds=1)
        db.commit()
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )

        result = NotificationService.retry_failed_deliveries(db)
        assert result["delivered"] >= 1

        db.refresh(notif)
        assert notif.status == NotificationStatus.DELIVERED
        assert notif.delivered_at is not None
        assert notif.push_attempts == 2
        assert notif.next_retry_at is None
        assert notif.last_error is None

        _deactivate_tokens(db, test_user.id)
        db.delete(token)
        db.commit()

    def test_retry_gives_up_after_max_attempts(
        self, db, test_user, monkeypatch
    ):
        """Retries stop at the configured budget instead of looping forever."""
        _reset_prefs(db, test_user.id)
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="delivery_giveup_token_0001"
        )
        monkeypatch.setattr(settings, "NOTIFICATION_MAX_PUSH_ATTEMPTS", 2)
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(retryable=True))
        )

        notif = _make_due_notification(db, test_user.id, NotificationChannel.PUSH)
        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.push_attempts == 1

        notif.next_retry_at = _naive_utc_now() - timedelta(seconds=1)
        db.commit()
        NotificationService.retry_failed_deliveries(db)

        db.refresh(notif)
        assert notif.push_attempts == 2
        assert notif.next_retry_at is None
        assert notif.status == NotificationStatus.SENT
        assert notif.last_error

        # Exhausted rows are no longer picked up by the sweep.
        assert NotificationService.retry_failed_deliveries(db)["attempted"] == 0

        _deactivate_tokens(db, test_user.id)
        db.delete(token)
        db.commit()

    def test_invalid_token_failure_is_not_retried(
        self, db, test_user, monkeypatch
    ):
        """A dead token is a permanent failure — no pointless retries."""
        _reset_prefs(db, test_user.id)
        token = NotificationService.register_device_token(
            db, test_user.id, fcm_token="delivery_invalid_token_0001"
        )
        monkeypatch.setattr(
            FCMService,
            "send_detailed",
            staticmethod(_fake_send(invalid=[token.fcm_token])),
        )

        notif = _make_due_notification(db, test_user.id, NotificationChannel.PUSH)
        NotificationService.process_pending_notifications(db)

        db.refresh(notif)
        db.refresh(token)
        assert notif.status == NotificationStatus.SENT
        assert notif.next_retry_at is None
        assert notif.last_error
        assert token.is_active is False

        db.delete(token)
        db.commit()

    def test_preference_cancellation_records_reason(self, db, test_user):
        """Turning a type off cancels its pending rows with an explanation."""
        _reset_prefs(db, test_user.id)
        notif = _make_due_notification(
            db, test_user.id, NotificationChannel.IN_APP
        )
        NotificationService.update_preferences(
            db, test_user.id, {"motivational_enabled": False}
        )

        db.refresh(notif)
        assert notif.status == NotificationStatus.FAILED
        assert notif.last_error == "cancelled_type_disabled"

        _reset_prefs(db, test_user.id)

    def test_dispatch_of_disabled_type_records_reason(self, db, test_user):
        """A type disabled after scheduling is cancelled at dispatch, with a reason."""
        prefs = _reset_prefs(db, test_user.id)
        notif = _make_due_notification(
            db, test_user.id, NotificationChannel.IN_APP
        )
        # Bypass update_preferences so the row survives to the dispatcher.
        prefs.motivational_enabled = False
        db.commit()

        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.status == NotificationStatus.FAILED
        assert notif.last_error == "type_disabled_by_user_preference"

        _reset_prefs(db, test_user.id)


# ── Email Delivery Tests ─────────────────────────────────────────

class TestEmailNotifications:
    """Email channel delivers through EmailService."""

    def test_email_channel_delivers_when_smtp_configured(
        self, db, test_user, monkeypatch
    ):
        """An EMAIL notification is sent over SMTP and marked DELIVERED."""
        _reset_prefs(db, test_user.id)
        sent = _capture_emails(monkeypatch)

        notif = _make_due_notification(
            db, test_user.id, NotificationChannel.EMAIL
        )
        NotificationService.process_pending_notifications(db)

        db.refresh(notif)
        assert notif.status == NotificationStatus.DELIVERED
        assert notif.delivered_at is not None
        assert notif.email_attempts == 1
        assert (notif.data or {}).get("email_delivered") is True
        assert len(sent) == 1
        assert sent[0]["to_email"] == test_user.email
        assert sent[0]["subject"] == notif.title

    def test_email_channel_fails_clearly_without_smtp(
        self, db, test_user, monkeypatch
    ):
        """Without SMTP the notification fails with an actionable reason."""
        _reset_prefs(db, test_user.id)
        monkeypatch.setattr(EmailService, "is_configured", staticmethod(lambda: False))

        notif = _make_due_notification(
            db, test_user.id, NotificationChannel.EMAIL
        )
        NotificationService.process_pending_notifications(db)

        db.refresh(notif)
        assert notif.status == NotificationStatus.FAILED
        assert notif.last_error == "email_not_configured"

    def test_email_mirror_only_for_opted_in_users(
        self, db, test_user, monkeypatch
    ):
        """Push notifications are emailed only when the user opts the channel in."""
        _reset_prefs(db, test_user.id)
        sent = _capture_emails(monkeypatch)
        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )

        # Opted out (default) → no email.
        opted_out = _make_due_notification(
            db, test_user.id, NotificationChannel.PUSH
        )
        NotificationService.process_pending_notifications(db)
        db.refresh(opted_out)
        assert (opted_out.data or {}).get("email_delivered") is None
        assert sent == []

        # Opted in → an email copy accompanies the push.
        NotificationService.update_preferences(
            db, test_user.id, {"email_notifications_enabled": True}
        )
        opted_in = _make_due_notification(
            db, test_user.id, NotificationChannel.PUSH
        )
        NotificationService.process_pending_notifications(db)

        db.refresh(opted_in)
        assert (opted_in.data or {}).get("email_delivered") is True
        assert len(sent) == 1
        assert sent[0]["to_email"] == test_user.email

        _reset_prefs(db, test_user.id)


# ── Reminder Verification (bedtime / wake / habit) ───────────────

class TestReminderDeliveryEndToEnd:
    """Each reminder type schedules, becomes due, and dispatches."""

    def test_bedtime_reminder_schedules_and_dispatches(
        self, db, test_user, monkeypatch
    ):
        """Bedtime reminder fires at wake_time minus sleep minus lead time."""
        _reset_prefs(db, test_user.id)
        _clear_notifications(db, test_user.id, NotificationType.BEDTIME_REMINDER)

        notif = NotificationService.schedule_bedtime_reminder(db, test_user.id)
        assert notif is not None
        assert notif.status == NotificationStatus.PENDING
        assert notif.channel == NotificationChannel.PUSH

        # 07:00 wake − 8h sleep = 23:00 bedtime, reminded 30 min earlier.
        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .first()
        )
        tz = ZoneInfo(profile.timezone or "UTC")
        local = (
            notif.scheduled_at.replace(tzinfo=timezone.utc).astimezone(tz)
        )
        assert (local.hour, local.minute) == (22, 30)

        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )
        notif.scheduled_at = _naive_utc_now() - timedelta(minutes=1)
        db.commit()

        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.status in (
            NotificationStatus.SENT,
            NotificationStatus.DELIVERED,
        )
        assert notif.sent_at is not None

    def test_wake_reminder_schedules_and_dispatches(
        self, db, test_user, test_alarm, monkeypatch
    ):
        """Wake reminder fires the configured lead time before the alarm."""
        _reset_prefs(db, test_user.id)
        _clear_notifications(db, test_user.id, NotificationType.WAKE_REMINDER)
        test_alarm.is_active = True
        test_alarm.next_trigger_at = _naive_utc_now() + timedelta(hours=6)
        db.commit()

        created = NotificationService.schedule_wake_reminders(db, test_user.id)
        mine = [n for n in created if n.related_alarm_id == test_alarm.id]
        assert len(mine) == 1
        notif = mine[0]
        assert notif.scheduled_at == test_alarm.next_trigger_at - timedelta(
            minutes=15
        )
        assert (notif.data or {})["alarm_id"] == test_alarm.id

        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )
        notif.scheduled_at = _naive_utc_now() - timedelta(minutes=1)
        db.commit()

        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.status in (
            NotificationStatus.SENT,
            NotificationStatus.DELIVERED,
        )
        assert notif.sent_at is not None

    def test_habit_alert_fires_on_low_score_and_dispatches(
        self, db, test_user, monkeypatch
    ):
        """A habit score under the admin threshold produces one alert per day."""
        _reset_prefs(db, test_user.id)
        _clear_notifications(db, test_user.id, NotificationType.HABIT_ALERT)

        monkeypatch.setattr(
            notification_service,
            "calculate_habit_score_for_user",
            lambda *a, **k: {
                "habit_score": 11.0,
                "streak_days": 0,
                "breakdown": {
                    "wake_up_consistency": 10.0,
                    "snooze_reduction": 10.0,
                    "sleep_adherence": 10.0,
                },
            },
            raising=False,
        )
        monkeypatch.setattr(
            "app.services.habit_score.calculate_habit_score_for_user",
            lambda *a, **k: {
                "habit_score": 11.0,
                "streak_days": 0,
                "breakdown": {
                    "wake_up_consistency": 10.0,
                    "snooze_reduction": 10.0,
                    "sleep_adherence": 10.0,
                },
            },
        )

        notif = NotificationService.schedule_habit_alert(db, test_user.id)
        assert notif is not None
        assert notif.notification_type == NotificationType.HABIT_ALERT
        assert notif.status == NotificationStatus.PENDING

        # Deduped to at most one alert per 24 hours.
        assert NotificationService.schedule_habit_alert(db, test_user.id) is None

        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )
        NotificationService.process_pending_notifications(db)
        db.refresh(notif)
        assert notif.status in (
            NotificationStatus.SENT,
            NotificationStatus.DELIVERED,
        )
        assert notif.sent_at is not None

        _clear_notifications(db, test_user.id, NotificationType.HABIT_ALERT)


# ── Challenge Reminders & Progress Updates ───────────────────────

def _add_challenge_log(db, user_id, alarm_id, created_at, *, correct=True):
    row = AlarmChallengeLog(
        user_id=user_id,
        alarm_id=alarm_id,
        challenge_type="math",
        difficulty="medium",
        challenge_prompt="2+2?",
        is_correct=correct,
        time_taken_seconds=9,
        failed_attempts=0,
        points_earned=10 if correct else 0,
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    return row


def _add_wake_event(db, user_id, alarm_id, dismissed_at, *, verified=True):
    row = AlarmWakeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        triggered_at=dismissed_at - timedelta(minutes=5),
        dismissed_at=dismissed_at,
        dismiss_method="challenge",
        snooze_count_at_dismiss=0,
        time_to_dismiss_seconds=300,
        verified=verified,
        wakefulness_score=80.0,
        wakefulness_level="alert",
        failed_attempts=0,
        challenges_required=1,
        challenges_completed=1,
    )
    db.add(row)
    db.commit()
    return row


def _clear_activity(db, user_id):
    db.query(AlarmChallengeLog).filter(
        AlarmChallengeLog.user_id == user_id
    ).delete()
    db.query(AlarmWakeEvent).filter(
        AlarmWakeEvent.user_id == user_id
    ).delete()
    db.commit()


def _force_prefs(db, user_id):
    """Set permissive preferences without triggering any scheduling.

    ``update_preferences`` re-schedules on re-enable, which would create the
    very row these tests are trying to assert about.
    """
    prefs = NotificationService.get_preferences(db, user_id)
    prefs.notifications_enabled = True
    prefs.notification_frequency = "all"
    prefs.notification_sound = "default"
    prefs.push_enabled = True
    prefs.challenge_reminders_enabled = True
    prefs.progress_updates_enabled = True
    prefs.quiet_hours_start = None
    prefs.quiet_hours_end = None
    db.commit()
    return prefs


class TestChallengeReminders:
    """Practice nudges for users who stopped attempting challenges."""

    @pytest.fixture(autouse=True)
    def _clean(self, db, test_user, test_alarm):
        _force_prefs(db, test_user.id)
        _clear_notifications(
            db, test_user.id, NotificationType.CHALLENGE_REMINDER
        )
        _clear_activity(db, test_user.id)
        db.query(Alarm).filter(Alarm.user_id == test_user.id).update(
            {"is_active": True}
        )
        db.commit()
        yield
        _clear_notifications(
            db, test_user.id, NotificationType.CHALLENGE_REMINDER
        )
        _clear_activity(db, test_user.id)

    def test_recent_practice_suppresses_the_nudge(self, db, test_user, test_alarm):
        """A user who practised today does not need a reminder."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(hours=3)
        )
        assert (
            NotificationService.schedule_challenge_reminder(db, test_user.id)
            is None
        )

    def test_idle_user_is_reminded_with_measured_idle_days(
        self, db, test_user, test_alarm
    ):
        """The nudge reports the real gap since the last attempt."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(days=5)
        )

        notif = NotificationService.schedule_challenge_reminder(db, test_user.id)
        assert notif is not None
        assert notif.notification_type == NotificationType.CHALLENGE_REMINDER
        assert notif.status == NotificationStatus.PENDING
        assert notif.data["days_since_last_attempt"] == 5
        assert notif.data["url"] == "/practice"
        assert "5 days" in notif.body
        # Delivered at the user's local evening — never in the past.
        assert notif.scheduled_at > _naive_utc_now()

    def test_cooldown_reuses_the_pending_row(self, db, test_user, test_alarm):
        """A second sweep on the same day must not queue a duplicate."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(days=5)
        )
        first = NotificationService.schedule_challenge_reminder(db, test_user.id)
        second = NotificationService.schedule_challenge_reminder(db, test_user.id)

        assert first is not None and second is not None
        assert second.id == first.id
        assert (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.notification_type
                == NotificationType.CHALLENGE_REMINDER,
            )
            .count()
            == 1
        )

    def test_first_challenge_nudge_requires_an_active_alarm(
        self, db, test_user, test_alarm
    ):
        """Users with no alarms and no history are not cold-nudged."""
        db.query(Alarm).filter(Alarm.user_id == test_user.id).update(
            {"is_active": False}
        )
        db.commit()
        assert (
            NotificationService.schedule_challenge_reminder(db, test_user.id)
            is None
        )

        db.query(Alarm).filter(Alarm.user_id == test_user.id).update(
            {"is_active": True}
        )
        db.commit()
        notif = NotificationService.schedule_challenge_reminder(db, test_user.id)
        assert notif is not None
        assert "First Challenge" in notif.title
        assert "days_since_last_attempt" not in notif.data

    def test_disabled_preference_cancels_and_blocks(
        self, db, test_user, test_alarm
    ):
        """Turning the toggle off cancels the pending nudge and stops new ones."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(days=5)
        )
        pending = NotificationService.schedule_challenge_reminder(
            db, test_user.id
        )
        assert pending is not None

        NotificationService.update_preferences(
            db, test_user.id, {"challenge_reminders_enabled": False}
        )
        db.refresh(pending)
        assert pending.status == NotificationStatus.FAILED
        assert (
            NotificationService.schedule_challenge_reminder(db, test_user.id)
            is None
        )

    def test_essential_frequency_blocks_challenge_reminders(
        self, db, test_user, test_alarm
    ):
        """Practice nudges are not essential traffic."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(days=5)
        )
        NotificationService.update_preferences(
            db, test_user.id, {"notification_frequency": "essential"}
        )
        try:
            assert (
                NotificationService.schedule_challenge_reminder(db, test_user.id)
                is None
            )
        finally:
            NotificationService.update_preferences(
                db, test_user.id, {"notification_frequency": "all"}
            )

    def test_reminder_dispatches_through_the_queue(
        self, db, test_user, test_alarm, monkeypatch
    ):
        """The nudge reaches dispatch like any other scheduled notification."""
        _add_challenge_log(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(days=5)
        )
        notif = NotificationService.schedule_challenge_reminder(db, test_user.id)
        assert notif is not None

        notif.scheduled_at = _naive_utc_now() - timedelta(minutes=1)
        db.commit()

        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )
        NotificationService.process_pending_notifications(
            db, only_types=[NotificationType.CHALLENGE_REMINDER]
        )
        db.refresh(notif)
        assert notif.status in (
            NotificationStatus.SENT,
            NotificationStatus.DELIVERED,
        )
        assert notif.sent_at is not None


class TestProgressUpdates:
    """Weekly recap built from real wake-up and challenge activity."""

    @pytest.fixture(autouse=True)
    def _clean(self, db, test_user, test_alarm):
        _force_prefs(db, test_user.id)
        _clear_notifications(db, test_user.id, NotificationType.PROGRESS_UPDATE)
        _clear_activity(db, test_user.id)
        yield
        _clear_notifications(db, test_user.id, NotificationType.PROGRESS_UPDATE)
        _clear_activity(db, test_user.id)

    def test_no_recap_without_activity(self, db, test_user):
        """An empty week is not progress — nothing is sent."""
        assert (
            NotificationService.schedule_progress_update(db, test_user.id)
            is None
        )

    def test_recap_reports_measured_activity(self, db, test_user, test_alarm):
        """Counts and accuracy come from stored events, not from copy."""
        now = _naive_utc_now()
        _add_wake_event(db, test_user.id, test_alarm.id, now - timedelta(days=1))
        _add_wake_event(db, test_user.id, test_alarm.id, now - timedelta(days=2))
        _add_challenge_log(
            db, test_user.id, test_alarm.id, now - timedelta(days=1)
        )
        _add_challenge_log(
            db, test_user.id, test_alarm.id, now - timedelta(days=2), correct=False
        )

        notif = NotificationService.schedule_progress_update(db, test_user.id)
        assert notif is not None
        assert notif.notification_type == NotificationType.PROGRESS_UPDATE
        assert notif.status == NotificationStatus.PENDING
        assert notif.data["period_days"] == 7
        assert notif.data["verified_wakes"] == 2
        assert notif.data["challenge_attempts"] == 2
        assert notif.data["challenge_accuracy"] == 50.0
        assert notif.data["url"] == "/analytics"
        assert "2 verified wake-ups" in notif.body
        assert "50% accuracy" in notif.body
        assert notif.scheduled_at > _naive_utc_now()

    def test_activity_outside_the_window_is_ignored(
        self, db, test_user, test_alarm
    ):
        """Events older than the recap period cannot manufacture progress."""
        old = _naive_utc_now() - timedelta(days=30)
        _add_wake_event(db, test_user.id, test_alarm.id, old)
        _add_challenge_log(db, test_user.id, test_alarm.id, old)

        assert (
            NotificationService.schedule_progress_update(db, test_user.id)
            is None
        )

    def test_streak_milestone_headlines_the_recap(
        self, db, test_user, test_alarm
    ):
        """A milestone streak is called out instead of the generic title."""
        _add_wake_event(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(hours=6)
        )
        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .first()
        )
        previous = (
            profile.streak_days,
            profile.best_streak,
            profile.last_successful_wake_date,
        )
        profile.streak_days = 7
        profile.best_streak = 7
        # Today's local date, so missed-day decay does not reset the streak.
        profile.last_successful_wake_date = datetime.now(
            ZoneInfo(profile.timezone or "UTC")
        ).date()
        db.commit()

        try:
            notif = NotificationService.schedule_progress_update(
                db, test_user.id
            )
            assert notif is not None
            assert notif.title.startswith("7-Day Streak")
            assert notif.data["milestone"] == 7
            assert notif.data["streak_days"] == 7
        finally:
            (
                profile.streak_days,
                profile.best_streak,
                profile.last_successful_wake_date,
            ) = previous
            db.commit()

    def test_weekly_cooldown_reuses_the_pending_row(
        self, db, test_user, test_alarm
    ):
        """A daily sweep produces at most one recap per week."""
        _add_wake_event(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(hours=6)
        )
        first = NotificationService.schedule_progress_update(db, test_user.id)
        second = NotificationService.schedule_progress_update(db, test_user.id)

        assert first is not None and second is not None
        assert second.id == first.id
        assert (
            db.query(Notification)
            .filter(
                Notification.user_id == test_user.id,
                Notification.notification_type
                == NotificationType.PROGRESS_UPDATE,
            )
            .count()
            == 1
        )

    def test_disabled_preference_cancels_and_blocks(
        self, db, test_user, test_alarm
    ):
        """Turning the toggle off cancels the pending recap and stops new ones."""
        _add_wake_event(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(hours=6)
        )
        pending = NotificationService.schedule_progress_update(db, test_user.id)
        assert pending is not None

        NotificationService.update_preferences(
            db, test_user.id, {"progress_updates_enabled": False}
        )
        db.refresh(pending)
        assert pending.status == NotificationStatus.FAILED
        assert (
            NotificationService.schedule_progress_update(db, test_user.id)
            is None
        )

    def test_recap_dispatches_through_the_queue(
        self, db, test_user, test_alarm, monkeypatch
    ):
        """The recap reaches dispatch like any other scheduled notification."""
        _add_wake_event(
            db, test_user.id, test_alarm.id, _naive_utc_now() - timedelta(hours=6)
        )
        notif = NotificationService.schedule_progress_update(db, test_user.id)
        assert notif is not None

        notif.scheduled_at = _naive_utc_now() - timedelta(minutes=1)
        db.commit()

        monkeypatch.setattr(
            FCMService, "send_detailed", staticmethod(_fake_send(successes=1))
        )
        NotificationService.process_pending_notifications(
            db, only_types=[NotificationType.PROGRESS_UPDATE]
        )
        db.refresh(notif)
        assert notif.status in (
            NotificationStatus.SENT,
            NotificationStatus.DELIVERED,
        )
        assert notif.sent_at is not None


# ── API Endpoint Tests ───────────────────────────────────────────

class TestNotificationAPI:
    """Test notification REST endpoints."""

    def test_get_preferences(self, auth_headers):
        """GET /notifications/preferences returns defaults."""
        client = TestClient(app)
        resp = client.get(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "bedtime_reminder_enabled" in data
        assert "wake_reminder_enabled" in data
        assert "challenge_reminders_enabled" in data
        assert "progress_updates_enabled" in data

    def test_update_engagement_toggles(self, auth_headers):
        """PUT /notifications/preferences persists the new type toggles."""
        client = TestClient(app)
        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "challenge_reminders_enabled": False,
                "progress_updates_enabled": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["challenge_reminders_enabled"] is False
        assert data["progress_updates_enabled"] is False

        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "challenge_reminders_enabled": True,
                "progress_updates_enabled": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["challenge_reminders_enabled"] is True
        assert resp.json()["progress_updates_enabled"] is True

    def test_update_preferences(self, auth_headers):
        """PUT /notifications/preferences updates fields."""
        client = TestClient(app)
        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "bedtime_reminder_minutes_before": 45,
                "motivational_enabled": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["bedtime_reminder_minutes_before"] == 45
        assert data["motivational_enabled"] is False

        # Restore defaults
        client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "bedtime_reminder_minutes_before": 30,
                "motivational_enabled": True,
            },
        )

    def test_register_device_token(self, auth_headers):
        """POST /notifications/device-token registers a token."""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/notifications/device-token",
            headers=auth_headers,
            json={
                "fcm_token": "api_test_token_abcdefgh1234567890",
                "device_type": "web",
                "device_name": "Test API",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_active"] is True

    def test_remove_device_token(self, auth_headers):
        """DELETE /notifications/device-token deactivates the token."""
        client = TestClient(app)
        resp = client.delete(
            "/api/v1/notifications/device-token",
            headers=auth_headers,
            params={"fcm_token": "api_test_token_abcdefgh1234567890"},
        )
        assert resp.status_code == 200

    def test_list_notifications(self, auth_headers):
        """GET /notifications/ returns paginated feed."""
        client = TestClient(app)
        resp = client.get(
            "/api/v1/notifications/",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert "total" in data
        assert "unread_count" in data

    def test_list_pending_notifications(self, auth_headers):
        """GET /notifications/pending returns upcoming local-schedule items."""
        client = TestClient(app)
        resp = client.get(
            "/api/v1/notifications/pending",
            headers=auth_headers,
            params={"within_hours": 24},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications" in data
        assert isinstance(data["notifications"], list)

    def test_unread_count(self, auth_headers):
        """GET /notifications/unread-count returns count."""
        client = TestClient(app)
        resp = client.get(
            "/api/v1/notifications/unread-count",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "unread_count" in data
        assert isinstance(data["unread_count"], int)

    def test_send_test_notification(self, auth_headers):
        """POST /notifications/test creates a test notification."""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/notifications/test",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "notification_id" in data
        assert "fcm_available" in data

    def test_mark_read(self, auth_headers):
        """POST /notifications/mark-read marks notifications."""
        client = TestClient(app)
        # First get a notification ID
        list_resp = client.get(
            "/api/v1/notifications/",
            headers=auth_headers,
        )
        notifications = list_resp.json().get("notifications", [])
        if notifications:
            notif_id = notifications[0]["id"]
            resp = client.post(
                "/api/v1/notifications/mark-read",
                headers=auth_headers,
                json={"notification_ids": [notif_id]},
            )
            assert resp.status_code == 200

    def test_update_preferences_empty_body(self, auth_headers):
        """PUT /notifications/preferences with empty body returns 422."""
        client = TestClient(app)
        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={},
        )
        assert resp.status_code == 422

    def test_update_preferences_sound_and_frequency(self, auth_headers):
        """PUT preferences accepts notification_sound and notification_frequency."""
        client = TestClient(app)
        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "notifications_enabled": True,
                "notification_sound": "gentle",
                "notification_frequency": "essential",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notifications_enabled"] is True
        assert data["notification_sound"] == "gentle"
        assert data["notification_frequency"] == "essential"

        # Restore
        client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={
                "notification_sound": "default",
                "notification_frequency": "all",
            },
        )

    def test_update_preferences_invalid_sound(self, auth_headers):
        """Invalid notification_sound is rejected by schema validation."""
        client = TestClient(app)
        resp = client.put(
            "/api/v1/notifications/preferences",
            headers=auth_headers,
            json={"notification_sound": "laser"},
        )
        assert resp.status_code == 422

    def test_remove_nonexistent_token(self, auth_headers):
        """DELETE /notifications/device-token with unknown token returns 404."""
        client = TestClient(app)
        resp = client.delete(
            "/api/v1/notifications/device-token",
            headers=auth_headers,
            params={"fcm_token": "nonexistent_token_xxxxxxxxxxxxxxxxxx"},
        )
        assert resp.status_code == 404
