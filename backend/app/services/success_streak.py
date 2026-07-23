"""
Success Streak — consecutive successful wake completions.

Success Streak is the number of alarms dismissed in a row after the user
solved the required challenge(s). It is the single source of truth for:

- Adaptive difficulty threshold checks (read-only for the engine)
- Analytics → Personalization "Success streak"
- Profile / habit-score / recommendation surfaces that expose the counter

Rules (final-outcome only):
- Increment by exactly 1 after a successful wake completion (verified dismiss).
- Reset to 0 after a failed wake completion (final failure only).
- Do not update while the alarm is ringing or while the user is snoozing.
- Do not update on mid-cycle wrong answers or timeouts (those only reset
  the in-session consecutive-challenge progress).
- Update at most once per alarm cycle after the final outcome is known.
- Never reset after reaching the adaptive difficulty threshold (e.g. 5);
  the streak keeps climbing until a failure. Watermarks on the profile
  prevent re-firing adapts without mutating this counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.models.profile import UserProfile


@dataclass(frozen=True)
class SuccessStreakState:
    """Immutable snapshot after a Success Streak write."""

    success_streak: int
    failure_streak: int
    changed: bool
    outcome_applied: str  # "success" | "failure" | "noop"


def read_stored_streak(profile: Optional[UserProfile]) -> int:
    """Return the canonical Success Streak from the profile (SSOT)."""
    if profile is None:
        return 0
    return max(0, int(getattr(profile, "consecutive_success_streak", 0) or 0))


def read_failure_streak(profile: Optional[UserProfile]) -> int:
    """Return the canonical Failure Streak from the profile."""
    if profile is None:
        return 0
    return max(0, int(getattr(profile, "consecutive_failure_streak", 0) or 0))


def apply_successful_wake(
    *,
    success_streak: int,
    failure_streak: int,
) -> SuccessStreakState:
    """Pure +1 success / clear failure for one successful wake completion."""
    new_success = max(0, int(success_streak or 0)) + 1
    return SuccessStreakState(
        success_streak=new_success,
        failure_streak=0,
        changed=True,
        outcome_applied="success",
    )


def apply_failed_wake(
    *,
    success_streak: int,
    failure_streak: int,
) -> SuccessStreakState:
    """Pure reset success / +1 failure for one failed wake completion."""
    new_failure = max(0, int(failure_streak or 0)) + 1
    return SuccessStreakState(
        success_streak=0,
        failure_streak=new_failure,
        changed=True,
        outcome_applied="failure",
    )


class SuccessStreakService:
    """Persist Success Streak updates only on final wake outcomes."""

    @staticmethod
    def read_stored_streak(profile: Optional[UserProfile]) -> int:
        return read_stored_streak(profile)

    @staticmethod
    def record_wake_outcome(
        db: Session,
        profile: Optional[UserProfile],
        *,
        completed_wake: bool,
        commit: bool = True,
    ) -> SuccessStreakState:
        """
        Apply exactly one Success Streak update for a final wake outcome.

        ``completed_wake=True`` → increment success by 1, clear failure.
        ``completed_wake=False`` → reset success to 0, increment failure.

        Callers must not invoke this for ring, snooze, or mid-cycle
        wrong/timeout verifies. The adaptive difficulty engine must never
        call this — it only reads the stored counters.
        """
        if profile is None:
            return SuccessStreakState(
                success_streak=0,
                failure_streak=0,
                changed=False,
                outcome_applied="noop",
            )

        if completed_wake:
            state = apply_successful_wake(
                success_streak=int(profile.consecutive_success_streak or 0),
                failure_streak=int(profile.consecutive_failure_streak or 0),
            )
            profile.consecutive_success_streak = state.success_streak
            profile.consecutive_failure_streak = 0
            profile.last_adapted_failure_streak = 0
        else:
            state = apply_failed_wake(
                success_streak=int(profile.consecutive_success_streak or 0),
                failure_streak=int(profile.consecutive_failure_streak or 0),
            )
            profile.consecutive_success_streak = 0
            profile.consecutive_failure_streak = state.failure_streak
            profile.last_adapted_success_streak = 0

        if commit:
            db.commit()
            db.refresh(profile)
        else:
            db.flush()
        return state
