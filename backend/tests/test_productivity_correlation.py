"""Tests for genuine productivity correlation analysis.

Covers the statistical primitives in ``app.services.correlation`` and the
history-driven analyzer that pairs recorded wake/habit behaviour with measured
productivity outcomes. Insufficient-data and no-variance paths must report
their state explicitly rather than emitting a fabricated coefficient.
"""

from datetime import datetime, time, timedelta, timezone

import numpy as np
import pytest

from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services import correlation as corr
from app.services.behavioral_analytics_service import (
    CORRELATION_MIN_PAIRS,
    BehavioralAnalyticsService,
)


# ── Statistical primitives ──────────────────────────────────────────────


class TestCorrelationPrimitives:
    def test_perfect_positive_linear_relationship(self):
        x = [1, 2, 3, 4, 5, 6]
        y = [2, 4, 6, 8, 10, 12]

        result = corr.correlate(x, y)

        assert result["status"] == "ok"
        assert result["n"] == 6
        assert result["pearson_r"] == 1.0
        assert result["spearman_rho"] == 1.0
        assert result["direction"] == "positive"
        assert result["strength"] == "very_strong"
        assert result["significant"] is True
        assert result["p_value"] < 0.05

    def test_perfect_negative_linear_relationship(self):
        x = [1, 2, 3, 4, 5, 6]
        y = [12, 10, 8, 6, 4, 2]

        result = corr.correlate(x, y)

        assert result["pearson_r"] == -1.0
        assert result["direction"] == "negative"
        assert result["significant"] is True

    def test_insufficient_pairs_reports_status_not_a_number(self):
        result = corr.correlate([1, 2, 3], [3, 2, 1], min_pairs=5)

        assert result["status"] == "insufficient_data"
        assert result["n"] == 3
        assert result["min_pairs"] == 5
        assert result["pearson_r"] is None
        assert result["spearman_rho"] is None
        assert result["p_value"] is None
        assert result["significant"] is False
        assert result["strength"] == "undefined"

    def test_constant_series_reports_no_variance(self):
        result = corr.correlate([5, 5, 5, 5, 5, 5], [1, 2, 3, 4, 5, 6])

        assert result["status"] == "no_variance"
        assert result["n"] == 6
        assert result["pearson_r"] is None
        assert result["significant"] is False

    def test_both_series_constant_reports_no_variance(self):
        result = corr.correlate([2] * 6, [9] * 6)

        assert result["status"] == "no_variance"

    def test_missing_values_drop_only_the_affected_pair(self):
        x = [1, 2, None, 4, 5, 6, 7]
        y = [2, 4, 6, 8, None, 12, 14]

        xs, ys = corr.clean_pairs(x, y)

        assert list(xs) == [1.0, 2.0, 4.0, 6.0, 7.0]
        assert list(ys) == [2.0, 4.0, 8.0, 12.0, 14.0]

    def test_nan_pairs_are_excluded_from_n(self):
        x = [1, 2, 3, 4, 5, np.nan]
        y = [1, 2, 3, 4, 5, 6]

        result = corr.correlate(x, y)

        assert result["n"] == 5
        assert result["pearson_r"] == 1.0

    def test_spearman_detects_monotonic_nonlinearity(self):
        x = [1, 2, 3, 4, 5, 6]
        y = [1, 4, 9, 16, 25, 36]

        result = corr.correlate(x, y)

        assert result["spearman_rho"] == 1.0
        assert result["pearson_r"] < 1.0

    def test_weak_relationship_is_not_significant(self):
        x = [1, 2, 3, 4, 5, 6, 7, 8]
        y = [3, 1, 4, 1, 5, 9, 2, 6]

        result = corr.correlate(x, y)

        assert result["status"] == "ok"
        assert result["p_value"] > 0.05
        assert result["significant"] is False

    def test_rank_average_resolves_ties(self):
        ranks = corr.rank_average(np.array([10.0, 20.0, 20.0, 30.0]))

        assert list(ranks) == [1.0, 2.5, 2.5, 4.0]

    def test_p_value_requires_minimum_sample(self):
        assert corr.p_value(0.9, 3) is None
        assert corr.p_value(None, 30) is None
        assert corr.p_value(0.9, 30) < 0.05

    def test_p_value_shrinks_as_sample_grows(self):
        small = corr.p_value(0.5, 8)
        large = corr.p_value(0.5, 80)

        assert large < small

    def test_strength_bands(self):
        assert corr.strength(0.05) == "negligible"
        assert corr.strength(0.3) == "weak"
        assert corr.strength(-0.5) == "moderate"
        assert corr.strength(0.7) == "strong"
        assert corr.strength(-0.95) == "very_strong"
        assert corr.strength(None) == "undefined"

    def test_empty_input_is_safe(self):
        result = corr.correlate([], [])

        assert result["status"] == "insufficient_data"
        assert result["n"] == 0


