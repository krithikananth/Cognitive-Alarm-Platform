"""Tests for the pandas/numpy Behavioral Analytics module."""

from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from app.models.alarm import Alarm, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.behavioral_analytics_service import BehavioralAnalyticsService
from app.services.habit_score import calculate_habit_score


def _make_alarm(db_session, user_id: int) -> Alarm:
    alarm = Alarm(
        user_id=user_id,
        title="Behavioral Alarm",
        alarm_time=time(7, 0),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        challenge_count=1,
        challenge_difficulty="medium",
        snooze_limit=3,
    )
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)
    return alarm


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


def _add_wake(
    db_session,
    user_id: int,
    alarm_id: int,
    dismissed_at: datetime,
    *,
    snoozes: int = 0,
    verified: bool = True,
    method: str = "challenge",
) -> AlarmWakeEvent:
    triggered = dismissed_at - timedelta(minutes=5 + snoozes * 5)
    row = AlarmWakeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        triggered_at=triggered,
        dismissed_at=dismissed_at,
        dismiss_method=method,
        snooze_count_at_dismiss=snoozes,
        time_to_dismiss_seconds=int((dismissed_at - triggered).total_seconds()),
        verified=verified,
        wakefulness_score=80.0,
        wakefulness_level="alert",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _add_snooze(
    db_session,
    user_id: int,
    alarm_id: int,
    created_at: datetime,
    snooze_number: int = 1,
    snooze_limit: int = 3,
) -> AlarmSnoozeEvent:
    row = AlarmSnoozeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        snooze_number=snooze_number,
        snooze_limit_at_event=snooze_limit,
        next_trigger_at=created_at + timedelta(minutes=5),
        created_at=created_at,
    )
    db_session.add(row)
    db_session.commit()
    return row


class TestBehavioralAnalyticsService:
    def test_empty_overview(self, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
        )
        result = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=30
        )
        assert result["snooze_pattern"]["total_snoozes"] == 0
        assert result["wake_up_consistency"]["verified_wakes"] == 0
        assert result["weekly_trends"]["period"] == "week"
        assert result["monthly_trends"]["days"] == 30
        assert len(result["weekly_trends"]["series"]) == 7
        assert len(result["monthly_trends"]["series"]) == 30
        assert len(result["habit_trends"]["series"]) == 30
        assert result["habit_trends"]["current_habit_score"] == calculate_habit_score(
            {
                "wake_up_consistency_score": 0.0,
                "total_alarms_dismissed": 0,
                "total_snoozes": 0,
                "streak_days": 0,
            }
        )["habit_score"]

    def test_snooze_pattern_and_wake_consistency(self, db_session, test_user):
        profile = _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
            wake_up_consistency_score=70.0,
            streak_days=5,
            total_alarms_dismissed=5,
            total_snoozes=3,
        )
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)

        # Three on-time wakes (~07:00) and one late wake
        for i, (hour, minute, snoozes) in enumerate(
            [(7, 0, 0), (7, 5, 1), (7, 10, 0), (8, 30, 2)]
        ):
            day = now - timedelta(days=i + 1)
            dismissed = day.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            _add_wake(
                db_session,
                test_user.id,
                alarm.id,
                dismissed,
                snoozes=snoozes,
            )
            for n in range(1, snoozes + 1):
                _add_snooze(
                    db_session,
                    test_user.id,
                    alarm.id,
                    dismissed - timedelta(minutes=5 * n),
                    snooze_number=n,
                )

        overview = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=30
        )
        snooze = overview["snooze_pattern"]
        wake = overview["wake_up_consistency"]
        sleep = overview["sleep_schedule_adherence"]

        assert snooze["total_snoozes"] == 3  # 1 + 2
        assert snooze["avg_snoozes_per_wake"] > 0
        assert len(snooze["by_hour"]) == 24
        assert len(snooze["by_weekday"]) == 7

        assert wake["verified_wakes"] == 4
        assert wake["consistency_score"] >= 0
        assert wake["std_wake_minutes"] is not None
        assert wake["on_time_rate"] > 0
        assert wake["rolling_profile_score"] == 70.0
        assert wake["preferred_wake_time"] == "07:00"

        assert sleep["suggested_bedtime"] == "23:00"
        assert sleep["observed_days"] == 4
        assert sleep["adherence_rate"] > 0
        assert sleep["profile_streak_days"] == 5
        assert overview["insights"]

    def test_habit_trends_use_ssot_formula(self, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            wake_up_consistency_score=80.0,
            total_alarms_dismissed=8,
            total_snoozes=2,
            streak_days=15,
        )
        overview = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=30
        )
        expected = calculate_habit_score(
            {
                "wake_up_consistency_score": 80.0,
                "total_alarms_dismissed": 8,
                "total_snoozes": 2,
                "streak_days": 15,
            }
        )
        assert overview["habit_trends"]["current_habit_score"] == expected["habit_score"]
        assert overview["habit_trends"]["current_breakdown"] == expected["breakdown"]

    def test_numpy_helpers(self):
        deltas = BehavioralAnalyticsService._circular_minute_delta(
            np.array([7 * 60, 23 * 60]), 0.0
        )
        assert abs(deltas[0] - 420) < 1e-6
        # 23:00 vs midnight → -60 minutes
        assert abs(deltas[1] - (-60)) < 1e-6
        assert BehavioralAnalyticsService._minutes_to_hhmm(7 * 60 + 5) == "07:05"
        assert (
            BehavioralAnalyticsService._compare_trend(10, 20, lower_is_better=True)
            == "improving"
        )

    def test_snooze_limit_hit_rate_hand_check(self, db_session, test_user):
        """limit_hit_rate = (hits / total_snoozes) * 100 with known fixture."""
        _ensure_profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)
        # Numbers 1,2,3,3 with limit 3 → 2 hits of 4 = 50%
        for i, number in enumerate([1, 2, 3, 3]):
            _add_snooze(
                db_session,
                test_user.id,
                alarm.id,
                now - timedelta(hours=i + 1),
                snooze_number=number,
                snooze_limit=3,
            )
        overview = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=30
        )
        snooze = overview["snooze_pattern"]
        assert snooze["total_snoozes"] == 4
        assert snooze["limit_hit_count"] == 2
        assert snooze["limit_hit_rate"] == 50.0
        assert snooze["avg_snooze_number"] == 2.25

    def test_wake_consistency_std_formula(self, db_session, test_user):
        """consistency_score = clip(100 - std*(100/60), 0, 100)."""
        _ensure_profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)
        # Distinct calendar days: 07:00, 07:10, 07:20
        for i, minute in enumerate([0, 10, 20]):
            day = now - timedelta(days=i + 1)
            dismissed = day.replace(hour=7, minute=minute, second=0, microsecond=0)
            _add_wake(db_session, test_user.id, alarm.id, dismissed, snoozes=0)

        overview = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=30
        )
        wake = overview["wake_up_consistency"]
        minutes = np.array([7 * 60, 7 * 60 + 10, 7 * 60 + 20], dtype=float)
        expected_std = float(np.round(float(np.std(minutes)), 2))
        expected_score = float(
            np.round(
                float(np.clip(100.0 - (expected_std * (100.0 / 60.0)), 0.0, 100.0)), 2
            )
        )
        assert wake["verified_wakes"] == 3
        assert wake["std_wake_minutes"] == expected_std
        assert wake["consistency_score"] == expected_score
        # Displayed std must reconstruct the score exactly
        reconstructed = float(
            np.round(
                float(np.clip(100.0 - (expected_std * (100.0 / 60.0)), 0.0, 100.0)), 2
            )
        )
        assert wake["consistency_score"] == reconstructed
        # Preferred 07:00, tolerance 15 → 07:00 & 07:10 on-time, 07:20 late
        assert wake["on_time_count"] == 2
        assert wake["on_time_rate"] == 66.67

    def test_inactive_day_habit_proxy_is_zero(self):
        empty = pd.DataFrame()
        proxy = BehavioralAnalyticsService._daily_habit_proxy(
            empty, empty, empty, preferred_minutes=7 * 60.0
        )
        assert proxy["has_activity"] is False
        assert proxy["habit_score"] == 0.0


