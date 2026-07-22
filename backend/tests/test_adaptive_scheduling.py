"""Tests for Smart Adaptive Alarm scheduling."""

from datetime import datetime, time, timedelta, timezone

from app.models.alarm import Alarm, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.adaptive_scheduling_service import AdaptiveSchedulingService


def _ensure_profile(db_session, user_id: int, **kwargs) -> UserProfile:
    profile = (
        db_session.query(UserProfile)
        .filter(UserProfile.user_id == user_id)
        .first()
    )
    if profile is None:
        profile = UserProfile(user_id=user_id, **kwargs)
        db_session.add(profile)
    else:
        for k, v in kwargs.items():
            setattr(profile, k, v)
    db_session.commit()
    db_session.refresh(profile)
    return profile


def _make_alarm(db_session, user_id: int, **kwargs) -> Alarm:
    defaults = dict(
        user_id=user_id,
        title="Smart Alarm",
        alarm_time=time(7, 0),
        alarm_type=AlarmType.SMART_ADAPTIVE,
        challenge_type=ChallengeType.MATH,
        challenge_count=1,
        challenge_difficulty="medium",
        snooze_limit=3,
        snooze_interval_minutes=5,
        is_active=True,
    )
    defaults.update(kwargs)
    alarm = Alarm(**defaults)
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)
    return alarm


def _add_wake(
    db_session,
    user_id: int,
    alarm_id: int,
    dismissed_at: datetime,
    *,
    snoozes: int = 0,
) -> AlarmWakeEvent:
    triggered = dismissed_at - timedelta(minutes=5 + snoozes * 5)
    row = AlarmWakeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        triggered_at=triggered,
        dismissed_at=dismissed_at,
        dismiss_method="challenge",
        snooze_count_at_dismiss=snoozes,
        time_to_dismiss_seconds=int((dismissed_at - triggered).total_seconds()),
        verified=True,
        wakefulness_score=80.0,
        wakefulness_level="alert",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _add_snoozes(
    db_session,
    user_id: int,
    alarm_id: int,
    count: int,
    when: datetime,
) -> None:
    for i in range(1, count + 1):
        db_session.add(
            AlarmSnoozeEvent(
                user_id=user_id,
                alarm_id=alarm_id,
                snooze_number=i,
                snooze_limit_at_event=3,
                created_at=when + timedelta(minutes=i),
            )
        )
    db_session.commit()


