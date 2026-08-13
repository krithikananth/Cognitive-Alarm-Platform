"""Tests for observed sleep-pattern analytics.

Sleep sessions are reconstructed from stored history only: a verified wake
event bounds the end of the night and the user's last recorded interaction
bounds the start. Nothing here may fall back to a static profile preference,
so several tests assert that missing evidence yields ``None`` and not a guess.
"""

from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pytest

from app.models.alarm import Alarm, AlarmType, ChallengeType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.profile import UserProfile
from app.services.behavioral_analytics_service import (
    SLEEP_MAX_DURATION_HOURS,
    BehavioralAnalyticsService,
)


def _alarm(db_session, user_id: int) -> Alarm:
    alarm = Alarm(
        user_id=user_id,
        title="Sleep Pattern Alarm",
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


def _profile(db_session, user_id: int, **kwargs) -> UserProfile:
    profile = (
        db_session.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    )
    if profile is None:
        profile = UserProfile(user_id=user_id, **kwargs)
        db_session.add(profile)
    else:
        for key, value in kwargs.items():
            setattr(profile, key, value)
    db_session.commit()
    db_session.refresh(profile)
    return profile


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _wake(db_session, user_id, alarm_id, dismissed_at, *, verified=True, latency=300):
    row = AlarmWakeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        triggered_at=dismissed_at - timedelta(seconds=latency),
        dismissed_at=dismissed_at,
        dismiss_method="challenge" if verified else "abandoned",
        snooze_count_at_dismiss=0,
        time_to_dismiss_seconds=latency,
        verified=verified,
        wakefulness_score=80.0,
        wakefulness_level="alert",
    )
    db_session.add(row)
    db_session.commit()
    return row


