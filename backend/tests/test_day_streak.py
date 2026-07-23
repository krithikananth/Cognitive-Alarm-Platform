"""Unit tests for calendar Day Streak semantics."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.day_streak import (
    DayStreakService,
    apply_failed_wake,
    apply_missed_day_decay,
    apply_successful_wake,
    compute_day_streak_from_success_dates,
    local_calendar_date,
)


def test_same_day_does_not_increment():
    state = apply_successful_wake(
        streak_days=3,
        best_streak=5,
        last_successful_wake_date=date(2026, 7, 20),
        wake_date=date(2026, 7, 20),
    )
    assert state.streak_days == 3
    assert state.best_streak == 5
    assert state.changed is False


def test_consecutive_day_increments():
    state = apply_successful_wake(
        streak_days=3,
        best_streak=5,
        last_successful_wake_date=date(2026, 7, 20),
        wake_date=date(2026, 7, 21),
    )
    assert state.streak_days == 4
    assert state.best_streak == 5
    assert state.last_successful_wake_date == date(2026, 7, 21)
    assert state.changed is True


def test_gap_resets_to_one():
    state = apply_successful_wake(
        streak_days=7,
        best_streak=10,
        last_successful_wake_date=date(2026, 7, 18),
        wake_date=date(2026, 7, 21),
    )
    assert state.streak_days == 1
    assert state.best_streak == 10
    assert state.last_successful_wake_date == date(2026, 7, 21)


def test_first_success_starts_at_one():
    state = apply_successful_wake(
        streak_days=0,
        best_streak=0,
        last_successful_wake_date=None,
        wake_date=date(2026, 7, 21),
    )
    assert state.streak_days == 1
    assert state.best_streak == 1


def test_missed_day_decay_resets_live_streak():
    state = apply_missed_day_decay(
        streak_days=4,
        best_streak=9,
        last_successful_wake_date=date(2026, 7, 18),
        today=date(2026, 7, 21),
    )
    assert state.streak_days == 0
    assert state.best_streak == 9
    assert state.last_successful_wake_date == date(2026, 7, 18)
    assert state.changed is True


def test_missed_day_decay_keeps_streak_through_today():
    # Last success yesterday → still alive today.
    state = apply_missed_day_decay(
        streak_days=4,
        best_streak=9,
        last_successful_wake_date=date(2026, 7, 20),
        today=date(2026, 7, 21),
    )
    assert state.streak_days == 4
    assert state.changed is False


def test_compute_from_dates_tracks_best():
    state = compute_day_streak_from_success_dates(
        [
            date(2026, 7, 10),
            date(2026, 7, 11),
            date(2026, 7, 12),
            # gap
            date(2026, 7, 20),
            date(2026, 7, 21),
        ],
        today=date(2026, 7, 21),
    )
    assert state.streak_days == 2
    assert state.best_streak == 3
    assert state.last_successful_wake_date == date(2026, 7, 21)


def test_local_calendar_date_respects_timezone():
    # 2026-07-21 02:00 UTC → still 2026-07-20 in US/Pacific.
    moment = datetime(2026, 7, 21, 2, 0, tzinfo=timezone.utc)
    assert local_calendar_date(moment, "America/Los_Angeles") == date(2026, 7, 20)
    assert local_calendar_date(moment, "UTC") == date(2026, 7, 21)


def test_record_successful_wake_on_profile():
    profile = SimpleNamespace(
        streak_days=2,
        best_streak=2,
        last_successful_wake_date=date(2026, 7, 20),
        timezone="UTC",
    )
    # Same day — no change
    state = DayStreakService.record_successful_wake(
        profile,
        wake_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
    )
    assert state.changed is False
    assert profile.streak_days == 2

    # Next day — increment
    state = DayStreakService.record_successful_wake(
        profile,
        wake_at=datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
    )
    assert state.streak_days == 3
    assert profile.streak_days == 3
    assert profile.last_successful_wake_date == date(2026, 7, 21)


def test_ensure_current_decays_stale_streak():
    profile = SimpleNamespace(
        streak_days=5,
        best_streak=8,
        last_successful_wake_date=date(2026, 7, 10),
        timezone="UTC",
    )
    state = DayStreakService.ensure_current(
        profile, today=date(2026, 7, 21)
    )
    assert state.streak_days == 0
    assert profile.streak_days == 0
    assert profile.best_streak == 8


def test_failed_wake_resets_when_no_success_today():
    state = apply_failed_wake(
        streak_days=4,
        best_streak=9,
        last_successful_wake_date=date(2026, 7, 18),
        outcome_date=date(2026, 7, 21),
    )
    assert state.streak_days == 0
    assert state.best_streak == 9
    assert state.changed is True
    assert state.outcome_applied == "failure"


def test_failed_wake_noop_if_already_succeeded_today():
    state = apply_failed_wake(
        streak_days=4,
        best_streak=9,
        last_successful_wake_date=date(2026, 7, 21),
        outcome_date=date(2026, 7, 21),
    )
    assert state.streak_days == 4
    assert state.changed is False


def test_record_wake_outcome_success_once_per_day():
    profile = SimpleNamespace(
        streak_days=2,
        best_streak=2,
        last_successful_wake_date=date(2026, 7, 20),
        timezone="UTC",
    )
    first = DayStreakService.record_wake_outcome(
        profile,
        outcome="success",
        at=datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
    )
    assert first.streak_days == 3
    assert profile.streak_days == 3

    second = DayStreakService.record_wake_outcome(
        profile,
        outcome="success",
        at=datetime(2026, 7, 21, 8, 30, tzinfo=timezone.utc),
    )
    assert second.changed is False
    assert profile.streak_days == 3


def test_record_wake_outcome_failure_does_not_increment():
    profile = SimpleNamespace(
        streak_days=5,
        best_streak=8,
        last_successful_wake_date=date(2026, 7, 19),
        timezone="UTC",
    )
    state = DayStreakService.record_wake_outcome(
        profile,
        outcome="failure",
        at=datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
    )
    assert state.streak_days == 0
    assert profile.streak_days == 0
    assert profile.best_streak == 8
