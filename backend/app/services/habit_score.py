"""
Single source of truth for Habit Score.

All dashboard, profile, recommendation, and analytics paths must use
``calculate_habit_score`` from this module. Do not reimplement the formula
elsewhere.

When verified wake events are available, input counters are derived by
replaying the same dismiss-path rules used when updating ``UserProfile``.
Otherwise stored profile counters are used (backward compatible).

Habit Score =
    Wake-Up Consistency        × 35%
  + Challenge Completion       × 25%
  + Snooze Reduction           × 20%
  + Sleep Schedule Adherence   × 20%

``challenge_completion`` prefers actual puzzle accuracy from challenge
attempt logs (correct / attempts). When no puzzle attempts are available,
it falls back to the legacy verified-dismiss share of (dismissed + snoozes)
so historical rows and callers without log data keep working.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

from sqlalchemy.orm import Session

from app.models.alarm import AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent
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

# Consistency deltas applied on verified dismiss (mirrors alarms.py)
_CONSISTENCY_CLEAN_WAKE_DELTA = 5.0
_CONSISTENCY_MID_CYCLE_SNOOZE_DELTA = 5.0
_CONSISTENCY_SNOOZE_EXHAUSTED_DELTA = 10.0


def calculate_habit_score(
    profile: Union[UserProfile, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Compute the weighted habit score (0–100) and component breakdown.

    Accepts a ``UserProfile`` ORM instance or a mapping with the same fields
    so callers/tests can pass plain dicts without a DB row.

    ``challenge_completion`` uses puzzle accuracy when
    ``total_puzzle_attempts`` > 0; otherwise the legacy dismiss/snooze share.

    Returns:
        ``{"habit_score": float, "breakdown": {...}, "weights": {...}}``
        matching ``GET /profiles/me/habit-score``.
    """
    wake_up_raw = _field(profile, "wake_up_consistency_score", 0.0)
    dismissed = int(_field(profile, "total_alarms_dismissed", 0) or 0)
    snoozes = int(_field(profile, "total_snoozes", 0) or 0)
    streak_days = int(_field(profile, "streak_days", 0) or 0)
    puzzle_correct = int(_field(profile, "total_puzzle_correct", 0) or 0)
    puzzle_attempts = int(_field(profile, "total_puzzle_attempts", 0) or 0)

    wake_up_score = min(float(wake_up_raw or 0.0), 100.0)

    total_events = dismissed + snoozes
    if puzzle_attempts > 0:
        challenge_score = (puzzle_correct / puzzle_attempts) * 100.0
    elif total_events > 0:
        # Legacy fallback — preserves historical / no-log scoring
        challenge_score = (dismissed / total_events) * 100.0
    else:
        challenge_score = _NEUTRAL_COMPONENT_SCORE

    if total_events > 0:
        snooze_ratio = snoozes / total_events
        snooze_score = max(0.0, (1.0 - snooze_ratio) * 100.0)
    else:
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