def _activity(db_session, user_id, created_at):
    row = AnalyticsEvent(
        user_id=user_id,
        event_type="app.interaction",
        source="client",
        event_data={},
        created_at=created_at,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _seed_nights(db_session, user, *, nights, bedtime_hour=23, wake_hour=7, record_activity=True):
    """Create N consecutive nights ending yesterday. Returns the alarm."""
    alarm = _alarm(db_session, user.id)
    today = _today()
    for offset in range(1, nights + 1):
        day = today - timedelta(days=offset)
        wake_at = datetime.combine(day, time(wake_hour, 0))
        if record_activity:
            bed_day = day - timedelta(days=1) if bedtime_hour >= 12 else day
            _activity(db_session, user.id, datetime.combine(bed_day, time(bedtime_hour, 0)))
        _wake(db_session, user.id, alarm.id, wake_at)
    return alarm


def _analyze(db_session, user, days=30):
    return BehavioralAnalyticsService.get_overview(
        db_session, user_id=user.id, days=days
    )["sleep_patterns"]


class TestSleepPatternReconstruction:
    def test_regular_schedule_measures_real_durations(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0), sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=10)

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 10
        assert result["nights_with_duration"] == 10
        # 23:00 -> 07:00 is exactly 8 hours, measured from stored timestamps
        assert result["avg_sleep_duration_hours"] == 8.0
        assert result["min_sleep_duration_hours"] == 8.0
        assert result["max_sleep_duration_hours"] == 8.0
        assert result["avg_bedtime"] == "23:00"
        assert result["avg_wake_time"] == "07:00"
        assert result["bedtime_coverage_rate"] == 100.0

    def test_perfect_regularity_scores_100(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=8)

        result = _analyze(db_session, test_user)

        assert result["std_sleep_duration_hours"] == 0.0
        assert result["schedule_regularity_score"] == 100.0
        assert result["duration_consistency_score"] == 100.0
        assert result["avg_sleep_debt_hours"] == 0.0

    def test_irregular_schedule_lowers_regularity(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        # Alternating 22:00 and 02:00 bedtimes against a drifting wake time
        for offset in range(1, 11):
            day = today - timedelta(days=offset)
            if offset % 2:
                bedtime = datetime.combine(day - timedelta(days=1), time(22, 0))
                wake_at = datetime.combine(day, time(6, 0))
            else:
                bedtime = datetime.combine(day, time(2, 0))
                wake_at = datetime.combine(day, time(10, 0))
            _activity(db_session, test_user.id, bedtime)
            _wake(db_session, test_user.id, alarm.id, wake_at)

        result = _analyze(db_session, test_user)

        assert result["nights_with_duration"] == 10
        assert result["avg_sleep_duration_hours"] == 8.0
        assert result["std_sleep_duration_hours"] == 0.0
        # Duration is stable but the clock times are not
        assert result["duration_consistency_score"] == 100.0
        assert result["schedule_regularity_score"] < 100.0
        assert result["wake_time_std_minutes"] > 0
        assert result["bedtime_std_minutes"] > 0

    def test_short_and_long_nights_are_counted(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        # 5h, 10h, 8h
        plan = [(2, 7), (21, 7), (23, 7)]
        for offset, (bed_hour, wake_hour) in enumerate(plan, start=1):
            day = today - timedelta(days=offset)
            bed_day = day - timedelta(days=1) if bed_hour >= 12 else day
            _activity(db_session, test_user.id, datetime.combine(bed_day, time(bed_hour, 0)))
            _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(wake_hour, 0)))

        result = _analyze(db_session, test_user)

        durations = sorted(
            n["sleep_duration_hours"] for n in result["nights"] if n["sleep_duration_hours"]
        )
        assert durations == [5.0, 8.0, 10.0]
        assert result["short_sleep_nights"] == 1
        assert result["long_sleep_nights"] == 1

    def test_social_jetlag_from_weekend_shift(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        for offset in range(1, 22):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                # Weekend: 01:00 -> 09:00, mid-sleep 05:00
                _activity(db_session, test_user.id, datetime.combine(day, time(1, 0)))
                _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(9, 0)))
            else:
                # Weekday: 23:00 -> 07:00, mid-sleep 03:00
                _activity(
                    db_session,
                    test_user.id,
                    datetime.combine(day - timedelta(days=1), time(23, 0)),
                )
                _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(7, 0)))

        result = _analyze(db_session, test_user)

        assert result["weekday"]["nights"] > 0
        assert result["weekend"]["nights"] > 0
        assert result["weekday"]["avg_wake_time"] == "07:00"
        assert result["weekend"]["avg_wake_time"] == "09:00"
        assert result["social_jetlag_minutes"] == 120.0

    def test_sleep_debt_reflects_measured_shortfall(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        # 00:00 -> 06:00 is 6 measured hours against an 8h target
        _seed_nights(db_session, test_user, nights=6, bedtime_hour=0, wake_hour=6)

        result = _analyze(db_session, test_user)

        assert result["avg_sleep_duration_hours"] == 6.0
        assert result["target_sleep_hours"] == 8.0
        assert result["avg_sleep_debt_hours"] == 2.0


class TestSleepPatternMissingAndInvalidData:
    def test_no_history_returns_empty_payload_not_defaults(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=7.5)

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 0
        assert result["nights_with_duration"] == 0
        assert result["avg_sleep_duration_hours"] is None
        assert result["avg_bedtime"] is None
        assert result["avg_wake_time"] is None
        assert result["social_jetlag_minutes"] is None
        assert result["avg_sleep_debt_hours"] is None
        assert result["trend"] == "insufficient_data"
        assert result["nights"] == []
        # The profile target is echoed but never used to invent a duration
        assert result["target_sleep_hours"] == 7.5

    def test_wakes_without_activity_report_null_duration(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=5, record_activity=False)

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 5
        assert result["nights_with_duration"] == 0
        assert result["avg_sleep_duration_hours"] is None
        assert result["avg_bedtime"] is None
        assert result["bedtime_coverage_rate"] == 0.0
        # Wake times are still real observations
        assert result["avg_wake_time"] == "07:00"
        assert all(n["sleep_duration_hours"] is None for n in result["nights"])

    def test_activity_too_close_to_wake_is_rejected(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        for offset in range(1, 5):
            day = today - timedelta(days=offset)
            # Only 1h before the wake — the user was clearly already awake
            _activity(db_session, test_user.id, datetime.combine(day, time(6, 0)))
            _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(7, 0)))

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 4
        assert result["nights_with_duration"] == 0

    def test_activity_older_than_max_window_is_rejected(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        day = _today() - timedelta(days=1)
        # The only recorded activity is 3 days stale — an idle gap, not a night
        _activity(
            db_session,
            test_user.id,
            datetime.combine(day - timedelta(days=3), time(23, 0)),
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(7, 0)))

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 1
        assert result["nights_with_duration"] == 0
        assert result["nights"][0]["bedtime"] is None

    def test_unverified_wakes_are_ignored(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        for offset in range(1, 5):
            day = today - timedelta(days=offset)
            _activity(
                db_session,
                test_user.id,
                datetime.combine(day - timedelta(days=1), time(23, 0)),
            )
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                datetime.combine(day, time(7, 0)),
                verified=False,
            )

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 0

    def test_only_first_wake_of_a_day_becomes_the_night(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        day = _today() - timedelta(days=1)
        _activity(
            db_session, test_user.id, datetime.combine(day - timedelta(days=1), time(23, 0))
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(7, 0)))
        # A nap alarm later the same day must not overwrite the night
        _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(14, 0)))

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 1
        assert result["nights"][0]["wake_time"] == "07:00"
        assert result["nights"][0]["sleep_duration_hours"] == 8.0

    def test_missing_profile_falls_back_to_default_target_only(self, db_session, test_user):
        _seed_nights(db_session, test_user, nights=3)

        result = _analyze(db_session, test_user)

        assert result["target_sleep_hours"] == 8.0
        assert result["nights_with_duration"] == 3


