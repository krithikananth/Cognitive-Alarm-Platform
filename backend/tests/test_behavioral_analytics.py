"""Tests for the pandas/numpy Behavioral Analytics module."""

from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

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
    required: int = 1,
    correct: int = None,
    failed: int = 0,
) -> AlarmWakeEvent:
    triggered = dismissed_at - timedelta(minutes=5 + snoozes * 5)
    if correct is None:
        correct = required if verified else 0
    row = AlarmWakeEvent(
        user_id=user_id,
        alarm_id=alarm_id,
        triggered_at=triggered,
        dismissed_at=dismissed_at,
        dismiss_method=method,
        challenges_required=required,
        challenges_completed=correct,
        consecutive_correct=correct,
        failed_attempts=failed,
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


def _snooze_frame(moments) -> pd.DataFrame:
    """Minimal _load_snooze_df-shaped frame for pure-function tests."""
    moments = list(moments)
    return pd.DataFrame(
        {
            "id": range(len(moments)),
            "alarm_id": [1] * len(moments),
            "snooze_number": [1] * len(moments),
            "snooze_limit_at_event": [3] * len(moments),
            "created_at": pd.to_datetime(moments, utc=True),
        }
    )


def _wake_frame(moments) -> pd.DataFrame:
    """Minimal _load_wake_df-shaped frame for pure-function tests."""
    moments = list(moments)
    return pd.DataFrame(
        {
            "id": range(len(moments)),
            "alarm_id": [1] * len(moments),
            "triggered_at": pd.to_datetime(moments, utc=True),
            "verified": [True] * len(moments),
        }
    )


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


class TestSnoozeReduction:
    """reduction_rate = (previous_rate - current_rate) / previous_rate * 100,
    where each rate is snoozes / wake events inside its own period."""

    END = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
    PERIOD = 7

    def _reduce(self, current, previous, *, period_days=PERIOD, end=None):
        """Build frames from (snoozes, wakes) counts per period and analyze."""
        end = end or self.END
        snoozes, wakes = [], []
        for offset, (n_snooze, n_wake) in (
            (timedelta(hours=1), current),
            (timedelta(days=period_days, hours=1), previous),
        ):
            anchor = end - offset
            snoozes += [anchor - timedelta(minutes=i) for i in range(n_snooze)]
            wakes += [anchor - timedelta(minutes=i) for i in range(n_wake)]
        return BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame(snoozes),
            _wake_frame(wakes),
            window_end=end,
            period_days=period_days,
        )

    def test_reduction_rate_is_the_drop_in_snoozes_per_wake(self):
        # previous 8/4 = 2.0 per wake, current 2/4 = 0.5 per wake
        result = self._reduce(current=(2, 4), previous=(8, 4))
        assert result["status"] == "ok"
        assert result["previous_snoozes_per_wake"] == 2.0
        assert result["current_snoozes_per_wake"] == 0.5
        assert result["reduction_rate"] == 75.0
        assert result["absolute_change_per_wake"] == -1.5
        assert result["direction"] == "improving"

    def test_reduction_rate_is_negative_when_snoozing_increases(self):
        # previous 4/4 = 1.0, current 8/4 = 2.0
        result = self._reduce(current=(8, 4), previous=(4, 4))
        assert result["status"] == "ok"
        assert result["reduction_rate"] == -100.0
        assert result["direction"] == "declining"

    def test_fewer_alarms_alone_is_not_counted_as_a_reduction(self):
        """The metric normalises by wake events, so halving both snoozes and
        alarms is 'stable' even though the raw snooze count dropped 50%."""
        result = self._reduce(current=(4, 4), previous=(8, 8))
        assert result["current_snoozes"] == 4
        assert result["previous_snoozes"] == 8
        assert result["current_snoozes_per_wake"] == 1.0
        assert result["previous_snoozes_per_wake"] == 1.0
        assert result["reduction_rate"] == 0.0
        assert result["direction"] == "stable"

    def test_eliminating_snoozing_is_a_full_reduction(self):
        result = self._reduce(current=(0, 3), previous=(6, 3))
        assert result["reduction_rate"] == 100.0
        assert result["current_snoozes_per_wake"] == 0.0
        assert result["direction"] == "improving"

    def test_zero_baseline_with_no_snoozes_has_no_percentage(self):
        result = self._reduce(current=(0, 4), previous=(0, 4))
        assert result["status"] == "no_baseline_snoozes"
        assert result["reduction_rate"] is None
        assert result["absolute_change_per_wake"] == 0.0
        assert result["direction"] == "stable"

    def test_zero_baseline_with_new_snoozing_is_declining(self):
        result = self._reduce(current=(4, 4), previous=(0, 4))
        assert result["status"] == "no_baseline_snoozes"
        assert result["reduction_rate"] is None
        assert result["absolute_change_per_wake"] == 1.0
        assert result["direction"] == "declining"

    @pytest.mark.parametrize(
        "current,previous",
        [((4, 2), (4, 5)), ((4, 5), (4, 2)), ((0, 0), (4, 5))],
    )
    def test_too_few_wakes_in_either_period_is_insufficient_data(
        self, current, previous
    ):
        result = self._reduce(current=current, previous=previous)
        assert result["status"] == "insufficient_data"
        assert result["direction"] == "insufficient_data"
        assert result["reduction_rate"] is None
        assert result["current_snoozes_per_wake"] is None
        assert result["previous_snoozes_per_wake"] is None
        assert result["min_wakes_required"] == 3

    def test_empty_history_is_insufficient_data(self):
        result = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame([]),
            _wake_frame([]),
            window_end=self.END,
            period_days=self.PERIOD,
        )
        assert result["status"] == "insufficient_data"
        assert result["current_snoozes"] == 0
        assert result["previous_wakes"] == 0

    def test_events_outside_the_paired_span_are_ignored(self):
        mid = self.END - timedelta(days=self.PERIOD)
        start = self.END - timedelta(days=2 * self.PERIOD)
        wakes = [mid - timedelta(hours=i) for i in range(3)]
        wakes += [self.END - timedelta(hours=i) for i in range(1, 4)]
        snoozes = [
            start - timedelta(minutes=1),  # older than the baseline period
            self.END + timedelta(minutes=1),  # after the window end
        ]
        result = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame(snoozes),
            _wake_frame(wakes),
            window_end=self.END,
            period_days=self.PERIOD,
        )
        assert result["current_snoozes"] == 0
        assert result["previous_snoozes"] == 0
        assert result["current_wakes"] == 3
        assert result["previous_wakes"] == 3

    def test_period_boundary_is_lower_exclusive_upper_inclusive(self):
        mid = self.END - timedelta(days=self.PERIOD)
        wakes = [mid, self.END] + [
            mid - timedelta(hours=i) for i in range(1, 3)
        ] + [self.END - timedelta(hours=i) for i in range(1, 3)]
        # One snooze exactly on each boundary instant
        result = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame([mid, self.END]),
            _wake_frame(wakes),
            window_end=self.END,
            period_days=self.PERIOD,
        )
        assert result["previous_snoozes"] == 1  # the one at `mid`
        assert result["current_snoozes"] == 1  # the one at `end`
        assert result["previous_wakes"] == 3
        assert result["current_wakes"] == 3

    def test_period_days_is_clamped_to_the_supported_maximum(self):
        result = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame([]), _wake_frame([]), window_end=self.END, period_days=400
        )
        assert result["period_days"] == 90
        assert result["previous_period_start"] == (
            self.END - timedelta(days=180)
        ).isoformat()

    def test_naive_window_end_is_treated_as_utc(self):
        aware = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame([]), _wake_frame([]), window_end=self.END, period_days=7
        )
        naive = BehavioralAnalyticsService.analyze_snooze_reduction(
            _snooze_frame([]),
            _wake_frame([]),
            window_end=self.END.replace(tzinfo=None),
            period_days=7,
        )
        assert naive["current_period_start"] == aware["current_period_start"]

    def test_overview_reads_the_baseline_period_from_stored_events(
        self, db_session, test_user
    ):
        """End to end over real rows: the previous period lies outside the
        requested 7-day window, so it must be loaded separately."""
        _ensure_profile(
            db_session,
            test_user.id,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
        )
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)

        # Previous 7 days: 4 wakes, 8 snoozes → 2.0 per wake
        # Current 7 days:  4 wakes, 2 snoozes → 0.5 per wake
        for day_offset, snoozes in ((8, 2), (9, 2), (10, 2), (11, 2)):
            dismissed = now - timedelta(days=day_offset)
            _add_wake(db_session, test_user.id, alarm.id, dismissed, snoozes=snoozes)
            for n in range(1, snoozes + 1):
                _add_snooze(
                    db_session,
                    test_user.id,
                    alarm.id,
                    dismissed - timedelta(minutes=5 * n),
                    snooze_number=n,
                )
        for day_offset, snoozes in ((1, 1), (2, 1), (3, 0), (4, 0)):
            dismissed = now - timedelta(days=day_offset)
            _add_wake(db_session, test_user.id, alarm.id, dismissed, snoozes=snoozes)
            for n in range(1, snoozes + 1):
                _add_snooze(
                    db_session,
                    test_user.id,
                    alarm.id,
                    dismissed - timedelta(minutes=5 * n),
                    snooze_number=n,
                )

        overview = BehavioralAnalyticsService.get_overview(
            db_session, user_id=test_user.id, days=7
        )
        reduction = overview["snooze_pattern"]["reduction"]

        assert reduction["period_days"] == 7
        assert reduction["previous_snoozes"] == 8
        assert reduction["previous_wakes"] == 4
        assert reduction["current_snoozes"] == 2
        assert reduction["current_wakes"] == 4
        assert reduction["previous_snoozes_per_wake"] == 2.0
        assert reduction["current_snoozes_per_wake"] == 0.5
        assert reduction["reduction_rate"] == 75.0
        assert reduction["direction"] == "improving"
        # Only the current window feeds the existing totals
        assert overview["snooze_pattern"]["total_snoozes"] == 2
        assert any("Snoozes per wake-up are down" in i for i in overview["insights"])


