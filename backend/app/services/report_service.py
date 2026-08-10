"""
User lifestyle Reports — reuse analytics / dashboard calculations.

Report types:
  - habit
  - wake
  - challenge
  - productivity
  - sleep
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.behavioral_analytics_service import BehavioralAnalyticsService
from app.services.dashboard_aggregations import (
    compute_challenge_performance,
    compute_productivity_insights,
    compute_wake_stats,
    get_or_create_profile,
)
from app.services.habit_score import calculate_habit_score_for_user


class ReportType(str, Enum):
    HABIT = "habit"
    WAKE = "wake"
    CHALLENGE = "challenge"
    PRODUCTIVITY = "productivity"
    SLEEP = "sleep"


REPORT_META: Dict[ReportType, Dict[str, str]] = {
    ReportType.HABIT: {
        "title": "Habit Report",
        "description": "Habit score, component breakdown, and daily habit trends.",
    },
    ReportType.WAKE: {
        "title": "Wake Report",
        "description": "Wake consistency, success rate, and dismiss timing.",
    },
    ReportType.CHALLENGE: {
        "title": "Challenge Performance",
        "description": "Challenge accuracy, response time, and type breakdown.",
    },
    ReportType.PRODUCTIVITY: {
        "title": "Productivity Report",
        "description": "Morning routine, cognitive readiness, and consistency.",
    },
    ReportType.SLEEP: {
        "title": "Sleep Analytics",
        "description": "Sleep schedule adherence and related wake patterns.",
    },
}

EMPTY_MESSAGES: Dict[ReportType, str] = {
    ReportType.HABIT: (
        "No habit data for this period. Complete verified wake-ups and challenges "
        "to build your habit score, then regenerate this report."
    ),
    ReportType.WAKE: (
        "No wake events for this period. Dismiss an alarm with a verified wake-up "
        "to generate wake analytics."
    ),
    ReportType.CHALLENGE: (
        "No challenge attempts for this period. Solve a challenge when your alarm "
        "rings, then regenerate this report."
    ),
    ReportType.PRODUCTIVITY: (
        "No productivity data for this period. Complete verified wake-ups to unlock "
        "morning routine and readiness insights."
    ),
    ReportType.SLEEP: (
        "No sleep adherence data for this period. Set a preferred wake time and "
        "complete verified wake-ups to track sleep consistency."
    ),
}


def resolve_date_window(
    days: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[datetime, datetime, int]:
    """Resolve a UTC date window from lookback days or explicit dates.

    Returns ``(window_start, window_end, days)``.
    """
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise ValueError("Both start_date and end_date are required when filtering by date.")
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date.")
        span = (end_date - start_date).days + 1
        if span > 365:
            raise ValueError("Date range cannot exceed 365 days.")
        window_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        # Inclusive end of end_date
        window_end = datetime.combine(end_date, time.max, tzinfo=timezone.utc).replace(
            microsecond=999999
        )
        return window_start, window_end, span

    lookback = max(1, min(int(days or 30), 365))
    window_end = datetime.now(timezone.utc)
    window_start = (window_end - timedelta(days=lookback)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return window_start, window_end, lookback


def list_report_types() -> List[Dict[str, str]]:
    return [
        {
            "type": rt.value,
            "title": meta["title"],
            "description": meta["description"],
        }
        for rt, meta in REPORT_META.items()
    ]


class ReportService:
    """Build report payloads by reusing analytics/dashboard calculators."""

    @staticmethod
    def list_report_types() -> List[Dict[str, str]]:
        return list_report_types()

    @classmethod
    def build_report(
        cls,
        db: Session,
        user_id: int,
        report_type: ReportType,
        *,
        days: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        window_start, window_end, window_days = resolve_date_window(
            days=days, start_date=start_date, end_date=end_date
        )
        meta = REPORT_META[report_type]

        overview = BehavioralAnalyticsService.get_overview(
            db,
            user_id,
            days=window_days,
            window_start=window_start,
            window_end=window_end,
        )

        builders = {
            ReportType.HABIT: cls._build_habit,
            ReportType.WAKE: cls._build_wake,
            ReportType.CHALLENGE: cls._build_challenge,
            ReportType.PRODUCTIVITY: cls._build_productivity,
            ReportType.SLEEP: cls._build_sleep,
        }
        sections, is_empty = builders[report_type](
            db, user_id, overview, window_days, window_start, window_end
        )

        return {
            "report_type": report_type.value,
            "title": meta["title"],
            "description": meta["description"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "period": {
                "days": window_days,
                "start_date": window_start.date().isoformat(),
                "end_date": window_end.date().isoformat(),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
            "is_empty": is_empty,
            "empty_message": (
                EMPTY_MESSAGES.get(
                    report_type,
                    "No data available for this period. Complete a verified wake-up "
                    "to unlock this report.",
                )
                if is_empty
                else None
            ),
            "sections": sections,
            "insights": overview.get("insights") or [],
        }

    @classmethod
    def _build_habit(
        cls,
        db: Session,
        user_id: int,
        overview: Dict[str, Any],
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], bool]:
        profile = get_or_create_profile(user_id, db)
        habit_score = calculate_habit_score_for_user(db, user_id, profile)
        habit_trends = overview.get("habit_trends") or {}
        series = habit_trends.get("series") or []
        active_days = sum(1 for d in series if d.get("has_activity"))
        is_empty = active_days == 0

        sections = {
            "summary": {
                "habit_score": habit_score.get("habit_score", 0),
                "breakdown": habit_score.get("breakdown", {}),
                "weights": habit_score.get("weights", {}),
                "current_streak": int(profile.streak_days or 0),
                "best_streak": int(profile.best_streak or 0),
            },
            "trends": habit_trends,
            "snooze_pattern": overview.get("snooze_pattern"),
            "wake_up_consistency": overview.get("wake_up_consistency"),
            "sleep_schedule_adherence": overview.get("sleep_schedule_adherence"),
        }
        return sections, is_empty

    @classmethod
    def _build_wake(
        cls,
        db: Session,
        user_id: int,
        overview: Dict[str, Any],
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], bool]:
        wake_stats = compute_wake_stats(
            db, user_id, days, cutoff=window_start, window_end=window_end
        )
        consistency = overview.get("wake_up_consistency") or {}
        is_empty = (wake_stats.get("total_wake_events") or 0) == 0
        sections = {
            "summary": {
                **{k: wake_stats[k] for k in (
                    "total_wake_events",
                    "verified_wakes",
                    "abandoned_wakes",
                    "success_rate",
                    "first_try_success_rate",
                    "avg_time_to_dismiss_seconds",
                    "median_time_to_dismiss_seconds",
                    "avg_snoozes_before_dismiss",
                    "avg_wakefulness_score",
                )},
                "consistency_score": consistency.get("consistency_score"),
                "on_time_rate": consistency.get("on_time_rate"),
                "mean_wake_time": consistency.get("mean_wake_time"),
                "preferred_wake_time": consistency.get("preferred_wake_time"),
                "trend": consistency.get("trend"),
            },
            "wake_stats": wake_stats,
            "wake_up_consistency": consistency,
            "snooze_pattern": overview.get("snooze_pattern"),
            "weekly_trends": overview.get("weekly_trends"),
        }
        return sections, is_empty

    @classmethod
    def _build_challenge(
        cls,
        db: Session,
        user_id: int,
        overview: Dict[str, Any],
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], bool]:
        challenge = compute_challenge_performance(
            db, user_id, days, cutoff=window_start, window_end=window_end
        )
        is_empty = (challenge.get("total_attempts") or 0) == 0
        sections = {
            "summary": {
                "total_attempts": challenge.get("total_attempts", 0),
                "correct_answers": challenge.get("correct_answers", 0),
                "accuracy": challenge.get("accuracy", 0.0),
                "avg_response_time": challenge.get("avg_response_time", 0.0),
                "total_points_earned": challenge.get("total_points_earned", 0),
                "best_type": challenge.get("best_type"),
                "worst_type": challenge.get("worst_type"),
                "trend": challenge.get("trend"),
            },
            "challenge_performance": challenge,
            "weekly_trends": overview.get("weekly_trends"),
        }
        return sections, is_empty

    @classmethod
    def _build_productivity(
        cls,
        db: Session,
        user_id: int,
        overview: Dict[str, Any],
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], bool]:
        productivity = compute_productivity_insights(
            db, user_id, days, cutoff=window_start, window_end=window_end
        )
        is_empty = (productivity.get("verified_wakes") or 0) == 0 and (
            productivity.get("challenge_accuracy") or 0
        ) == 0
        # More precise: empty when no wakes and no challenge activity in period
        challenge = compute_challenge_performance(
            db, user_id, days, cutoff=window_start, window_end=window_end
        )
        is_empty = (
            (productivity.get("verified_wakes") or 0) == 0
            and (challenge.get("total_attempts") or 0) == 0
        )
        sections = {
            "summary": {
                "morning_routine_score": productivity.get("morning_routine_score"),
                "cognitive_readiness_score": productivity.get("cognitive_readiness_score"),
                "habit_score": productivity.get("habit_score"),
                "consistency_rate": productivity.get("consistency_rate"),
                "active_days_in_period": productivity.get("active_days_in_period"),
                "verified_wakes": productivity.get("verified_wakes"),
                "challenge_accuracy": productivity.get("challenge_accuracy"),
                "current_streak": productivity.get("current_streak"),
                "best_streak": productivity.get("best_streak"),
                "avg_time_to_productive_seconds": productivity.get(
                    "avg_time_to_productive_seconds"
                ),
                "trend": productivity.get("trend"),
            },
            "productivity": productivity,
            "habit_trends": overview.get("habit_trends"),
        }
        return sections, is_empty

    @classmethod
    def _build_sleep(
        cls,
        db: Session,
        user_id: int,
        overview: Dict[str, Any],
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], bool]:
        sleep = overview.get("sleep_schedule_adherence") or {}
        wake = overview.get("wake_up_consistency") or {}
        verified = wake.get("verified_wakes") or 0
        is_empty = verified == 0
        sections = {
            "summary": {
                "adherence_rate": sleep.get("adherence_rate"),
                "adherent_days": sleep.get("adherent_days"),
                "observed_days": sleep.get("observed_days"),
                "suggested_bedtime": sleep.get("suggested_bedtime"),
                "preferred_wake_time": sleep.get("preferred_wake_time")
                or wake.get("preferred_wake_time"),
                "target_sleep_hours": sleep.get("target_sleep_hours"),
                "profile_streak_days": sleep.get("profile_streak_days"),
                "profile_adherence_score": sleep.get("profile_adherence_score"),
                "avg_deviation_minutes": sleep.get("avg_deviation_minutes"),
                "on_time_rate": wake.get("on_time_rate"),
                "trend": sleep.get("trend"),
            },
            "sleep_schedule_adherence": sleep,
            "wake_up_consistency": wake,
            "snooze_pattern": overview.get("snooze_pattern"),
            "weekly_trends": overview.get("weekly_trends"),
        }
        return sections, is_empty