class TestCircularClockStatistics:
    def test_circular_mean_crosses_midnight(self):
        # 23:50 and 00:10 average to midnight, not to noon
        minutes = np.array([23 * 60 + 50, 10], dtype=float)
        mean = BehavioralAnalyticsService._circular_mean_minutes(minutes)
        assert mean == pytest.approx(0.0, abs=1e-6) or mean == pytest.approx(1440.0, abs=1e-6)

    def test_circular_std_is_zero_for_identical_times(self):
        minutes = np.array([420.0, 420.0, 420.0])
        assert BehavioralAnalyticsService._circular_std_minutes(minutes) == pytest.approx(
            0.0, abs=1e-6
        )

    def test_circular_helpers_handle_empty_and_nan(self):
        empty = np.array([], dtype=float)
        assert BehavioralAnalyticsService._circular_mean_minutes(empty) is None
        assert BehavioralAnalyticsService._circular_std_minutes(empty) is None

        nans = np.array([np.nan, np.nan])
        assert BehavioralAnalyticsService._circular_mean_minutes(nans) is None
        assert BehavioralAnalyticsService._circular_std_minutes(nans) is None

    def test_circular_std_grows_with_scatter(self):
        tight = np.array([420.0, 425.0, 415.0])
        loose = np.array([300.0, 500.0, 700.0])
        assert BehavioralAnalyticsService._circular_std_minutes(
            tight
        ) < BehavioralAnalyticsService._circular_std_minutes(loose)