def derive_habit_score_inputs_from_events(
    events: Sequence[Union[AlarmWakeEvent, Mapping[str, Any]]],
) -> Dict[str, Any]:
    """Rebuild habit-score input counters from verified wake events.

    Replays the dismiss-path rules from ``alarms.py``:
    - every verified wake increments ``total_alarms_dismissed``
    - ``snooze_count_at_dismiss`` is summed into ``total_snoozes``
    - clean wake (0 snoozes): streak +1, consistency +5 (cap 100)
    - mid-cycle snoozes (1..limit-1): streak reset, consistency −5 (floor 0)
    - snooze-exhausted: streak reset, consistency −10 (floor 0)

    When wake events carry puzzle step snapshots (``challenges_completed`` /
    ``failed_attempts``), also derive ``total_puzzle_*`` so challenge
    completion can use puzzle progress without requiring challenge logs.
    """
    consistency = 0.0
    streak_days = 0
    dismissed = 0
    total_snoozes = 0
    puzzle_correct = 0
    puzzle_attempts = 0

    for event in _iter_verified_events(events):
        dismissed += 1
        snoozes = int(_event_field(event, "snooze_count_at_dismiss", 0) or 0)
        total_snoozes += snoozes
        dismiss_method = _event_field(event, "dismiss_method", None)

        completed = int(_event_field(event, "challenges_completed", 0) or 0)
        failed = int(_event_field(event, "failed_attempts", 0) or 0)
        cycle_attempts = completed + failed
        if cycle_attempts > 0:
            puzzle_correct += completed
            puzzle_attempts += cycle_attempts

        if snoozes == 0:
            streak_days += 1
            consistency = min(
                100.0, consistency + _CONSISTENCY_CLEAN_WAKE_DELTA
            )
        elif dismiss_method == "snooze_exhausted":
            streak_days = 0
            consistency = max(
                0.0, consistency - _CONSISTENCY_SNOOZE_EXHAUSTED_DELTA
            )
        else:
            # Mid-cycle snoozes: still count toward totals, break streak,
            # and apply a milder consistency penalty than limit-exhaustion.
            streak_days = 0
            consistency = max(
                0.0, consistency - _CONSISTENCY_MID_CYCLE_SNOOZE_DELTA
            )

    inputs: Dict[str, Any] = {
        "wake_up_consistency_score": consistency,
        "total_alarms_dismissed": dismissed,
        "total_snoozes": total_snoozes,
        "streak_days": streak_days,
    }
    if puzzle_attempts > 0:
        inputs["total_puzzle_correct"] = puzzle_correct
        inputs["total_puzzle_attempts"] = puzzle_attempts
    return inputs


def resolve_habit_score_inputs(
    profile: Optional[Union[UserProfile, Mapping[str, Any]]],
    events: Optional[Sequence[Union[AlarmWakeEvent, Mapping[str, Any]]]] = None,
) -> Union[UserProfile, Mapping[str, Any]]:
    """Prefer behavioral event-derived inputs when verified wakes exist.

    Falls back to stored profile counters when there is no verified history
    so legacy rows and unit tests that seed counters remain valid.
    """
    if events is not None:
        verified = list(_iter_verified_events(events))
        if verified:
            return derive_habit_score_inputs_from_events(verified)

    if profile is not None:
        return profile

    return {
        "wake_up_consistency_score": 0.0,
        "total_alarms_dismissed": 0,
        "total_snoozes": 0,
        "streak_days": 0,
    }


def load_verified_wake_events(
    db: Session,
    user_id: int,
) -> List[AlarmWakeEvent]:
    """Load lifetime verified wake events for habit-score recalculation."""
    return (
        db.query(AlarmWakeEvent)
        .filter(
            AlarmWakeEvent.user_id == user_id,
            AlarmWakeEvent.verified.is_(True),
        )
        .order_by(
            AlarmWakeEvent.dismissed_at.asc(),
            AlarmWakeEvent.id.asc(),
        )
        .all()
    )


def load_puzzle_attempt_stats(
    db: Session,
    user_id: int,
) -> Dict[str, int]:
    """Aggregate lifetime puzzle attempt accuracy from challenge logs.

    Returns ``{"total_puzzle_correct": int, "total_puzzle_attempts": int}``.
    Empty history yields zeros (caller should then use legacy fallback).
    """
    logs = (
        db.query(AlarmChallengeLog.is_correct)
        .filter(AlarmChallengeLog.user_id == user_id)
        .all()
    )
    attempts = len(logs)
    if attempts == 0:
        return {"total_puzzle_correct": 0, "total_puzzle_attempts": 0}
    correct = sum(1 for (is_correct,) in logs if is_correct)
    return {
        "total_puzzle_correct": correct,
        "total_puzzle_attempts": attempts,
    }


