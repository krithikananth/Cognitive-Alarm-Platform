"""
Single source of truth for Habit Score.

All dashboard, profile, recommendation, and analytics paths must use
``calculate_habit_score`` from this module. Do not reimplement the formula
elsewhere.

Habit Score =
    Wake-Up Consistency        × 35%
  + Challenge Completion       × 25%
  + Snooze Reduction           × 20%
  + Sleep Schedule Adherence   × 20%

Note: ``challenge_completion`` is the verified-dismiss share of
(dismissed + snoozes), not puzzle-answer accuracy from challenge logs.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Union

from app.models.profile import UserProfile

# Canonical weights — sum to 1.0
WEIGHT_WAKE_UP_CONSISTENCY = 0.35
WEIGHT_CHALLENGE_COMPLETION = 0.25
WEIGHT_SNOOZE_REDUCTION = 0.20
WEIGHT_SLEEP_ADHERENCE = 0.20

HABIT_SCORE_WEIGHTS: Dict[str, float] = {
    "wake_up_consistency": WEIGHT_WAKE_UP_CONSISTENCY,
    "challenge_completion": WEIGHT_CHALLENGE_COMPLETION,
    "snooze_reduction": WEIGHT_SNOOZE_REDUCTION,
    "sleep_adherence": WEIGHT_SLEEP_ADHERENCE,
}

# Streak days that map to 100% sleep-schedule adherence
SLEEP_ADHERENCE_STREAK_TARGET_DAYS = 30

# Neutral component score when the user has no dismiss/snooze history yet
_NEUTRAL_COMPONENT_SCORE = 50.0


def calculate_habit_score(
    profile: Union[UserProfile, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compute the weighted habit score (0–100) and component breakdown.

    Accepts a ``UserProfile`` ORM instance or a mapping with the same fields
    so callers/tests can pass plain dicts without a DB row.

    Returns:
        ``{"habit_score": float, "breakdown": {...}, "weights": {...}}``
        matching ``GET /profiles/me/habit-score``.
    """
    wake_up_raw = _field(profile, "wake_up_consistency_score", 0.0)
    dismissed = int(_field(profile, "total_alarms_dismissed", 0) or 0)
    snoozes = int(_field(profile, "total_snoozes", 0) or 0)
    streak_days = int(_field(profile, "streak_days", 0) or 0)

    wake_up_score = min(float(wake_up_raw or 0.0), 100.0)

    total_events = dismissed + snoozes
    if total_events > 0:
        challenge_score = (dismissed / total_events) * 100.0
        snooze_ratio = snoozes / total_events
        snooze_score = max(0.0, (1.0 - snooze_ratio) * 100.0)
    else:
        challenge_score = _NEUTRAL_COMPONENT_SCORE
        snooze_score = _NEUTRAL_COMPONENT_SCORE

    adherence_score = min(
        (streak_days / SLEEP_ADHERENCE_STREAK_TARGET_DAYS) * 100.0,
        100.0,
    )

    overall = (
        wake_up_score * WEIGHT_WAKE_UP_CONSISTENCY
        + challenge_score * WEIGHT_CHALLENGE_COMPLETION
        + snooze_score * WEIGHT_SNOOZE_REDUCTION
        + adherence_score * WEIGHT_SLEEP_ADHERENCE
    )
    habit_score = round(min(overall, 100.0), 2)

    return {
        "habit_score": habit_score,
        "breakdown": {
            "wake_up_consistency": round(wake_up_score, 2),
            "challenge_completion": round(challenge_score, 2),
            "snooze_reduction": round(snooze_score, 2),
            "sleep_adherence": round(adherence_score, 2),
        },
        "weights": dict(HABIT_SCORE_WEIGHTS),
    }


def _field(
    profile: Union[UserProfile, Mapping[str, Any]],
    name: str,
    default: Any,
) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(name, default)
    return getattr(profile, name, default)
