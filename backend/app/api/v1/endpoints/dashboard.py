"""
Dashboard Aggregation API endpoints.

Provides consolidated, single-call endpoints for the frontend dashboard.
All data is aggregated from existing SSOT tables and services — no new
data stores or duplicate calculations are introduced.

Endpoints:
    GET /dashboard/summary            — unified dashboard payload
    GET /dashboard/alarm-history      — chronological alarm activity timeline
    GET /dashboard/wake-stats         — wake-up statistics aggregation
    GET /dashboard/challenge-performance — challenge performance summary
    GET /dashboard/productivity       — productivity insights from wake behavior
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.models.user import User
from app.services.dashboard_aggregations import (
    compute_challenge_performance,
    compute_productivity_insights,
    compute_wake_stats,
    get_or_create_profile as _get_or_create_profile,
    lookback_start as _lookback_start,
    utc_isoformat as _utc_isoformat,
)
from app.services.day_streak import DayStreakService
from app.services.habit_score import calculate_habit_score_for_user

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _weekly_tracker(db: Session, user_id: int) -> list:
    """Build a simple 7-day on-time tracker from challenge logs."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    logs = (
        db.query(AlarmChallengeLog)
        .filter(
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= start,
            AlarmChallengeLog.is_correct == True,  # noqa: E712
        )
        .all()
    )
    by_day = {i: "pending" for i in range(7)}
    for log in logs:
        created = log.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day_idx = (created.date() - start.date()).days
        if 0 <= day_idx <= 6:
            by_day[day_idx] = "on_time"
    return [
        {
            "day": (start + timedelta(days=i)).strftime("%a").upper()[:3],
            "status": by_day[i],
        }
        for i in range(7)
    ]


# ── 1. GET /dashboard/summary ───────────────────────────────────────────


