"""Unit tests for Success Streak (consecutive successful wake completions)."""

from app.services.success_streak import (
    SuccessStreakService,
    apply_failed_wake,
    apply_successful_wake,
    read_stored_streak,
)


def test_successful_wake_increments_by_one():
    state = apply_successful_wake(success_streak=4, failure_streak=2)
    assert state.success_streak == 5
    assert state.failure_streak == 0
    assert state.outcome_applied == "success"
    assert state.changed is True


def test_failed_wake_resets_success_and_increments_failure():
    state = apply_failed_wake(success_streak=7, failure_streak=0)
    assert state.success_streak == 0
    assert state.failure_streak == 1
    assert state.outcome_applied == "failure"


def test_success_streak_keeps_climbing_past_threshold():
    """Adaptive threshold must not cap or reset the display streak."""
    streak = 0
    for _ in range(12):
        state = apply_successful_wake(success_streak=streak, failure_streak=0)
        streak = state.success_streak
    assert streak == 12


def test_read_stored_streak_none_safe():
    assert read_stored_streak(None) == 0
    assert SuccessStreakService.read_stored_streak(None) == 0