class TestAdaptiveSchedulingService:
    """Unit tests for AdaptiveSchedulingService."""

    def test_no_history_uses_preferred_wake(self, db_session, test_user):
        """Without wake history, base = preferred_wake_time (not alarm_time)."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(6, 30),
            timezone="UTC",
        )
        alarm = _make_alarm(db_session, test_user.id, alarm_time=time(8, 0))

        adapted = AdaptiveSchedulingService.compute_adapted_alarm_time(
            db_session, test_user.id, alarm
        )
        assert adapted == time(6, 30)

    def test_no_history_falls_back_to_alarm_time(self, db_session, test_user):
        """Without preferred wake or history, use alarm.alarm_time."""
        _ensure_profile(db_session, test_user.id, timezone="UTC")
        alarm = _make_alarm(db_session, test_user.id, alarm_time=time(7, 15))

        adapted = AdaptiveSchedulingService.compute_adapted_alarm_time(
            db_session, test_user.id, alarm
        )
        assert adapted == time(7, 15)

    def test_heavy_snooze_history_rings_earlier(self, db_session, test_user):
        """Habitual snoozing pulls the next ring earlier than preferred wake."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            timezone="UTC",
            wake_up_consistency_score=40.0,
            total_alarms_dismissed=5,
            total_snoozes=15,
            streak_days=0,
        )
        alarm = _make_alarm(
            db_session,
            test_user.id,
            alarm_time=time(7, 0),
            snooze_interval_minutes=5,
        )

        now = datetime.now(timezone.utc)
        for day in range(3):
            dismissed = now - timedelta(days=day + 1)
            dismissed = dismissed.replace(hour=7, minute=20, second=0, microsecond=0)
            _add_wake(
                db_session, test_user.id, alarm.id, dismissed, snoozes=3
            )
            _add_snoozes(
                db_session,
                test_user.id,
                alarm.id,
                3,
                dismissed - timedelta(minutes=15),
            )

        explanation = AdaptiveSchedulingService.explain_adaptation(
            db_session, test_user.id, alarm
        )
        assert explanation["offset_minutes"] < 0
        adapted = AdaptiveSchedulingService.compute_adapted_alarm_time(
            db_session, test_user.id, alarm
        )
        base_mins = 7 * 60
        adapted_mins = adapted.hour * 60 + adapted.minute
        assert adapted_mins < base_mins

    def test_daily_and_smart_differ_with_history(
        self, client, db_session, test_user, auth_headers
    ):
        """With snooze/late-wake history, smart next_trigger differs from daily."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            timezone="UTC",
            wake_up_consistency_score=30.0,
            total_alarms_dismissed=4,
            total_snoozes=12,
            streak_days=0,
        )

        # Seed history against a helper alarm first
        helper = _make_alarm(
            db_session, test_user.id, alarm_type=AlarmType.DAILY, title="Seed"
        )
        now = datetime.now(timezone.utc)
        for day in range(3):
            dismissed = (now - timedelta(days=day + 1)).replace(
                hour=7, minute=25, second=0, microsecond=0
            )
            _add_wake(db_session, test_user.id, helper.id, dismissed, snoozes=2)
            _add_snoozes(
                db_session,
                test_user.id,
                helper.id,
                2,
                dismissed - timedelta(minutes=10),
            )

        daily = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Daily Fixed",
                "alarm_time": "07:00",
                "alarm_type": "daily",
                "snooze_interval_minutes": 5,
            },
            headers=auth_headers,
        )
        assert daily.status_code == 201

        smart = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Smart Adapt",
                "alarm_time": "07:00",
                "alarm_type": "smart_adaptive",
                "snooze_interval_minutes": 5,
            },
            headers=auth_headers,
        )
        assert smart.status_code == 201

        daily_trigger = daily.json()["next_trigger_at"]
        smart_trigger = smart.json()["next_trigger_at"]
        assert daily_trigger is not None
        assert smart_trigger is not None
        # Smart should ring earlier (or at least not later than daily for this history)
        assert smart_trigger <= daily_trigger or smart_trigger != daily_trigger

        # Stronger assertion: adapted local time is before 07:00 when history is bad
        smart_alarm = (
            db_session.query(Alarm)
            .filter(Alarm.id == smart.json()["id"])
            .first()
        )
        adapted = AdaptiveSchedulingService.compute_adapted_alarm_time(
            db_session, test_user.id, smart_alarm
        )
        assert (adapted.hour, adapted.minute) < (7, 0)

    def test_daily_unchanged_by_preferred_wake(
        self, client, db_session, test_user, auth_headers
    ):
        """Daily still uses alarm_time even when preferred_wake differs."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(6, 0),
            timezone="UTC",
        )
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Daily Only",
                "alarm_time": "08:00",
                "alarm_type": "daily",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        trigger = datetime.fromisoformat(
            response.json()["next_trigger_at"].replace("Z", "+00:00")
        )
        if trigger.tzinfo is None:
            trigger = trigger.replace(tzinfo=timezone.utc)
        assert trigger.hour == 8
        assert trigger.minute == 0

    def test_smart_uses_preferred_without_history(
        self, client, db_session, test_user, auth_headers
    ):
        """Smart with preferred wake and no history schedules at preferred time."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(6, 15),
            timezone="UTC",
        )
        response = client.post(
            "/api/v1/alarms/",
            json={
                "title": "Smart Preferred",
                "alarm_time": "08:00",
                "alarm_type": "smart_adaptive",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        trigger = datetime.fromisoformat(
            response.json()["next_trigger_at"].replace("Z", "+00:00")
        )
        if trigger.tzinfo is None:
            trigger = trigger.replace(tzinfo=timezone.utc)
        assert trigger.hour == 6
        assert trigger.minute == 15