def merge_puzzle_stats(
    inputs: Union[UserProfile, Mapping[str, Any]],
    puzzle_stats: Optional[Mapping[str, Any]] = None,
) -> Mapping[str, Any]:
    """Overlay puzzle attempt stats onto habit-score inputs when present.

    Challenge logs are preferred over wake-event snapshots because they
    record every attempt (including mid-cycle corrects that reset).
    """
    if not puzzle_stats:
        return inputs if isinstance(inputs, Mapping) else {
            "wake_up_consistency_score": _field(inputs, "wake_up_consistency_score", 0.0),
            "total_alarms_dismissed": _field(inputs, "total_alarms_dismissed", 0),
            "total_snoozes": _field(inputs, "total_snoozes", 0),
            "streak_days": _field(inputs, "streak_days", 0),
            "total_puzzle_correct": _field(inputs, "total_puzzle_correct", 0),
            "total_puzzle_attempts": _field(inputs, "total_puzzle_attempts", 0),
        }

    attempts = int(puzzle_stats.get("total_puzzle_attempts", 0) or 0)
    if attempts <= 0:
        return inputs if isinstance(inputs, Mapping) else {
            "wake_up_consistency_score": _field(inputs, "wake_up_consistency_score", 0.0),
            "total_alarms_dismissed": _field(inputs, "total_alarms_dismissed", 0),
            "total_snoozes": _field(inputs, "total_snoozes", 0),
            "streak_days": _field(inputs, "streak_days", 0),
        }

    base: Dict[str, Any]
    if isinstance(inputs, Mapping):
        base = dict(inputs)
    else:
        base = {
            "wake_up_consistency_score": _field(inputs, "wake_up_consistency_score", 0.0),
            "total_alarms_dismissed": _field(inputs, "total_alarms_dismissed", 0),
            "total_snoozes": _field(inputs, "total_snoozes", 0),
            "streak_days": _field(inputs, "streak_days", 0),
        }
    base["total_puzzle_correct"] = int(
        puzzle_stats.get("total_puzzle_correct", 0) or 0
    )
    base["total_puzzle_attempts"] = attempts
    return base


def calculate_habit_score_for_user(
    db: Session,
    user_id: int,
    profile: Optional[Union[UserProfile, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Recalculate habit score from behavioral data when available.

    Response shape matches ``calculate_habit_score`` / habit-score API.
    Challenge completion uses challenge-log accuracy when logs exist.
    """
    events = load_verified_wake_events(db, user_id)
    inputs = resolve_habit_score_inputs(profile, events)
    puzzle_stats = load_puzzle_attempt_stats(db, user_id)
    inputs = merge_puzzle_stats(inputs, puzzle_stats)
    return calculate_habit_score(inputs)


def calculate_habit_score_with_events(
    profile: Optional[Union[UserProfile, Mapping[str, Any]]],
    events: Optional[Sequence[Union[AlarmWakeEvent, Mapping[str, Any]]]] = None,
    puzzle_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Score using in-memory wake events (or profile fallback).

    Optional ``puzzle_stats`` overlays challenge-log accuracy when the
    caller already loaded logs (same shape as ``load_puzzle_attempt_stats``).
    """
    inputs = resolve_habit_score_inputs(profile, events)
    inputs = merge_puzzle_stats(inputs, puzzle_stats)
    return calculate_habit_score(inputs)


def _iter_verified_events(
    events: Iterable[Union[AlarmWakeEvent, Mapping[str, Any]]],
) -> Iterable[Union[AlarmWakeEvent, Mapping[str, Any]]]:
    for event in events:
        if bool(_event_field(event, "verified", False)):
            yield event


def _event_field(
    event: Union[AlarmWakeEvent, Mapping[str, Any]],
    name: str,
    default: Any,
) -> Any:
    if isinstance(event, Mapping):
        return event.get(name, default)
    return getattr(event, name, default)


def _field(
    profile: Union[UserProfile, Mapping[str, Any]],
    name: str,
    default: Any,
) -> Any:
    if isinstance(profile, Mapping):
        return profile.get(name, default)
    return getattr(profile, name, default)