class TestRecordedSleepTakesPriority:
    """Explicitly logged sleep must never be replaced by an interaction estimate."""

    def _log_sleep(self, db_session, user_id, moment, event_type):
        row = AnalyticsEvent(
            user_id=user_id,
            event_type=event_type,
            source="client",
            event_data={},
            created_at=moment,
        )
        db_session.add(row)
        db_session.commit()
        return row

    def test_recorded_session_is_used_instead_of_estimate(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        day = _today() - timedelta(days=1)
        # A misleading interaction at 21:00 would estimate a 10h night
        _activity(
            db_session, test_user.id, datetime.combine(day - timedelta(days=1), time(21, 0))
        )
        # The user actually logged going to sleep at 23:00
        self._log_sleep(
            db_session,
            test_user.id,
            datetime.combine(day - timedelta(days=1), time(23, 0)),
            "sleep.started",
        )
        self._log_sleep(
            db_session, test_user.id, datetime.combine(day, time(7, 0)), "sleep.ended"
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(7, 30)))

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 1
        night = result["nights"][0]
        assert night["source"] == "recorded"
        assert night["sleep_end_source"] == "sleep_record"
        assert night["bedtime"] == "23:00"
        assert night["sleep_duration_hours"] == 8.0
        assert result["has_recorded_sleep"] is True
        assert result["nights_recorded"] == 1
        assert result["nights_estimated"] == 0
        assert result["duration_source"] == "recorded"
        assert result["avg_recorded_duration_hours"] == 8.0
        assert result["avg_estimated_duration_hours"] is None

    def test_recorded_start_without_end_closes_on_verified_wake(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        day = _today() - timedelta(days=1)
        self._log_sleep(
            db_session,
            test_user.id,
            datetime.combine(day - timedelta(days=1), time(23, 0)),
            "sleep.started",
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(day, time(6, 0)))

        result = _analyze(db_session, test_user)
        night = result["nights"][0]

        assert night["source"] == "recorded"
        assert night["sleep_end_source"] == "verified_wake"
        assert night["sleep_duration_hours"] == 7.0
        assert result["nights_recorded"] == 1

    def test_recorded_session_without_any_alarm_still_counts(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        day = _today() - timedelta(days=1)
        self._log_sleep(
            db_session,
            test_user.id,
            datetime.combine(day - timedelta(days=1), time(22, 30)),
            "sleep.started",
        )
        self._log_sleep(
            db_session, test_user.id, datetime.combine(day, time(6, 30)), "sleep.ended"
        )

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 1
        assert result["nights_recorded"] == 1
        assert result["nights"][0]["sleep_duration_hours"] == 8.0
        assert result["nights"][0]["wake_latency_seconds"] is None

    def test_mixed_recorded_and_estimated_nights_are_labelled(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        today = _today()
        # Night 1 recorded
        first = today - timedelta(days=1)
        self._log_sleep(
            db_session,
            test_user.id,
            datetime.combine(first - timedelta(days=1), time(23, 0)),
            "sleep.started",
        )
        self._log_sleep(
            db_session, test_user.id, datetime.combine(first, time(7, 0)), "sleep.ended"
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(first, time(7, 0)))
        # Night 2 estimated only
        second = today - timedelta(days=2)
        _activity(
            db_session,
            test_user.id,
            datetime.combine(second - timedelta(days=1), time(22, 0)),
        )
        _wake(db_session, test_user.id, alarm.id, datetime.combine(second, time(6, 0)))

        result = _analyze(db_session, test_user)

        by_source = {n["date"]: n["source"] for n in result["nights"]}
        assert by_source[first.isoformat()] == "recorded"
        assert by_source[second.isoformat()] == "estimated"
        assert result["nights_recorded"] == 1
        assert result["nights_estimated"] == 1
        assert result["duration_source"] == "mixed"
        assert result["avg_recorded_duration_hours"] == 8.0
        assert result["avg_estimated_duration_hours"] == 8.0

    def test_estimated_nights_are_never_labelled_recorded(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=4)

        result = _analyze(db_session, test_user)

        assert result["has_recorded_sleep"] is False
        assert result["nights_recorded"] == 0
        assert result["nights_estimated"] == 4
        assert result["duration_source"] == "estimated"
        assert result["avg_recorded_duration_hours"] is None
        assert all(n["source"] == "estimated" for n in result["nights"])

    def test_backfilled_timestamp_in_event_data_is_honoured(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        day = _today() - timedelta(days=1)
        actual_start = datetime.combine(day - timedelta(days=1), time(23, 0))
        actual_end = datetime.combine(day, time(7, 0))
        # Both logged the next morning, but carry the real instants
        db_session.add(
            AnalyticsEvent(
                user_id=test_user.id,
                event_type="sleep.started",
                source="client",
                event_data={"at": actual_start.replace(tzinfo=timezone.utc).isoformat()},
                created_at=actual_end + timedelta(minutes=5),
            )
        )
        db_session.add(
            AnalyticsEvent(
                user_id=test_user.id,
                event_type="sleep.ended",
                source="client",
                event_data={"at": actual_end.replace(tzinfo=timezone.utc).isoformat()},
                created_at=actual_end + timedelta(minutes=6),
            )
        )
        db_session.commit()

        result = _analyze(db_session, test_user)

        assert result["nights_recorded"] == 1
        assert result["nights"][0]["bedtime"] == "23:00"
        assert result["nights"][0]["sleep_duration_hours"] == 8.0

    def test_implausible_recorded_session_is_rejected(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        day = _today() - timedelta(days=1)
        # 30 minutes is below the 2h floor — not a night
        self._log_sleep(
            db_session, test_user.id, datetime.combine(day, time(6, 0)), "sleep.started"
        )
        self._log_sleep(
            db_session, test_user.id, datetime.combine(day, time(6, 30)), "sleep.ended"
        )

        result = _analyze(db_session, test_user)

        assert result["nights_observed"] == 0
        assert result["has_recorded_sleep"] is False

    def test_sleep_events_are_ingestible_through_the_public_api(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        day = _today() - timedelta(days=1)
        start = datetime.combine(day - timedelta(days=1), time(23, 0)).replace(
            tzinfo=timezone.utc
        )
        end = datetime.combine(day, time(7, 0)).replace(tzinfo=timezone.utc)

        for event_type, moment in (("sleep.started", start), ("sleep.ended", end)):
            res = client.post(
                "/api/v1/analytics/events",
                headers=auth_headers,
                json={
                    "event_type": event_type,
                    "source": "client",
                    "event_data": {"at": moment.isoformat()},
                },
            )
            assert res.status_code in (200, 201), res.text

        res = client.get(
            "/api/v1/analytics/behavioral/sleep-patterns", headers=auth_headers
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["has_recorded_sleep"] is True
        assert body["nights_recorded"] == 1
        assert body["nights"][0]["sleep_duration_hours"] == 8.0


class TestOpenSleepSessionBoundary:
    """``has_open_session`` drives the dashboard's start/end button.

    A logged start with no end stays "open" only while it could still be a
    night in progress — that is, until it ages past SLEEP_MAX_DURATION_HOURS.
    """

    def _start(self, db_session, user_id, moment):
        db_session.add(
            AnalyticsEvent(
                user_id=user_id,
                event_type="sleep.started",
                source="client",
                event_data={},
                created_at=moment,
            )
        )
        db_session.commit()

    def _now(self):
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def test_recent_start_without_end_is_open(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        self._start(db_session, test_user.id, self._now() - timedelta(hours=1))

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is True
        assert result["nights_observed"] == 0

    def test_start_just_inside_the_boundary_is_open(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        self._start(
            db_session,
            test_user.id,
            self._now() - timedelta(hours=SLEEP_MAX_DURATION_HOURS - 1),
        )

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is True

    def test_start_past_the_boundary_is_no_longer_open(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        self._start(
            db_session,
            test_user.id,
            self._now() - timedelta(hours=SLEEP_MAX_DURATION_HOURS + 2),
        )

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is False
        # It never became a night either — nothing closed it
        assert result["nights_observed"] == 0

    def test_a_closed_session_is_not_open(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        now = self._now()
        self._start(db_session, test_user.id, now - timedelta(hours=9))
        db_session.add(
            AnalyticsEvent(
                user_id=test_user.id,
                event_type="sleep.ended",
                source="client",
                event_data={},
                created_at=now - timedelta(hours=1),
            )
        )
        db_session.commit()

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is False
        assert result["nights_recorded"] == 1

    def test_a_start_closed_by_a_verified_wake_is_not_open(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        alarm = _alarm(db_session, test_user.id)
        now = self._now()
        self._start(db_session, test_user.id, now - timedelta(hours=10))
        _wake(db_session, test_user.id, alarm.id, now - timedelta(hours=2))

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is False
        assert result["nights_recorded"] == 1
        assert result["nights"][0]["sleep_end_source"] == "verified_wake"

    def test_no_sleep_records_means_no_open_session(self, db_session, test_user):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=3)

        result = _analyze(db_session, test_user)

        assert result["has_open_session"] is False

    def test_open_session_is_exposed_through_the_api(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        self._start(db_session, test_user.id, self._now() - timedelta(hours=2))

        res = client.get(
            "/api/v1/analytics/behavioral/sleep-patterns", headers=auth_headers
        )

        assert res.status_code == 200, res.text
        assert res.json()["has_open_session"] is True


class TestSleepPatternAPI:
    def test_endpoint_requires_auth(self, client):
        assert client.get("/api/v1/analytics/behavioral/sleep-patterns").status_code == 401

    def test_endpoint_returns_measured_payload(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=6)

        res = client.get(
            "/api/v1/analytics/behavioral/sleep-patterns",
            headers=auth_headers,
            params={"days": 30},
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["nights_observed"] == 6
        assert body["avg_sleep_duration_hours"] == 8.0
        assert body["avg_bedtime"] == "23:00"
        assert len(body["nights"]) == 6

    def test_overview_includes_sleep_patterns(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, sleep_duration_hours=8.0)
        _seed_nights(db_session, test_user, nights=4)

        res = client.get("/api/v1/analytics/behavioral", headers=auth_headers)

        assert res.status_code == 200, res.text
        assert res.json()["sleep_patterns"]["nights_with_duration"] == 4