class TestBehavioralAnalyticsAPI:
    def test_behavioral_endpoints_require_auth(self, client):
        for path in (
            "/api/v1/analytics/behavioral",
            "/api/v1/analytics/behavioral/snooze",
            "/api/v1/analytics/behavioral/wake-consistency",
            "/api/v1/analytics/behavioral/sleep-adherence",
            "/api/v1/analytics/behavioral/trends/weekly",
            "/api/v1/analytics/behavioral/trends/monthly",
            "/api/v1/analytics/behavioral/habits",
        ):
            assert client.get(path).status_code == 401

    def test_behavioral_overview_api(self, client, auth_headers, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(6, 30),
            sleep_duration_hours=7.5,
        )
        alarm = _make_alarm(db_session, test_user.id)
        dismissed = datetime.now(timezone.utc).replace(
            hour=6, minute=30, second=0, microsecond=0
        ) - timedelta(days=1)
        _add_wake(db_session, test_user.id, alarm.id, dismissed, snoozes=1)
        _add_snooze(
            db_session,
            test_user.id,
            alarm.id,
            dismissed - timedelta(minutes=5),
        )

        res = client.get(
            "/api/v1/analytics/behavioral?days=30", headers=auth_headers
        )
        assert res.status_code == 200
        body = res.json()
        assert "snooze_pattern" in body
        assert "wake_up_consistency" in body
        assert "sleep_schedule_adherence" in body
        assert "weekly_trends" in body
        assert "monthly_trends" in body
        assert "habit_trends" in body
        assert body["snooze_pattern"]["total_snoozes"] == 1
        assert body["wake_up_consistency"]["verified_wakes"] == 1

        # Focused endpoints still work and match overview slices
        snooze = client.get(
            "/api/v1/analytics/behavioral/snooze", headers=auth_headers
        )
        assert snooze.status_code == 200
        assert snooze.json()["total_snoozes"] == 1

        weekly = client.get(
            "/api/v1/analytics/behavioral/trends/weekly", headers=auth_headers
        )
        assert weekly.status_code == 200
        assert weekly.json()["period"] == "week"
        assert len(weekly.json()["series"]) == 7

        habits = client.get(
            "/api/v1/analytics/behavioral/habits", headers=auth_headers
        )
        assert habits.status_code == 200
        assert "current_habit_score" in habits.json()

    def test_existing_ingestion_summary_still_works(
        self, client, auth_headers
    ):
        """Regression: ingestion summary contract must remain intact."""
        res = client.get("/api/v1/analytics/summary", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert "total_events" in body
        assert "by_event_type" in body