def _decision_frame(rows) -> pd.DataFrame:
    """Frame shaped like _load_wake_df, one row per finished wake cycle.

    Each tuple is ``(verified, challenges_required, consecutive_correct,
    failed_attempts)``.
    """
    rows = list(rows)
    base = datetime(2026, 8, 12, 7, 0, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "id": range(len(rows)),
            "alarm_id": [1] * len(rows),
            "triggered_at": pd.to_datetime(
                [base - timedelta(days=i, minutes=10) for i in range(len(rows))],
                utc=True,
            ),
            "dismissed_at": pd.to_datetime(
                [base - timedelta(days=i) for i in range(len(rows))], utc=True
            ),
            "verified": [r[0] for r in rows],
            "challenges_required": [r[1] for r in rows],
            "consecutive_correct": [r[2] for r in rows],
            "failed_attempts": [r[3] for r in rows],
        }
    )


class TestVerificationAccuracy:
    """accuracy_rate replays each finished cycle against the gate's contract:
    verified <=> consecutive_correct >= challenges_required."""

    def _analyze(self, rows, **kwargs):
        return BehavioralAnalyticsService.analyze_verification_accuracy(
            _decision_frame(rows), **kwargs
        )

    def test_a_gate_that_matches_its_evidence_is_fully_accurate(self):
        result = self._analyze(
            [(True, 1, 1, 0), (True, 2, 2, 0), (False, 2, 1, 3), (False, 1, 0, 2)]
        )
        assert result["status"] == "ok"
        assert result["decisions"] == 4
        assert result["verified"] == 2
        assert result["rejected"] == 2
        assert result["correct_decisions"] == 4
        assert result["accuracy_rate"] == 100.0
        assert result["false_verifications"] == 0
        assert result["missed_verifications"] == 0
        assert result["integrity"] == "consistent"

    def test_releasing_a_user_who_never_met_the_requirement_is_a_false_verification(self):
        result = self._analyze(
            [(True, 3, 1, 0), (True, 1, 1, 0), (True, 1, 1, 0), (False, 1, 0, 1)]
        )
        assert result["false_verifications"] == 1
        assert result["missed_verifications"] == 0
        assert result["correct_decisions"] == 3
        assert result["accuracy_rate"] == 75.0
        assert result["integrity"] == "inconsistent"

    def test_rejecting_a_user_who_did_meet_the_requirement_is_a_missed_verification(self):
        result = self._analyze(
            [(False, 1, 1, 0), (True, 1, 1, 0), (False, 2, 0, 2), (False, 1, 0, 1)]
        )
        assert result["missed_verifications"] == 1
        assert result["false_verifications"] == 0
        assert result["accuracy_rate"] == 75.0
        assert result["integrity"] == "inconsistent"

    def test_it_is_not_the_dismissal_success_rate(self):
        """Every cycle here was rejected, so the dismissal success rate is 0%,
        yet every rejection was the correct call on the evidence held."""
        result = self._analyze([(False, 2, 0, 4), (False, 2, 1, 3), (False, 1, 0, 2)])
        assert result["verified"] == 0
        assert result["rejected"] == 3
        assert result["accuracy_rate"] == 100.0
        assert result["first_pass_rate"] is None
        assert result["avg_answers_per_verification"] is None

    def test_it_is_not_challenge_accuracy(self):
        """Half of these answers were wrong, so challenge accuracy is 50%, but
        the gate still reached the right verdict on every cycle."""
        result = self._analyze(
            [(True, 1, 1, 1), (True, 1, 1, 1), (True, 2, 2, 2), (True, 1, 1, 1)]
        )
        correct_answers = 1 + 1 + 2 + 1
        wrong_answers = 1 + 1 + 2 + 1
        assert correct_answers == wrong_answers  # challenge accuracy would be 50%
        assert result["accuracy_rate"] == 100.0
        assert result["first_pass_rate"] == 0.0

    def test_first_pass_rate_counts_verifications_with_no_wrong_answer(self):
        result = self._analyze(
            [(True, 1, 1, 0), (True, 1, 1, 0), (True, 1, 1, 2), (True, 1, 1, 5)]
        )
        assert result["first_pass_verifications"] == 2
        assert result["first_pass_rate"] == 50.0
        assert result["avg_wrong_answers_per_verification"] == 1.75
        # one answer per correct step plus one per wrong try
        assert result["answers_recorded"] == 4 + 7
        assert result["avg_answers_per_verification"] == 2.75

    def test_unfinished_cycles_are_not_decisions(self):
        frame = _decision_frame([(True, 1, 1, 0)] * 4)
        frame.loc[0, "dismissed_at"] = pd.NaT
        result = BehavioralAnalyticsService.analyze_verification_accuracy(frame)
        assert result["decisions"] == 3

    def test_too_few_cycles_is_insufficient_data(self):
        result = self._analyze([(True, 1, 1, 0), (False, 1, 0, 1)])
        assert result["status"] == "insufficient_data"
        assert result["accuracy_rate"] is None
        assert result["integrity"] == "unknown"
        assert result["min_decisions_required"] == 3
        # counts are still reported so the shortfall is visible
        assert result["decisions"] == 2
        assert result["verified"] == 1

    def test_the_minimum_is_configurable(self):
        rows = [(True, 1, 1, 0), (False, 1, 0, 1)]
        assert self._analyze(rows, min_decisions=2)["status"] == "ok"

    def test_empty_history_is_insufficient_data(self):
        result = BehavioralAnalyticsService.analyze_verification_accuracy(
            _decision_frame([])
        )
        assert result["status"] == "insufficient_data"
        assert result["decisions"] == 0

    def test_a_frame_without_the_verification_columns_does_not_crash(self):
        """Older callers build wake frames with only timing columns."""
        moments = [datetime(2026, 8, 12, 7, 0, tzinfo=timezone.utc)] * 3
        frame = _wake_frame(moments)
        result = BehavioralAnalyticsService.analyze_verification_accuracy(frame)
        assert result["decisions"] == 3
        assert result["status"] == "ok"


