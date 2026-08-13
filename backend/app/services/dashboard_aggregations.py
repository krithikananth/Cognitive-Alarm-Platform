"""
Shared dashboard aggregation builders.

Extracted from dashboard endpoints so Reports (and other consumers) can reuse
the same wake / challenge / productivity calculations without duplication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.alarm import AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.challenge_delivery_service import ChallengeDeliveryService
from app.services.habit_score import calculate_habit_score_for_user

# ── Productivity improvement ────────────────────────────────────────────
# Improvement is measured on the project's own productivity scores rather
# than on clean-wake rate alone: cognitive readiness leads, with the morning
# routine score and its inputs reported beside it so the headline is never the
# only thing on show.

#: Verified wakes required in each half before the comparison is reported.
PRODUCTIVITY_MIN_WAKES = 2
#: Challenge attempts required in each half — readiness is 60% accuracy.
PRODUCTIVITY_MIN_ATTEMPTS = 3
#: Relative movement smaller than this is noise, not an improvement.
PRODUCTIVITY_TOLERANCE_PCT = 5.0
#: Metric the headline rate is taken from.
PRODUCTIVITY_PRIMARY_METRIC = "cognitive_readiness_score"
#: Scores compared across the two halves.
PRODUCTIVITY_TRACKED_METRICS = (
    "cognitive_readiness_score",
    "morning_routine_score",
    "challenge_accuracy",
    "avg_wakefulness",
)


def _productivity_snapshot(wakes: list, logs: list) -> dict:
    """The project's productivity scores over one slice of history.

    Missing inputs yield ``None`` rather than the neutral defaults the
    whole-window summary uses, so an empty half can never be compared as if it
    had been measured.
    """
    routine = (
        round(sum(1 for e in wakes if e.snooze_count_at_dismiss == 0) / len(wakes) * 100, 1)
        if wakes
        else None
    )
    accuracy = (
        round(sum(1 for l in logs if l.is_correct) / len(logs) * 100, 1)
        if logs
        else None
    )
    scores = [e.wakefulness_score for e in wakes if e.wakefulness_score is not None]
    wakefulness = round(sum(scores) / len(scores), 1) if scores else None
    readiness = (
        round(accuracy * 0.6 + wakefulness * 0.4, 1)
        if accuracy is not None and wakefulness is not None
        else None
    )
    return {
        "verified_wakes": len(wakes),
        "challenge_attempts": len(logs),
        "morning_routine_score": routine,
        "challenge_accuracy": accuracy,
        "avg_wakefulness": wakefulness,
        "cognitive_readiness_score": readiness,
    }


def _metric_delta(previous: Optional[float], current: Optional[float]) -> dict:
    if previous is None or current is None:
        return {"previous": previous, "current": current, "change": None, "change_pct": None}
    change = round(current - previous, 1)
    return {
        "previous": previous,
        "current": current,
        "change": change,
        # Undefined against a zero baseline; the absolute change still stands.
        "change_pct": round((change / previous) * 100, 1) if previous else None,
    }


def _productivity_improvement(
    previous_snapshot: dict,
    current_snapshot: dict,
    *,
    period_days: int,
    previous_start: datetime,
    boundary: datetime,
    current_end: datetime,
) -> dict:
    """Period-over-period movement in the real productivity scores."""
    metrics = {
        key: _metric_delta(previous_snapshot[key], current_snapshot[key])
        for key in PRODUCTIVITY_TRACKED_METRICS
    }
    primary = metrics[PRODUCTIVITY_PRIMARY_METRIC]

    result = {
        "period_days": period_days,
        "current_period_start": boundary.isoformat(),
        "current_period_end": current_end.isoformat(),
        "previous_period_start": previous_start.isoformat(),
        "previous_period_end": boundary.isoformat(),
        "primary_metric": PRODUCTIVITY_PRIMARY_METRIC,
        "min_wakes": PRODUCTIVITY_MIN_WAKES,
        "min_attempts": PRODUCTIVITY_MIN_ATTEMPTS,
        "previous": previous_snapshot,
        "current": current_snapshot,
        "metrics": metrics,
        "change": None,
        "improvement_rate": None,
        "direction": "insufficient_data",
        "status": "insufficient_data",
    }

    measurable = all(
        (
            snapshot["verified_wakes"] >= PRODUCTIVITY_MIN_WAKES
            and snapshot["challenge_attempts"] >= PRODUCTIVITY_MIN_ATTEMPTS
            and snapshot[PRODUCTIVITY_PRIMARY_METRIC] is not None
        )
        for snapshot in (previous_snapshot, current_snapshot)
    )
    if not measurable:
        return result

    change = primary["change"]
    rate = primary["change_pct"]
    # Fall back to points when the baseline was zero and a ratio is undefined.
    movement = rate if rate is not None else change
    if movement > PRODUCTIVITY_TOLERANCE_PCT:
        direction = "improving"
    elif movement < -PRODUCTIVITY_TOLERANCE_PCT:
        direction = "declining"
    else:
        direction = "stable"

    result.update(
        {
            "change": change,
            "improvement_rate": rate,
            "direction": direction,
            "status": "ok",
        }
    )
    return result


def utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a stored (UTC-naive) datetime with an explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def lookback_start(days: int) -> datetime:
    """Return the UTC datetime marking the start of the lookback window.

    ``days=N`` covers N calendar days ending today (inclusive).
    """
    return (
        datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)
    ).replace(hour=0, minute=0, second=0, microsecond=0)


def get_or_create_profile(user_id: int, db: Session) -> UserProfile:
    """Get user profile, creating a default one if none exists."""
    from app.models.profile import DifficultyPreference

    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(
            user_id=user_id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            adapted_difficulty=DifficultyPreference.MEDIUM,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def compute_wake_stats(
    db: Session,
    user_id: int,
    days: int,
    *,
    cutoff: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> dict:
    """Aggregated wake-up statistics for a lookback window."""
    if cutoff is None:
        cutoff = lookback_start(days)

    query = db.query(AlarmWakeEvent).filter(
        AlarmWakeEvent.user_id == user_id,
        AlarmWakeEvent.dismissed_at >= cutoff,
    )
    if window_end is not None:
        end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
        query = query.filter(AlarmWakeEvent.dismissed_at <= end)

    wake_events = query.order_by(AlarmWakeEvent.dismissed_at.desc()).all()

    if not wake_events:
        return {
            "days": days,
            "total_wake_events": 0,
            "verified_wakes": 0,
            "abandoned_wakes": 0,
            "success_rate": 0.0,
            "avg_time_to_dismiss_seconds": None,
            "median_time_to_dismiss_seconds": None,
            "fastest_dismiss_seconds": None,
            "slowest_dismiss_seconds": None,
            "first_try_success_rate": 0.0,
            "avg_snoozes_before_dismiss": 0.0,
            "avg_failed_attempts": 0.0,
            "avg_wakefulness_score": None,
            "by_hour": [],
            "by_weekday": [],
            "by_dismiss_method": {},
        }

    verified = [e for e in wake_events if e.verified]
    abandoned = [e for e in wake_events if not e.verified]

    dismiss_times = sorted([
        e.time_to_dismiss_seconds
        for e in verified
        if e.time_to_dismiss_seconds is not None
    ])

    avg_dismiss = (
        round(sum(dismiss_times) / len(dismiss_times), 1)
        if dismiss_times
        else None
    )
    median_dismiss = None
    if dismiss_times:
        mid = len(dismiss_times) // 2
        if len(dismiss_times) % 2 == 0 and len(dismiss_times) > 1:
            median_dismiss = round(
                (dismiss_times[mid - 1] + dismiss_times[mid]) / 2, 1
            )
        else:
            median_dismiss = float(dismiss_times[mid])

    fastest = min(dismiss_times) if dismiss_times else None
    slowest = max(dismiss_times) if dismiss_times else None

    first_try = [
        e for e in verified
        if e.snooze_count_at_dismiss == 0 and e.failed_attempts == 0
    ]
    first_try_rate = (
        round((len(first_try) / len(verified)) * 100, 1)
        if verified
        else 0.0
    )

    snooze_counts = [e.snooze_count_at_dismiss for e in verified]
    avg_snoozes = (
        round(sum(snooze_counts) / len(snooze_counts), 2)
        if snooze_counts
        else 0.0
    )

    failed_counts = [e.failed_attempts for e in verified]
    avg_failed = (
        round(sum(failed_counts) / len(failed_counts), 2)
        if failed_counts
        else 0.0
    )

    wake_scores = [
        e.wakefulness_score for e in verified
        if e.wakefulness_score is not None
    ]
    avg_wakefulness = (
        round(sum(wake_scores) / len(wake_scores), 1)
        if wake_scores
        else None
    )

    hour_counts: dict = {}
    for e in wake_events:
        if e.dismissed_at:
            dt = e.dismissed_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            hour = dt.hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
    by_hour = [
        {"hour": h, "count": c}
        for h, c in sorted(hour_counts.items())
    ]

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_counts: dict = {}
    for e in wake_events:
        if e.dismissed_at:
            dt = e.dismissed_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            wd = dt.weekday()
            weekday_counts[wd] = weekday_counts.get(wd, 0) + 1
    by_weekday = [
        {
            "weekday": weekday_names[wd],
            "weekday_index": wd,
            "count": weekday_counts.get(wd, 0),
        }
        for wd in range(7)
    ]

    method_counts: dict = {}
    for e in wake_events:
        method = e.dismiss_method or "unknown"
        method_counts[method] = method_counts.get(method, 0) + 1

    total_events = len(wake_events)
    success_rate = (
        round((len(verified) / total_events) * 100, 1)
        if total_events > 0
        else 0.0
    )

    return {
        "days": days,
        "total_wake_events": total_events,
        "verified_wakes": len(verified),
        "abandoned_wakes": len(abandoned),
        "success_rate": success_rate,
        "avg_time_to_dismiss_seconds": avg_dismiss,
        "median_time_to_dismiss_seconds": median_dismiss,
        "fastest_dismiss_seconds": fastest,
        "slowest_dismiss_seconds": slowest,
        "first_try_success_rate": first_try_rate,
        "avg_snoozes_before_dismiss": avg_snoozes,
        "avg_failed_attempts": avg_failed,
        "avg_wakefulness_score": avg_wakefulness,
        "by_hour": by_hour,
        "by_weekday": by_weekday,
        "by_dismiss_method": method_counts,
    }


def compute_challenge_performance(
    db: Session,
    user_id: int,
    days: int,
    *,
    cutoff: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    recent_limit: int = 5,
) -> dict:
    """Challenge performance summary for a period."""
    now = window_end or datetime.now(timezone.utc)
    if cutoff is None:
        cutoff = lookback_start(days)

    half_days = max(1, days // 2)
    mid_cutoff = now - timedelta(days=half_days)

    query = db.query(AlarmChallengeLog).filter(
        AlarmChallengeLog.user_id == user_id,
        AlarmChallengeLog.created_at >= cutoff,
    )
    if window_end is not None:
        end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
        query = query.filter(AlarmChallengeLog.created_at <= end)

    logs = query.order_by(AlarmChallengeLog.created_at.desc()).all()

    # Served-vs-finished lives in challenge_deliveries, not in the attempt log:
    # an unanswered challenge never produces an attempt row.
    completion = ChallengeDeliveryService.compute_completion_stats(
        db, user_id, days, cutoff=cutoff, window_end=window_end
    )

    if not logs:
        return {
            "days": days,
            "total_attempts": 0,
            "correct_answers": 0,
            "accuracy": 0.0,
            "avg_response_time": 0.0,
            "total_points_earned": 0,
            "completion": completion,
            "trend": {
                "direction": "insufficient_data",
                "recent_accuracy": 0.0,
                "previous_accuracy": 0.0,
                "accuracy_change": 0.0,
            },
            "best_type": None,
            "worst_type": None,
            "by_type": {},
            "by_difficulty": {},
            "recent_activity": [],
        }

    total = len(logs)
    correct = sum(1 for l in logs if l.is_correct)
    accuracy = round((correct / total) * 100, 1) if total > 0 else 0.0
    avg_time = round(sum(l.time_taken_seconds for l in logs) / total, 1)
    total_points = sum(l.points_earned for l in logs)

    mid_naive = mid_cutoff.replace(tzinfo=None) if mid_cutoff.tzinfo else mid_cutoff
    recent_logs = [l for l in logs if l.created_at and l.created_at >= mid_naive]
    previous_logs = [l for l in logs if l.created_at and l.created_at < mid_naive]

    recent_correct = sum(1 for l in recent_logs if l.is_correct)
    recent_accuracy = (
        round((recent_correct / len(recent_logs)) * 100, 1)
        if recent_logs
        else 0.0
    )
    previous_correct = sum(1 for l in previous_logs if l.is_correct)
    previous_accuracy = (
        round((previous_correct / len(previous_logs)) * 100, 1)
        if previous_logs
        else 0.0
    )
    accuracy_change = round(recent_accuracy - previous_accuracy, 1)

    if not previous_logs or not recent_logs:
        direction = "insufficient_data"
    elif accuracy_change > 2:
        direction = "improving"
    elif accuracy_change < -2:
        direction = "declining"
    else:
        direction = "stable"

    by_type: dict = {}
    for log in logs:
        ct = log.challenge_type or "unknown"
        if ct not in by_type:
            by_type[ct] = {"total": 0, "correct": 0, "total_time": 0, "points": 0}
        by_type[ct]["total"] += 1
        by_type[ct]["correct"] += 1 if log.is_correct else 0
        by_type[ct]["total_time"] += log.time_taken_seconds
        by_type[ct]["points"] += log.points_earned

    for ct, s in by_type.items():
        s["accuracy"] = (
            round((s["correct"] / s["total"]) * 100, 1)
            if s["total"] > 0
            else 0.0
        )
        s["avg_time"] = (
            round(s["total_time"] / s["total"], 1)
            if s["total"] > 0
            else 0.0
        )
        del s["total_time"]

    qualified = {k: v for k, v in by_type.items() if v["total"] >= 2}
    best_type = None
    worst_type = None
    if qualified:
        best_type = max(qualified, key=lambda k: qualified[k]["accuracy"])
        worst_type = min(qualified, key=lambda k: qualified[k]["accuracy"])

    by_difficulty: dict = {}
    for log in logs:
        diff = log.difficulty or "unknown"
        if diff not in by_difficulty:
            by_difficulty[diff] = {"total": 0, "correct": 0, "total_time": 0}
        by_difficulty[diff]["total"] += 1
        by_difficulty[diff]["correct"] += 1 if log.is_correct else 0
        by_difficulty[diff]["total_time"] += log.time_taken_seconds

    for diff, s in by_difficulty.items():
        s["accuracy"] = (
            round((s["correct"] / s["total"]) * 100, 1)
            if s["total"] > 0
            else 0.0
        )
        s["avg_time"] = (
            round(s["total_time"] / s["total"], 1)
            if s["total"] > 0
            else 0.0
        )
        del s["total_time"]

    recent_activity = [
        {
            "challenge_type": l.challenge_type,
            "difficulty": l.difficulty,
            "is_correct": l.is_correct,
            "time_taken_seconds": l.time_taken_seconds,
            "points_earned": l.points_earned,
            "created_at": utc_isoformat(l.created_at),
        }
        for l in logs[: max(0, recent_limit)]
    ]

    return {
        "days": days,
        "total_attempts": total,
        "correct_answers": correct,
        "accuracy": accuracy,
        "avg_response_time": avg_time,
        "total_points_earned": total_points,
        "completion": completion,
        "trend": {
            "direction": direction,
            "recent_accuracy": recent_accuracy,
            "previous_accuracy": previous_accuracy,
            "accuracy_change": accuracy_change,
        },
        "best_type": best_type,
        "worst_type": worst_type,
        "by_type": by_type,
        "by_difficulty": by_difficulty,
        "recent_activity": recent_activity,
    }


def compute_productivity_insights(
    db: Session,
    user_id: int,
    days: int,
    *,
    cutoff: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    include_correlations: bool = True,
) -> dict:
    """Productivity insights derived from wake behavior and challenges."""
    now = window_end or datetime.now(timezone.utc)
    if cutoff is None:
        cutoff = lookback_start(days)

    profile = get_or_create_profile(user_id, db)
    habit_data = calculate_habit_score_for_user(db, user_id, profile)

    wake_query = db.query(AlarmWakeEvent).filter(
        AlarmWakeEvent.user_id == user_id,
        AlarmWakeEvent.dismissed_at >= cutoff,
        AlarmWakeEvent.verified == True,  # noqa: E712
    )
    challenge_query = db.query(AlarmChallengeLog).filter(
        AlarmChallengeLog.user_id == user_id,
        AlarmChallengeLog.created_at >= cutoff,
    )
    if window_end is not None:
        end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
        wake_query = wake_query.filter(AlarmWakeEvent.dismissed_at <= end)
        challenge_query = challenge_query.filter(AlarmChallengeLog.created_at <= end)

    wake_events = wake_query.order_by(AlarmWakeEvent.dismissed_at.desc()).all()
    challenge_logs = challenge_query.all()

    if wake_events:
        clean_wakes = sum(
            1 for e in wake_events
            if e.snooze_count_at_dismiss == 0
        )
        routine_score = round((clean_wakes / len(wake_events)) * 100, 1)
    else:
        routine_score = 0.0

    challenge_accuracy = 0.0
    if challenge_logs:
        correct = sum(1 for l in challenge_logs if l.is_correct)
        challenge_accuracy = round((correct / len(challenge_logs)) * 100, 1)

    wake_scores = [
        e.wakefulness_score for e in wake_events
        if e.wakefulness_score is not None
    ]
    avg_wakefulness = (
        round(sum(wake_scores) / len(wake_scores), 1)
        if wake_scores
        else 50.0
    )
    cognitive_readiness = round(
        (challenge_accuracy * 0.6 + avg_wakefulness * 0.4), 1
    )

    active_dates = set()
    for e in wake_events:
        if e.dismissed_at:
            dt = e.dismissed_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            active_dates.add(dt.date())
    active_days = len(active_dates)
    consistency_rate = (
        round((active_days / days) * 100, 1)
        if days > 0
        else 0.0
    )

    goals = profile.productivity_goals
    if isinstance(goals, list):
        goals_list = goals
    elif goals:
        goals_list = [goals]
    else:
        goals_list = []

    sleep_patterns = None
    correlations = None
    if include_correlations:
        # Imported here: behavioral analytics imports habit_score, which this
        # module also feeds, so a top-level import would be circular.
        from app.services.behavioral_analytics_service import (
            BehavioralAnalyticsService,
        )

        sleep_patterns, correlations = (
            BehavioralAnalyticsService.sleep_and_correlation_snapshot(
                db, user_id, days, window_end=window_end
            )
        )

    half = max(1, days // 2)
    mid_cutoff = now - timedelta(days=half)
    mid_naive = mid_cutoff.replace(tzinfo=None) if mid_cutoff.tzinfo else mid_cutoff
    recent_wakes = [
        e for e in wake_events
        if e.dismissed_at and e.dismissed_at >= mid_naive
    ]
    previous_wakes = [
        e for e in wake_events
        if e.dismissed_at and e.dismissed_at < mid_naive
    ]

    recent_clean = sum(
        1 for e in recent_wakes
        if e.snooze_count_at_dismiss == 0
    )
    previous_clean = sum(
        1 for e in previous_wakes
        if e.snooze_count_at_dismiss == 0
    )

    recent_rate = (
        round((recent_clean / len(recent_wakes)) * 100, 1)
        if recent_wakes
        else 0.0
    )
    previous_rate = (
        round((previous_clean / len(previous_wakes)) * 100, 1)
        if previous_wakes
        else 0.0
    )
    rate_change = round(recent_rate - previous_rate, 1)

    if not previous_wakes or not recent_wakes:
        trend_direction = "insufficient_data"
    elif rate_change > 5:
        trend_direction = "improving"
    elif rate_change < -5:
        trend_direction = "declining"
    else:
        trend_direction = "stable"

    # Same split applied to the attempt log, so both halves are scored on the
    # rows already loaded above — no extra queries.
    recent_logs = [
        l for l in challenge_logs if l.created_at and l.created_at >= mid_naive
    ]
    previous_logs = [
        l for l in challenge_logs if l.created_at and l.created_at < mid_naive
    ]
    productivity_improvement = _productivity_improvement(
        _productivity_snapshot(previous_wakes, previous_logs),
        _productivity_snapshot(recent_wakes, recent_logs),
        period_days=half,
        previous_start=cutoff,
        boundary=mid_cutoff,
        current_end=now,
    )

    dismiss_times = [
        e.time_to_dismiss_seconds for e in wake_events
        if e.time_to_dismiss_seconds is not None
    ]
    avg_time_to_productive = (
        round(sum(dismiss_times) / len(dismiss_times), 1)
        if dismiss_times
        else None
    )

    return {
        "days": days,
        "generated_at": now.isoformat(),
        "morning_routine_score": routine_score,
        "cognitive_readiness_score": cognitive_readiness,
        "habit_score": habit_data["habit_score"],
        "habit_score_breakdown": habit_data["breakdown"],
        "active_days_in_period": active_days,
        "consistency_rate": consistency_rate,
        "current_streak": int(profile.streak_days or 0),
        "best_streak": int(profile.best_streak or 0),
        "verified_wakes": len(wake_events),
        "challenge_accuracy": challenge_accuracy,
        "avg_wakefulness": avg_wakefulness,
        "avg_time_to_productive_seconds": avg_time_to_productive,
        "productivity_improvement": productivity_improvement,
        "trend": {
            "direction": trend_direction,
            "recent_clean_wake_rate": recent_rate,
            "previous_clean_wake_rate": previous_rate,
            "change": rate_change,
        },
        "goals": goals_list,
        "goals_count": len(goals_list),
        "sleep_patterns": sleep_patterns,
        "correlations": correlations,
    }