# ── History-driven analyzer ─────────────────────────────────────────────


def _alarm(db_session, user_id: int) -> Alarm:
    alarm = Alarm(
        user_id=user_id,
        title="Correlation Alarm",
        alarm_time=time(7, 0),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        challenge_count=1,
        challenge_difficulty="medium",
        snooze_limit=5,
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


def _seed_day(
    db_session,
    user,
    alarm,
    day,
    *,
    snoozes: int,
    correct: int,
    attempts: int,
    wakefulness: float = 80.0,
):
    """One recorded day: a verified wake, N snoozes and M challenge attempts."""
    wake_at = datetime.combine(day, time(7, 0))
    db_session.add(
        AlarmWakeEvent(
            user_id=user.id,
            alarm_id=alarm.id,
            triggered_at=wake_at - timedelta(minutes=10),
            dismissed_at=wake_at,
            dismiss_method="challenge",
            snooze_count_at_dismiss=snoozes,
            time_to_dismiss_seconds=600,
            verified=True,
            wakefulness_score=wakefulness,
            wakefulness_level="alert",
        )
    )
    for index in range(snoozes):
        db_session.add(
            AlarmSnoozeEvent(
                user_id=user.id,
                alarm_id=alarm.id,
                snooze_number=index + 1,
                snooze_limit_at_event=5,
                next_trigger_at=wake_at,
                created_at=wake_at - timedelta(minutes=30 - index),
            )
        )
    for index in range(attempts):
        db_session.add(
            AlarmChallengeLog(
                user_id=user.id,
                alarm_id=alarm.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt=f"{day}-{index}",
                is_correct=index < correct,
                time_taken_seconds=10,
                failed_attempts=0,
                points_earned=10 if index < correct else 0,
                created_at=wake_at + timedelta(minutes=index),
            )
        )
    db_session.commit()


def _correlation(db_session, user, days=30):
    return BehavioralAnalyticsService.get_overview(
        db_session, user_id=user.id, days=days
    )["productivity_correlation"]


def _pair(result, pair_id):
    return next(p for p in result["pairs"] if p["id"] == pair_id)


class TestProductivityCorrelationWithRealHistory:
    def test_snoozing_more_tracks_lower_accuracy(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        # Accuracy falls exactly 20pp per extra snooze across 14 recorded days
        for offset in range(1, 15):
            snoozes = offset % 4
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=snoozes,
                correct=5 - snoozes,
                attempts=5,
            )

        result = _correlation(db_session, test_user)
        pair = _pair(result, "snooze_vs_accuracy")

        assert result["status"] == "ok"
        assert result["days_analyzed"] == 14
        assert pair["status"] == "ok"
        assert pair["n"] == 14
        assert pair["pearson_r"] == pytest.approx(-1.0, abs=1e-6)
        assert pair["spearman_rho"] == pytest.approx(-1.0, abs=1e-6)
        assert pair["direction"] == "negative"
        assert pair["strength"] == "very_strong"
        assert pair["significant"] is True
        assert pair["expected_direction"] == "negative"
        assert "snooze_vs_accuracy" in result["significant_findings"]
        assert result["strongest"]["id"] in {p["id"] for p in result["pairs"]}

    def test_method_block_documents_the_statistics_used(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, 9):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset % 3,
                correct=offset % 5,
                attempts=5,
            )

        result = _correlation(db_session, test_user)

        assert result["method"]["coefficients"] == ["pearson", "spearman"]
        assert result["method"]["significance_test"] == "fisher_z"
        assert result["method"]["alpha"] == corr.ALPHA
        assert result["method"]["min_pairs"] == CORRELATION_MIN_PAIRS

    def test_every_declared_pair_is_reported(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, 10):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset % 3,
                correct=offset % 6,
                attempts=5,
            )

        result = _correlation(db_session, test_user)

        ids = [p["id"] for p in result["pairs"]]
        assert len(ids) == len(set(ids))
        assert "habit_vs_accuracy" in ids
        assert "sleep_duration_vs_accuracy" in ids
        for pair in result["pairs"]:
            assert pair["status"] in {"ok", "insufficient_data", "no_variance"}
            assert pair["interpretation"]

    def test_days_without_any_activity_are_not_counted_as_zero(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        # Only 6 active days inside a 30-day window
        for offset in (1, 3, 5, 7, 9, 11):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset % 3,
                correct=offset % 5,
                attempts=5,
            )

        result = _correlation(db_session, test_user, days=30)

        assert result["window_days"] == 30
        assert result["days_analyzed"] == 6
        assert _pair(result, "snooze_vs_accuracy")["n"] == 6


