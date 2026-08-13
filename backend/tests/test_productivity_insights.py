"""Regression tests for the productivity scoring formula.

``compute_productivity_insights`` is the productivity-scoring component. These
tests pin its formula and edge cases so the numbers cannot drift silently:

    morning_routine_score     = clean_wakes / verified_wakes * 100
    challenge_accuracy        = correct / attempts * 100
    cognitive_readiness_score = challenge_accuracy * 0.6 + avg_wakefulness * 0.4
    consistency_rate          = active_days / window_days * 100

A "clean" wake is one dismissed with zero snoozes. The habit score carried in
the payload must come from the weighted 35/25/20/20 SSOT, not a local formula.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.dashboard_aggregations import compute_productivity_insights
from app.services.habit_score import (
    HABIT_SCORE_WEIGHTS,
    calculate_habit_score_for_user,
)

# Mirrors the blend inside compute_productivity_insights
READINESS_ACCURACY_WEIGHT = 0.6
READINESS_WAKEFULNESS_WEIGHT = 0.4
NEUTRAL_WAKEFULNESS = 50.0


def _alarm(db_session, user_id: int) -> Alarm:
    alarm = Alarm(
        user_id=user_id,
        title="Productivity Alarm",
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


def _wake(
    db_session,
    user_id,
    alarm_id,
    dismissed_at,
    *,
    snoozes=0,
    verified=True,
    wakefulness=None,
    latency=300,
):
    db_session.add(
        AlarmWakeEvent(
            user_id=user_id,
            alarm_id=alarm_id,
            triggered_at=dismissed_at - timedelta(seconds=latency),
            dismissed_at=dismissed_at,
            dismiss_method="challenge" if verified else "abandoned",
            snooze_count_at_dismiss=snoozes,
            time_to_dismiss_seconds=latency,
            verified=verified,
            wakefulness_score=wakefulness,
            wakefulness_level="alert" if wakefulness else None,
        )
    )
    db_session.commit()


def _challenge(db_session, user_id, alarm_id, created_at, *, correct):
    db_session.add(
        AlarmChallengeLog(
            user_id=user_id,
            alarm_id=alarm_id,
            challenge_type="math",
            difficulty="medium",
            challenge_prompt=f"p-{created_at.isoformat()}-{correct}",
            is_correct=correct,
            time_taken_seconds=12,
            failed_attempts=0,
            points_earned=10 if correct else 0,
            created_at=created_at,
        )
    )
    db_session.commit()


def _yesterday_at(hour: int) -> datetime:
    day = datetime.now(timezone.utc).date() - timedelta(days=1)
    return datetime.combine(day, time(hour, 0))


class TestProductivityScoringFormula:
    def test_morning_routine_score_is_clean_wake_share(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        # 3 clean of 4 verified wakes -> 75%
        for index in range(3):
            _wake(db_session, test_user.id, alarm.id, base - timedelta(days=index))
        _wake(db_session, test_user.id, alarm.id, base - timedelta(days=3), snoozes=2)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["verified_wakes"] == 4
        assert result["morning_routine_score"] == 75.0

    def test_challenge_accuracy_is_correct_share(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(8)
        for index in range(10):
            _challenge(
                db_session,
                test_user.id,
                alarm.id,
                base + timedelta(minutes=index),
                correct=index < 7,
            )

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["challenge_accuracy"] == 70.0

    def test_cognitive_readiness_is_the_documented_blend(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        # Wakefulness scores 50 and 70 -> mean 60
        _wake(db_session, test_user.id, alarm.id, base, wakefulness=50.0)
        _wake(
            db_session,
            test_user.id,
            alarm.id,
            base - timedelta(days=1),
            wakefulness=70.0,
        )
        for index in range(10):
            _challenge(
                db_session,
                test_user.id,
                alarm.id,
                base + timedelta(minutes=index),
                correct=index < 7,
            )

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["avg_wakefulness"] == 60.0
        assert result["challenge_accuracy"] == 70.0
        expected = round(
            70.0 * READINESS_ACCURACY_WEIGHT + 60.0 * READINESS_WAKEFULNESS_WEIGHT, 1
        )
        assert expected == 66.0
        assert result["cognitive_readiness_score"] == expected

    def test_consistency_rate_counts_distinct_active_days(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        # Two wakes on the same day count once
        _wake(db_session, test_user.id, alarm.id, base)
        _wake(db_session, test_user.id, alarm.id, base + timedelta(hours=3))
        _wake(db_session, test_user.id, alarm.id, base - timedelta(days=1))

        result = compute_productivity_insights(db_session, test_user.id, 10)

        assert result["active_days_in_period"] == 2
        assert result["consistency_rate"] == 20.0

    def test_avg_time_to_productive_averages_dismiss_latency(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        _wake(db_session, test_user.id, alarm.id, base, latency=100)
        _wake(db_session, test_user.id, alarm.id, base - timedelta(days=1), latency=300)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["avg_time_to_productive_seconds"] == 200.0

    def test_habit_score_comes_from_the_weighted_ssot(self, db_session, test_user):
        profile = _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        _wake(db_session, test_user.id, alarm.id, _yesterday_at(7))

        result = compute_productivity_insights(db_session, test_user.id, 30)
        expected = calculate_habit_score_for_user(db_session, test_user.id, profile)

        assert result["habit_score"] == expected["habit_score"]
        assert result["habit_score_breakdown"] == expected["breakdown"]
        assert HABIT_SCORE_WEIGHTS == {
            "wake_up_consistency": 0.35,
            "challenge_completion": 0.25,
            "snooze_reduction": 0.20,
            "sleep_adherence": 0.20,
        }


class TestProductivityScoringEdgeCases:
    def test_no_history_returns_neutral_wakefulness_and_zero_scores(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["verified_wakes"] == 0
        assert result["morning_routine_score"] == 0.0
        assert result["challenge_accuracy"] == 0.0
        assert result["avg_wakefulness"] == NEUTRAL_WAKEFULNESS
        # 0 * 0.6 + 50 * 0.4
        assert result["cognitive_readiness_score"] == 20.0
        assert result["consistency_rate"] == 0.0
        assert result["avg_time_to_productive_seconds"] is None
        assert result["trend"]["direction"] == "insufficient_data"

    def test_unverified_wakes_are_excluded(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        _wake(db_session, test_user.id, alarm.id, base)
        _wake(
            db_session,
            test_user.id,
            alarm.id,
            base - timedelta(days=1),
            verified=False,
            snoozes=3,
        )

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["verified_wakes"] == 1
        assert result["morning_routine_score"] == 100.0

    def test_all_wakes_snoozed_gives_zero_routine_score(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        for index in range(3):
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                base - timedelta(days=index),
                snoozes=1,
            )

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["morning_routine_score"] == 0.0

    def test_wakes_without_wakefulness_scores_use_neutral_default(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        _wake(db_session, test_user.id, alarm.id, _yesterday_at(7), wakefulness=None)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["avg_wakefulness"] == NEUTRAL_WAKEFULNESS

    def test_improving_trend_when_recent_half_is_cleaner(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        # Older half all snoozed, recent half all clean
        for index in range(3):
            _wake(db_session, test_user.id, alarm.id, base - timedelta(days=index))
        for index in range(6, 9):
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                base - timedelta(days=index),
                snoozes=2,
            )

        result = compute_productivity_insights(db_session, test_user.id, 10)

        assert result["trend"]["recent_clean_wake_rate"] == 100.0
        assert result["trend"]["previous_clean_wake_rate"] == 0.0
        assert result["trend"]["change"] == 100.0
        assert result["trend"]["direction"] == "improving"

    def test_declining_trend_when_recent_half_is_worse(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        for index in range(3):
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                base - timedelta(days=index),
                snoozes=2,
            )
        for index in range(6, 9):
            _wake(db_session, test_user.id, alarm.id, base - timedelta(days=index))

        result = compute_productivity_insights(db_session, test_user.id, 10)

        assert result["trend"]["change"] == -100.0
        assert result["trend"]["direction"] == "declining"

    def test_stable_trend_within_five_point_band(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        for index in range(3):
            _wake(db_session, test_user.id, alarm.id, base - timedelta(days=index))
        for index in range(6, 9):
            _wake(db_session, test_user.id, alarm.id, base - timedelta(days=index))

        result = compute_productivity_insights(db_session, test_user.id, 10)

        assert result["trend"]["change"] == 0.0
        assert result["trend"]["direction"] == "stable"

    def test_goals_are_normalized_to_a_list(self, db_session, test_user):
        _profile(db_session, test_user.id, productivity_goals="Ship the thing")

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["goals"] == ["Ship the thing"]
        assert result["goals_count"] == 1

    def test_empty_goals_are_safe(self, db_session, test_user):
        _profile(db_session, test_user.id, productivity_goals=None)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["goals"] == []
        assert result["goals_count"] == 0


class TestProductivityImprovement:
    """Improvement is measured on the real productivity scores.

    The headline is cognitive readiness (accuracy 60% / wakefulness 40%), with
    the morning routine score and both inputs reported beside it. A 10-day
    window splits into two 5-day halves.
    """

    def _half(
        self,
        db_session,
        user_id,
        alarm_id,
        day_offsets,
        *,
        wakefulness,
        snoozes,
        correct,
        attempts=4,
    ):
        base = _yesterday_at(7)
        for index, offset in enumerate(day_offsets):
            _wake(
                db_session,
                user_id,
                alarm_id,
                base - timedelta(days=offset),
                snoozes=snoozes,
                wakefulness=wakefulness,
            )
            for attempt in range(attempts if index == 0 else 0):
                _challenge(
                    db_session,
                    user_id,
                    alarm_id,
                    base - timedelta(days=offset, minutes=attempt),
                    correct=attempt < correct,
                )

    RECENT = (0, 1, 2)
    PREVIOUS = (6, 7, 8)

    def _scenario(self, db_session, user, *, recent, previous, days=10):
        _profile(db_session, user.id)
        alarm = _alarm(db_session, user.id)
        self._half(db_session, user.id, alarm.id, self.PREVIOUS, **previous)
        self._half(db_session, user.id, alarm.id, self.RECENT, **recent)
        return compute_productivity_insights(db_session, user.id, days)[
            "productivity_improvement"
        ]

    def test_rising_readiness_is_an_improvement(self, db_session, test_user):
        # previous: 25% accuracy, 40 wakefulness -> 31.0
        # current:  100% accuracy, 90 wakefulness -> 96.0
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 40.0, "snoozes": 2, "correct": 1},
            recent={"wakefulness": 90.0, "snoozes": 0, "correct": 4},
        )

        assert result["status"] == "ok"
        assert result["primary_metric"] == "cognitive_readiness_score"
        assert result["previous"]["cognitive_readiness_score"] == 31.0
        assert result["current"]["cognitive_readiness_score"] == 96.0
        assert result["change"] == 65.0
        assert result["improvement_rate"] == 209.7
        assert result["direction"] == "improving"

    def test_falling_readiness_is_a_decline(self, db_session, test_user):
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 90.0, "snoozes": 0, "correct": 4},
            recent={"wakefulness": 40.0, "snoozes": 2, "correct": 1},
        )

        assert result["status"] == "ok"
        assert result["previous"]["cognitive_readiness_score"] == 96.0
        assert result["current"]["cognitive_readiness_score"] == 31.0
        assert result["change"] == -65.0
        assert result["improvement_rate"] == -67.7
        assert result["direction"] == "declining"

    def test_unchanged_scores_are_stable(self, db_session, test_user):
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 80.0, "snoozes": 0, "correct": 3},
            recent={"wakefulness": 80.0, "snoozes": 0, "correct": 3},
        )

        assert result["status"] == "ok"
        assert result["change"] == 0.0
        assert result["improvement_rate"] == 0.0
        assert result["direction"] == "stable"

    def test_it_is_not_the_clean_wake_proxy(self, db_session, test_user):
        """Clean-wake rate can rise while real productivity falls.

        Every wake in the earlier half was snoozed but the user was alert and
        accurate; every recent wake is snooze-free but groggy and wrong.
        """
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 95.0, "snoozes": 2, "correct": 4},
            recent={"wakefulness": 30.0, "snoozes": 0, "correct": 1},
        )

        assert result["metrics"]["morning_routine_score"]["previous"] == 0.0
        assert result["metrics"]["morning_routine_score"]["current"] == 100.0
        assert result["metrics"]["morning_routine_score"]["change"] == 100.0
        # The headline follows readiness, which collapsed
        assert result["previous"]["cognitive_readiness_score"] == 98.0
        assert result["current"]["cognitive_readiness_score"] == 27.0
        assert result["direction"] == "declining"

    def test_the_old_clean_wake_trend_disagrees_in_that_case(
        self, db_session, test_user
    ):
        """Pins the difference against the metric this replaces."""
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            self.PREVIOUS,
            wakefulness=95.0,
            snoozes=2,
            correct=4,
        )
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            self.RECENT,
            wakefulness=30.0,
            snoozes=0,
            correct=1,
        )

        payload = compute_productivity_insights(db_session, test_user.id, 10)

        assert payload["trend"]["direction"] == "improving"
        assert payload["productivity_improvement"]["direction"] == "declining"

    def test_every_tracked_metric_carries_a_delta(self, db_session, test_user):
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 40.0, "snoozes": 2, "correct": 1},
            recent={"wakefulness": 90.0, "snoozes": 0, "correct": 4},
        )

        for key in (
            "cognitive_readiness_score",
            "morning_routine_score",
            "challenge_accuracy",
            "avg_wakefulness",
        ):
            delta = result["metrics"][key]
            assert delta["change"] == pytest.approx(
                delta["current"] - delta["previous"], abs=0.05
            )
        assert result["metrics"]["challenge_accuracy"]["previous"] == 25.0
        assert result["metrics"]["challenge_accuracy"]["current"] == 100.0
        assert result["metrics"]["avg_wakefulness"]["change"] == 50.0

    def test_periods_are_adjacent_and_equal_length(self, db_session, test_user):
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 80.0, "snoozes": 0, "correct": 3},
            recent={"wakefulness": 80.0, "snoozes": 0, "correct": 3},
        )

        assert result["period_days"] == 5
        assert result["previous_period_end"] == result["current_period_start"]

    def test_too_few_wakes_in_a_half_is_insufficient_data(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            self.PREVIOUS,
            wakefulness=80.0,
            snoozes=0,
            correct=3,
        )
        # A single recent wake is below the minimum sample
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            (1,),
            wakefulness=80.0,
            snoozes=0,
            correct=3,
        )

        result = compute_productivity_insights(db_session, test_user.id, 10)[
            "productivity_improvement"
        ]
        assert result["status"] == "insufficient_data"
        assert result["direction"] == "insufficient_data"
        assert result["change"] is None
        assert result["improvement_rate"] is None
        assert result["current"]["verified_wakes"] == 1
        assert result["min_wakes"] == 2

    def test_no_challenge_attempts_in_a_half_is_insufficient_data(
        self, db_session, test_user
    ):
        """Readiness is 60% accuracy — without attempts it cannot be scored."""
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            self.PREVIOUS,
            wakefulness=80.0,
            snoozes=0,
            correct=3,
        )
        self._half(
            db_session,
            test_user.id,
            alarm.id,
            self.RECENT,
            wakefulness=80.0,
            snoozes=0,
            correct=0,
            attempts=0,
        )

        result = compute_productivity_insights(db_session, test_user.id, 10)[
            "productivity_improvement"
        ]
        assert result["status"] == "insufficient_data"
        assert result["current"]["challenge_attempts"] == 0
        assert result["current"]["cognitive_readiness_score"] is None
        assert result["min_attempts"] == 3

    def test_no_history_at_all_is_insufficient_data(self, db_session, test_user):
        _profile(db_session, test_user.id)

        result = compute_productivity_insights(db_session, test_user.id, 30)[
            "productivity_improvement"
        ]
        assert result["status"] == "insufficient_data"
        assert result["previous"]["verified_wakes"] == 0
        assert result["current"]["verified_wakes"] == 0
        assert result["previous"]["cognitive_readiness_score"] is None

    def test_a_zero_baseline_falls_back_to_absolute_points(
        self, db_session, test_user
    ):
        """A ratio is undefined against zero; the point change still is not."""
        result = self._scenario(
            db_session,
            test_user,
            previous={"wakefulness": 0.0, "snoozes": 2, "correct": 0},
            recent={"wakefulness": 80.0, "snoozes": 0, "correct": 4},
        )

        assert result["previous"]["cognitive_readiness_score"] == 0.0
        assert result["improvement_rate"] is None
        assert result["change"] == 92.0
        assert result["direction"] == "improving"


class TestProductivityCorrelationExposure:
    """Correlations ride alongside the composite score; they never replace it."""

    def test_composite_score_is_still_present(self, db_session, test_user):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        _wake(db_session, test_user.id, alarm.id, _yesterday_at(7), wakefulness=80.0)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert "morning_routine_score" in result
        assert "cognitive_readiness_score" in result
        assert "consistency_rate" in result
        assert "habit_score" in result
        assert result["correlations"] is not None
        assert result["sleep_patterns"] is not None

    def test_correlations_report_insufficient_data_without_history(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)

        result = compute_productivity_insights(db_session, test_user.id, 30)

        assert result["correlations"]["status"] == "insufficient_data"
        assert result["sleep_patterns"]["nights_observed"] == 0

    def test_correlations_can_be_disabled_for_report_exports(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        _wake(db_session, test_user.id, alarm.id, _yesterday_at(7))

        result = compute_productivity_insights(
            db_session, test_user.id, 30, include_correlations=False
        )

        assert result["correlations"] is None
        assert result["sleep_patterns"] is None
        # The composite score is unaffected either way
        assert result["morning_routine_score"] == 100.0

    def test_dashboard_endpoint_exposes_correlations(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        for offset in range(12):
            snoozes = offset % 4
            day_wake = base - timedelta(days=offset)
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                day_wake,
                snoozes=snoozes,
                wakefulness=80.0,
            )
            for index in range(5):
                _challenge(
                    db_session,
                    test_user.id,
                    alarm.id,
                    day_wake + timedelta(minutes=index),
                    correct=index < (5 - snoozes),
                )

        res = client.get(
            "/api/v1/dashboard/productivity", headers=auth_headers, params={"days": 30}
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["correlations"]["status"] == "ok"
        pair = next(
            p for p in body["correlations"]["pairs"] if p["id"] == "snooze_vs_accuracy"
        )
        assert pair["pearson_r"] == pytest.approx(-1.0, abs=1e-6)
        assert pair["significant"] is True
        # Composite score untouched
        assert "cognitive_readiness_score" in body
        assert "morning_routine_score" in body


class TestProductivityScoringAPI:
    def test_dashboard_endpoint_exposes_productivity_improvement(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        # Earlier half groggy and inaccurate, recent half alert and accurate.
        for offset, wakefulness, correct in (
            (6, 40.0, 1),
            (7, 40.0, 1),
            (8, 40.0, 1),
            (0, 90.0, 4),
            (1, 90.0, 4),
            (2, 90.0, 4),
        ):
            day_wake = base - timedelta(days=offset)
            _wake(
                db_session,
                test_user.id,
                alarm.id,
                day_wake,
                snoozes=0,
                wakefulness=wakefulness,
            )
            for index in range(4):
                _challenge(
                    db_session,
                    test_user.id,
                    alarm.id,
                    day_wake + timedelta(minutes=index),
                    correct=index < correct,
                )

        res = client.get(
            "/api/v1/dashboard/productivity", headers=auth_headers, params={"days": 10}
        )

        assert res.status_code == 200, res.text
        improvement = res.json()["productivity_improvement"]
        assert improvement["status"] == "ok"
        assert improvement["direction"] == "improving"
        assert improvement["primary_metric"] == "cognitive_readiness_score"
        assert improvement["improvement_rate"] > 0
        assert improvement["metrics"]["avg_wakefulness"]["change"] == 50.0

    def test_dashboard_endpoint_matches_the_service(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id)
        alarm = _alarm(db_session, test_user.id)
        base = _yesterday_at(7)
        _wake(db_session, test_user.id, alarm.id, base, wakefulness=80.0)
        _wake(
            db_session,
            test_user.id,
            alarm.id,
            base - timedelta(days=1),
            snoozes=1,
            wakefulness=60.0,
        )

        res = client.get(
            "/api/v1/dashboard/productivity", headers=auth_headers, params={"days": 30}
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["morning_routine_score"] == 50.0
        assert body["avg_wakefulness"] == 70.0
        # No challenge attempts -> accuracy 0, readiness = 0*0.6 + 70*0.4
        assert body["cognitive_readiness_score"] == 28.0