@router.get(
    "/summary",
    summary="Unified dashboard summary",
)
def get_dashboard_summary(
    period: str = Query(
        "weekly",
        description="Aggregation period: daily, weekly, or monthly",
        pattern="^(daily|weekly|monthly)$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single-call aggregated dashboard combining profile stats, habit score,
    challenge performance snapshot, upcoming alarms, and recent activity.

    The ``period`` parameter controls the lookback window:
    - ``daily``  → last 1 day
    - ``weekly`` → last 7 days (default)
    - ``monthly`` → last 30 days
    """
    period_days = {"daily": 1, "weekly": 7, "monthly": 30}
    days = period_days.get(period, 7)
    cutoff = _lookback_start(days)
    now = datetime.now(timezone.utc)

    profile = _get_or_create_profile(current_user.id, db)
    current_streak = DayStreakService.read_stored_streak(
        profile, db=db, commit=True
    )

    # Habit score (reuses canonical service — no duplicate formula)
    habit_data = calculate_habit_score_for_user(db, current_user.id, profile)

    # Active alarms count
    active_alarms = (
        db.query(func.count(Alarm.id))
        .filter(
            Alarm.user_id == current_user.id,
            Alarm.is_active == True,  # noqa: E712
        )
        .scalar()
        or 0
    )

    # Upcoming alarms (next 24h)
    upcoming_cutoff = now + timedelta(hours=24)
    upcoming = (
        db.query(Alarm)
        .filter(
            Alarm.user_id == current_user.id,
            Alarm.is_active == True,  # noqa: E712
            Alarm.next_trigger_at != None,  # noqa: E711
            Alarm.next_trigger_at >= now,
            Alarm.next_trigger_at <= upcoming_cutoff,
        )
        .order_by(Alarm.next_trigger_at)
        .limit(5)
        .all()
    )

    # Wake events in period
    wake_events = (
        db.query(AlarmWakeEvent)
        .filter(
            AlarmWakeEvent.user_id == current_user.id,
            AlarmWakeEvent.dismissed_at >= cutoff,
        )
        .all()
    )
    verified_wakes = [e for e in wake_events if e.verified]
    abandoned_wakes = [e for e in wake_events if not e.verified]

    # Challenge logs in period
    challenge_logs = (
        db.query(AlarmChallengeLog)
        .filter(
            AlarmChallengeLog.user_id == current_user.id,
            AlarmChallengeLog.created_at >= cutoff,
        )
        .all()
    )
    total_attempts = len(challenge_logs)
    correct_attempts = sum(1 for l in challenge_logs if l.is_correct)
    period_accuracy = (
        round((correct_attempts / total_attempts) * 100, 1)
        if total_attempts > 0
        else 0.0
    )

    # Snooze events in period
    snooze_count = (
        db.query(func.count(AlarmSnoozeEvent.id))
        .filter(
            AlarmSnoozeEvent.user_id == current_user.id,
            AlarmSnoozeEvent.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

    # Success rate
    total_outcomes = len(verified_wakes) + len(abandoned_wakes)
    success_rate = (
        round((len(verified_wakes) / total_outcomes) * 100, 1)
        if total_outcomes > 0
        else 0.0
    )

    # Average time to dismiss
    dismiss_times = [
        e.time_to_dismiss_seconds
        for e in verified_wakes
        if e.time_to_dismiss_seconds is not None
    ]
    avg_dismiss_seconds = (
        round(sum(dismiss_times) / len(dismiss_times), 1)
        if dismiss_times
        else None
    )

    # Total points in period
    total_points = sum(l.points_earned for l in challenge_logs)

    # Weekly tracker
    tracker = _weekly_tracker(db, current_user.id)
    weekly_on_time = sum(1 for d in tracker if d["status"] == "on_time")

    wake = profile.preferred_wake_time

    return {
        "period": period,
        "period_days": days,
        "generated_at": now.isoformat(),
        # Profile stats
        "active_alarms": active_alarms,
        "current_habit_score": habit_data["habit_score"],
        "habit_score_breakdown": habit_data["breakdown"],
        "current_streak": current_streak,
        "best_streak": int(profile.best_streak or 0),
        "success_streak": int(profile.consecutive_success_streak or 0),
        "failure_streak": int(profile.consecutive_failure_streak or 0),
        "preferred_wakeup_time": (
            wake.strftime("%H:%M:%S") if wake else None
        ),
        # Period performance
        "period_stats": {
            "verified_wakes": len(verified_wakes),
            "abandoned_wakes": len(abandoned_wakes),
            "success_rate": success_rate,
            "total_snoozes": snooze_count,
            "challenge_attempts": total_attempts,
            "challenge_accuracy": period_accuracy,
            "total_points_earned": total_points,
            "avg_dismiss_seconds": avg_dismiss_seconds,
        },
        # Weekly tracker (always 7-day, regardless of period)
        "weekly_on_time": weekly_on_time,
        "weekly_total": 7,
        "weekly_tracker": tracker,
        # Upcoming alarms
        "upcoming_alarms": [
            {
                "id": a.id,
                "title": a.title or a.label or "Alarm",
                "alarm_time": str(a.alarm_time)[:5] if a.alarm_time else None,
                "alarm_type": a.alarm_type.value if a.alarm_type else None,
                "challenge_type": (
                    a.challenge_type.value if a.challenge_type else None
                ),
                "next_trigger_at": _utc_isoformat(a.next_trigger_at),
            }
            for a in upcoming
        ],
        # Last successful wake
        "last_successful_wake_date": (
            profile.last_successful_wake_date.isoformat()
            if profile.last_successful_wake_date
            else None
        ),
    }


# ── 2. GET /dashboard/alarm-history ─────────────────────────────────────


@router.get(
    "/alarm-history",
    summary="Paginated alarm activity timeline",
)
def get_alarm_history(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chronological alarm activity timeline merging wake events and snooze
    events into a unified feed.

    Each entry includes a ``event_type`` of ``dismissed``, ``abandoned``,
    or ``snoozed`` along with relevant details.
    """
    cutoff = _lookback_start(days)

    # Wake events (both verified dismissals and abandoned cycles)
    wake_events = (
        db.query(AlarmWakeEvent)
        .filter(
            AlarmWakeEvent.user_id == current_user.id,
            AlarmWakeEvent.dismissed_at >= cutoff,
        )
        .all()
    )

    # Snooze events
    snooze_events = (
        db.query(AlarmSnoozeEvent)
        .filter(
            AlarmSnoozeEvent.user_id == current_user.id,
            AlarmSnoozeEvent.created_at >= cutoff,
        )
        .all()
    )

    # Merge into unified timeline
    timeline = []

    for e in wake_events:
        event_type = "dismissed" if e.verified else "abandoned"
        timeline.append({
            "id": f"wake-{e.id}",
            "alarm_id": e.alarm_id,
            "event_type": event_type,
            "timestamp": _utc_isoformat(e.dismissed_at),
            "details": {
                "dismiss_method": e.dismiss_method,
                "challenges_required": e.challenges_required,
                "challenges_completed": e.challenges_completed,
                "failed_attempts": e.failed_attempts,
                "snooze_count": e.snooze_count_at_dismiss,
                "time_to_dismiss_seconds": e.time_to_dismiss_seconds,
                "wakefulness_score": e.wakefulness_score,
                "wakefulness_level": e.wakefulness_level,
                "verified": e.verified,
            },
        })

    for e in snooze_events:
        timeline.append({
            "id": f"snooze-{e.id}",
            "alarm_id": e.alarm_id,
            "event_type": "snoozed",
            "timestamp": _utc_isoformat(e.created_at),
            "details": {
                "snooze_number": e.snooze_number,
                "snooze_limit": e.snooze_limit_at_event,
                "next_trigger_at": _utc_isoformat(e.next_trigger_at),
            },
        })

    # Sort newest first
    timeline.sort(key=lambda x: x["timestamp"] or "", reverse=True)

    total = len(timeline)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = timeline[start_idx:end_idx]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "days": days,
        "events": page_items,
    }


# ── 3. GET /dashboard/wake-stats ────────────────────────────────────────


@router.get(
    "/wake-stats",
    summary="Wake-up statistics aggregation",
)
def get_wake_stats(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated wake-up statistics including average time to dismiss,
    on-time percentage, distribution by hour and weekday, and first-try
    success rate.

    Queries existing ``alarm_wake_events`` — no duplicate calculations.
    """
    return compute_wake_stats(db, current_user.id, days)


# ── 4. GET /dashboard/challenge-performance ─────────────────────────────


@router.get(
    "/challenge-performance",
    summary="Challenge performance dashboard summary",
)
def get_challenge_performance(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Challenge performance summary for the dashboard, including recent vs
    previous period comparison, best/worst types, and improvement trajectory.

    Aggregates existing ``alarm_challenge_logs`` — no duplication with
    ``/alarms/challenge/stats`` (which is lifetime, not period-based).
    """
    return compute_challenge_performance(db, current_user.id, days)


# ── 5. GET /dashboard/productivity ──────────────────────────────────────


@router.get(
    "/productivity",
    summary="Productivity insights from wake behavior",
)
def get_productivity_insights(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Productivity insights derived from wake behavior, challenge performance,
    and user goals. Computes morning routine consistency, cognitive readiness,
    and goal adherence metrics.

    All data is aggregated from existing tables — no new calculations or
    duplicate logic.
    """
    return compute_productivity_insights(db, current_user.id, days)