class TestProductivityCorrelationEdgeCases:
    def test_no_history_reports_insufficient_data(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))

        result = _correlation(db_session, test_user)

        assert result["status"] == "insufficient_data"
        assert result["days_analyzed"] == 0
        assert result["significant_findings"] == []
        assert result["strongest"] is None
        assert all(p["status"] == "insufficient_data" for p in result["pairs"])
        assert all(p["pearson_r"] is None for p in result["pairs"])
        assert result["insights"]

    def test_below_min_pairs_reports_insufficient_data(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, CORRELATION_MIN_PAIRS):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset,
                correct=offset,
                attempts=5,
            )

        result = _correlation(db_session, test_user)
        pair = _pair(result, "snooze_vs_accuracy")

        assert result["status"] == "insufficient_data"
        assert pair["status"] == "insufficient_data"
        assert pair["n"] == CORRELATION_MIN_PAIRS - 1
        assert pair["pearson_r"] is None
        assert str(CORRELATION_MIN_PAIRS) in pair["interpretation"]

    def test_constant_behaviour_reports_no_variance(self, db_session, test_user):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        # Snoozes never change; accuracy does
        for offset in range(1, 11):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=0,
                correct=offset % 6,
                attempts=5,
            )

        result = _correlation(db_session, test_user)
        pair = _pair(result, "snooze_vs_accuracy")

        assert pair["status"] == "no_variance"
        assert pair["n"] == 10
        assert pair["pearson_r"] is None
        assert pair["significant"] is False
        assert "never changed" in pair["interpretation"]

    def test_missing_sleep_history_leaves_sleep_pairs_unmeasured(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, 11):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset % 3,
                correct=offset % 5,
                attempts=5,
            )

        result = _correlation(db_session, test_user)
        pair = _pair(result, "sleep_duration_vs_accuracy")

        # Challenge attempts sit minutes after the wake, so no session is bounded
        assert pair["status"] == "insufficient_data"
        assert pair["pearson_r"] is None

    def test_days_without_challenges_do_not_fabricate_accuracy(
        self, db_session, test_user
    ):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, 9):
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=offset % 3,
                correct=0,
                attempts=0,
            )

        result = _correlation(db_session, test_user)
        pair = _pair(result, "snooze_vs_accuracy")

        assert result["days_analyzed"] == 8
        assert pair["status"] == "insufficient_data"
        assert pair["n"] == 0


class TestProductivityCorrelationAPI:
    def test_endpoint_requires_auth(self, client):
        res = client.get("/api/v1/analytics/behavioral/productivity-correlation")
        assert res.status_code == 401

    def test_endpoint_returns_correlation_payload(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))
        alarm = _alarm(db_session, test_user.id)
        today = datetime.now(timezone.utc).date()
        for offset in range(1, 13):
            snoozes = offset % 4
            _seed_day(
                db_session,
                test_user,
                alarm,
                today - timedelta(days=offset),
                snoozes=snoozes,
                correct=5 - snoozes,
                attempts=5,
            )

        res = client.get(
            "/api/v1/analytics/behavioral/productivity-correlation",
            headers=auth_headers,
            params={"days": 30},
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "ok"
        pair = next(p for p in body["pairs"] if p["id"] == "snooze_vs_accuracy")
        assert pair["pearson_r"] == pytest.approx(-1.0, abs=1e-6)
        assert pair["significant"] is True

    def test_overview_includes_productivity_correlation(
        self, client, auth_headers, db_session, test_user
    ):
        _profile(db_session, test_user.id, preferred_wake_time=time(7, 0))

        res = client.get("/api/v1/analytics/behavioral", headers=auth_headers)

        assert res.status_code == 200, res.text
        assert res.json()["productivity_correlation"]["status"] == "insufficient_data"