class TestBehavioralAnalyticsAPI:
    def test_behavioral_endpoints_require_auth(self, client):
        for path in (
            "/api/v1/analytics/behavioral",
            "/api/v1/analytics/behavioral/snooze",
            "/api/v1/analytics/behavioral/wake-consistency",
            "/api/v1/analytics/behavioral/verification-accuracy",
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
        # The reduction block is part of the documented snooze contract
        reduction = snooze.json()["reduction"]
        assert set(reduction) == {
            "period_days",
            "current_period_start",
            "current_period_end",
            "previous_period_start",
            "previous_period_end",
            "current_snoozes",
            "previous_snoozes",
            "current_wakes",
            "previous_wakes",
            "current_snoozes_per_wake",
            "previous_snoozes_per_wake",
            "absolute_change_per_wake",
            "reduction_rate",
            "direction",
            "status",
            "min_wakes_required",
        }
        assert reduction["status"] == "insufficient_data"
        assert body["snooze_pattern"]["reduction"]["status"] == "insufficient_data"

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

    def test_verification_accuracy_is_read_from_stored_wake_cycles(
        self, client, auth_headers, db_session, test_user
    ):
        alarm = _make_alarm(db_session, test_user.id)
        base = datetime.now(timezone.utc).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
        # Two clean confirmations, one that needed retries, one honest rejection
        _add_wake(db_session, test_user.id, alarm.id, base - timedelta(days=1))
        _add_wake(db_session, test_user.id, alarm.id, base - timedelta(days=2))
        _add_wake(
            db_session, test_user.id, alarm.id, base - timedelta(days=3), failed=2
        )
        _add_wake(
            db_session,
            test_user.id,
            alarm.id,
            base - timedelta(days=4),
            verified=False,
            method="abandoned",
            required=2,
            correct=1,
            failed=3,
        )

        res = client.get(
            "/api/v1/analytics/behavioral/verification-accuracy?days=30",
            headers=auth_headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["decisions"] == 4
        assert body["verified"] == 3
        assert body["rejected"] == 1
        assert body["accuracy_rate"] == 100.0
        assert body["integrity"] == "consistent"
        assert body["false_verifications"] == 0
        assert body["missed_verifications"] == 0
        assert body["first_pass_verifications"] == 2
        assert body["first_pass_rate"] == pytest.approx(66.67, abs=0.01)

        overview = client.get(
            "/api/v1/analytics/behavioral?days=30", headers=auth_headers
        )
        assert overview.status_code == 200
        assert overview.json()["verification_accuracy"] == body

    def test_a_wake_marked_verified_without_the_evidence_is_flagged(
        self, client, auth_headers, db_session, test_user
    ):
        alarm = _make_alarm(db_session, test_user.id)
        base = datetime.now(timezone.utc).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
        for day in (1, 2):
            _add_wake(db_session, test_user.id, alarm.id, base - timedelta(days=day))
        _add_wake(
            db_session,
            test_user.id,
            alarm.id,
            base - timedelta(days=3),
            required=3,
            correct=1,
        )

        res = client.get(
            "/api/v1/analytics/behavioral/verification-accuracy",
            headers=auth_headers,
        )
        body = res.json()
        assert body["false_verifications"] == 1
        assert body["accuracy_rate"] == pytest.approx(66.67, abs=0.01)
        assert body["integrity"] == "inconsistent"

    def test_existing_ingestion_summary_still_works(
        self, client, auth_headers
    ):
        """Regression: ingestion summary contract must remain intact."""
        res = client.get("/api/v1/analytics/summary", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert "total_events" in body
        assert "by_event_type" in body
