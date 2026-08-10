"""
Wellness coach roster service.

Owns two responsibilities:

1. **Scoping** — resolving which clients a coach may see, via
   ``coach_assignments``. Every coach endpoint routes its authorization
   through :meth:`CoachService.get_assigned_client` or
   :meth:`CoachService.assigned_client_ids`, so there is exactly one place
   where cross-client access is decided.

2. **Roster aggregation** — building the client list with per-client habit
   score, streak, consistency, and engagement figures.

All figures come from the same services the user-facing dashboard uses
(``habit_score``, ``dashboard_aggregations``, ``BehavioralAnalyticsService``),
so a coach and their client never see different numbers for the same metric.

The roster is computed in full and then filtered / sorted / paginated in
memory rather than in SQL. Habit score is a weighted composite that cannot be
expressed as a SQL column, so sorting or filtering on it in SQL is impossible;
doing the whole thing in memory keeps every field consistently sortable and
keeps pagination correct. Cost is bounded because a roster is an admin-curated
set of assignments, and the underlying data is fetched with one batched query
per table regardless of roster size.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.coach_assignment import CoachAssignment
from app.models.profile import UserProfile
from app.models.user import User, UserRole
from app.services.day_streak import apply_missed_day_decay, today_in_timezone
from app.services.habit_score import calculate_habit_score_with_events
from app.services.system_settings_service import SystemSettingsService

# Days without a verified wake before a client is flagged as disengaged.
INACTIVITY_ALERT_DAYS = 7

# Sort keys accepted by :meth:`CoachService.list_clients`.
CLIENT_SORT_FIELDS = (
    "full_name",
    "username",
    "email",
    "assigned_at",
    "habit_score",
    "streak_days",
    "wake_consistency",
    "verified_wakes",
    "challenge_accuracy",
    "last_wake_at",
)

# Status filters accepted by :meth:`CoachService.list_clients`.
CLIENT_STATUS_FILTERS = ("all", "needs_attention", "on_track", "inactive")


def _utc_isoformat(value: Optional[datetime]) -> Optional[str]:
    """Serialize a stored (UTC-naive) datetime with an explicit UTC offset."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _time_isoformat(value: Optional[Any]) -> Optional[str]:
    """Serialize a ``Time`` column as ``HH:MM``."""
    if value is None:
        return None
    return value.strftime("%H:%M")


def _mean(values: Sequence[float], decimals: int = 1) -> float:
    """Arithmetic mean, or 0.0 for an empty sequence."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), decimals)


def _percentage(numerator: int, denominator: int, decimals: int = 1) -> float:
    """Percentage guarded against a zero denominator."""
    if not denominator:
        return 0.0
    return round((numerator / denominator) * 100.0, decimals)


class CoachService:
    """Assignment scoping and roster aggregation for wellness coaches."""

    # ── Scoping ──────────────────────────────────────────────────────────

    @staticmethod
    def assignment_query(db: Session, coach_id: int):
        """Base query for a coach's active assignments joined to the client."""
        return (
            db.query(CoachAssignment, User)
            .join(User, User.id == CoachAssignment.client_id)
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.is_active.is_(True),
            )
        )

    @classmethod
    def assigned_client_ids(cls, db: Session, coach_id: int) -> List[int]:
        """Return the client user IDs actively assigned to ``coach_id``."""
        rows = (
            db.query(CoachAssignment.client_id)
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.is_active.is_(True),
            )
            .all()
        )
        return [client_id for (client_id,) in rows]

    @classmethod
    def is_client_assigned(cls, db: Session, coach_id: int, client_id: int) -> bool:
        """Whether ``client_id`` is actively assigned to ``coach_id``."""
        return (
            db.query(CoachAssignment.id)
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.client_id == client_id,
                CoachAssignment.is_active.is_(True),
            )
            .first()
            is not None
        )

    @classmethod
    def get_assigned_client(
        cls, db: Session, coach_id: int, client_id: int
    ) -> Optional[User]:
        """Return the client ``User`` only if actively assigned to the coach.

        Returns ``None`` for unassigned, deactivated, or non-existent clients
        so callers can answer with a uniform 404 and never reveal whether an
        unassigned user exists.
        """
        row = (
            db.query(User)
            .join(
                CoachAssignment,
                CoachAssignment.client_id == User.id,
            )
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.is_active.is_(True),
                User.id == client_id,
            )
            .first()
        )
        return row

    # ── Batched aggregate loaders ────────────────────────────────────────

    @staticmethod
    def _load_profiles(
        db: Session, client_ids: Sequence[int]
    ) -> Dict[int, UserProfile]:
        if not client_ids:
            return {}
        rows = (
            db.query(UserProfile)
            .filter(UserProfile.user_id.in_(client_ids))
            .all()
        )
        return {row.user_id: row for row in rows}

    @staticmethod
    def _load_verified_wake_events(
        db: Session, client_ids: Sequence[int]
    ) -> Dict[int, List[AlarmWakeEvent]]:
        """Lifetime verified wake events grouped by client.

        Habit score replays the full verified history, so this cannot be
        limited to the reporting window.
        """
        if not client_ids:
            return {}
        rows = (
            db.query(AlarmWakeEvent)
            .filter(
                AlarmWakeEvent.user_id.in_(client_ids),
                AlarmWakeEvent.verified.is_(True),
            )
            .order_by(
                AlarmWakeEvent.dismissed_at.asc(),
                AlarmWakeEvent.id.asc(),
            )
            .all()
        )
        grouped: Dict[int, List[AlarmWakeEvent]] = {}
        for row in rows:
            grouped.setdefault(row.user_id, []).append(row)
        return grouped

    @staticmethod
    def _load_puzzle_stats(
        db: Session, client_ids: Sequence[int]
    ) -> Dict[int, Dict[str, int]]:
        """Lifetime challenge-log accuracy grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(
                AlarmChallengeLog.user_id,
                func.count(AlarmChallengeLog.id),
                func.sum(
                    case((AlarmChallengeLog.is_correct.is_(True), 1), else_=0)
                ),
            )
            .filter(AlarmChallengeLog.user_id.in_(client_ids))
            .group_by(AlarmChallengeLog.user_id)
            .all()
        )
        return {
            user_id: {
                "total_puzzle_attempts": int(attempts or 0),
                "total_puzzle_correct": int(correct or 0),
            }
            for user_id, attempts, correct in rows
        }

    @staticmethod
    def _load_window_wakes(
        db: Session,
        client_ids: Sequence[int],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[int, Dict[str, Any]]:
        """Wake-event counts inside the reporting window, grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(
                AlarmWakeEvent.user_id,
                func.count(AlarmWakeEvent.id),
                func.sum(case((AlarmWakeEvent.verified.is_(True), 1), else_=0)),
                func.sum(AlarmWakeEvent.snooze_count_at_dismiss),
                func.avg(AlarmWakeEvent.wakefulness_score),
            )
            .filter(
                AlarmWakeEvent.user_id.in_(client_ids),
                AlarmWakeEvent.triggered_at >= window_start,
                AlarmWakeEvent.triggered_at <= window_end,
            )
            .group_by(AlarmWakeEvent.user_id)
            .all()
        )
        return {
            user_id: {
                "wake_events": int(total or 0),
                "verified_wakes": int(verified or 0),
                "snoozes_at_dismiss": int(snoozes or 0),
                "avg_wakefulness": (
                    round(float(wakefulness), 1) if wakefulness is not None else None
                ),
            }
            for user_id, total, verified, snoozes, wakefulness in rows
        }

    @staticmethod
    def _load_last_verified_wake(
        db: Session, client_ids: Sequence[int]
    ) -> Dict[int, datetime]:
        """Most recent lifetime verified wake timestamp, grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(
                AlarmWakeEvent.user_id,
                func.max(AlarmWakeEvent.dismissed_at),
            )
            .filter(
                AlarmWakeEvent.user_id.in_(client_ids),
                AlarmWakeEvent.verified.is_(True),
            )
            .group_by(AlarmWakeEvent.user_id)
            .all()
        )
        return {
            user_id: dismissed_at
            for user_id, dismissed_at in rows
            if dismissed_at is not None
        }

    @staticmethod
    def _load_window_snoozes(
        db: Session,
        client_ids: Sequence[int],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[int, int]:
        """Snooze-event counts inside the reporting window, grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(
                AlarmSnoozeEvent.user_id,
                func.count(AlarmSnoozeEvent.id),
            )
            .filter(
                AlarmSnoozeEvent.user_id.in_(client_ids),
                AlarmSnoozeEvent.created_at >= window_start,
                AlarmSnoozeEvent.created_at <= window_end,
            )
            .group_by(AlarmSnoozeEvent.user_id)
            .all()
        )
        return {user_id: int(count or 0) for user_id, count in rows}

    @staticmethod
    def _load_window_challenges(
        db: Session,
        client_ids: Sequence[int],
        window_start: datetime,
        window_end: datetime,
    ) -> Dict[int, Dict[str, Any]]:
        """Challenge attempts inside the reporting window, grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(
                AlarmChallengeLog.user_id,
                func.count(AlarmChallengeLog.id),
                func.sum(
                    case((AlarmChallengeLog.is_correct.is_(True), 1), else_=0)
                ),
                func.avg(AlarmChallengeLog.time_taken_seconds),
                func.sum(AlarmChallengeLog.points_earned),
            )
            .filter(
                AlarmChallengeLog.user_id.in_(client_ids),
                AlarmChallengeLog.created_at >= window_start,
                AlarmChallengeLog.created_at <= window_end,
            )
            .group_by(AlarmChallengeLog.user_id)
            .all()
        )
        return {
            user_id: {
                "attempts": int(attempts or 0),
                "correct": int(correct or 0),
                "accuracy": _percentage(int(correct or 0), int(attempts or 0)),
                "avg_response_time": (
                    round(float(avg_time), 1) if avg_time is not None else 0.0
                ),
                "points": int(points or 0),
            }
            for user_id, attempts, correct, avg_time, points in rows
        }

    @staticmethod
    def _load_active_alarm_counts(
        db: Session, client_ids: Sequence[int]
    ) -> Dict[int, int]:
        """Active alarm counts grouped by client."""
        if not client_ids:
            return {}
        rows = (
            db.query(Alarm.user_id, func.count(Alarm.id))
            .filter(
                Alarm.user_id.in_(client_ids),
                Alarm.is_active.is_(True),
            )
            .group_by(Alarm.user_id)
            .all()
        )
        return {user_id: int(count or 0) for user_id, count in rows}

    # ── Roster construction ──────────────────────────────────────────────

    @classmethod
    def build_roster(
        cls,
        db: Session,
        coach_id: int,
        *,
        days: int = 30,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        only_client_ids: Optional[Sequence[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Build the aggregated client roster for a coach.

        Returns one row per actively assigned client. An empty list means the
        coach has no assignments — callers surface that as an empty state
        rather than an error.

        ``only_client_ids`` narrows the aggregation to specific clients, which
        is how the single-client detail endpoint avoids paying for the whole
        roster. It restricts, never widens: an id outside the coach's
        assignments is simply absent from the result.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if window_end is None:
            window_end = now
        if window_start is None:
            window_start = (window_end - timedelta(days=days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        assignment_query = cls.assignment_query(db, coach_id)
        if only_client_ids is not None:
            if not only_client_ids:
                return []
            assignment_query = assignment_query.filter(
                CoachAssignment.client_id.in_(list(only_client_ids))
            )

        assignments = assignment_query.order_by(
            CoachAssignment.created_at.asc(), CoachAssignment.id.asc()
        ).all()
        if not assignments:
            return []

        client_ids = [user.id for _assignment, user in assignments]

        profiles = cls._load_profiles(db, client_ids)
        wake_events = cls._load_verified_wake_events(db, client_ids)
        puzzle_stats = cls._load_puzzle_stats(db, client_ids)
        window_wakes = cls._load_window_wakes(
            db, client_ids, window_start, window_end
        )
        window_snoozes = cls._load_window_snoozes(
            db, client_ids, window_start, window_end
        )
        window_challenges = cls._load_window_challenges(
            db, client_ids, window_start, window_end
        )
        last_wakes = cls._load_last_verified_wake(db, client_ids)
        alarm_counts = cls._load_active_alarm_counts(db, client_ids)
        thresholds = SystemSettingsService.get_alert_thresholds(db)

        roster: List[Dict[str, Any]] = []
        for assignment, client in assignments:
            profile = profiles.get(client.id)
            events = wake_events.get(client.id, [])

            habit = calculate_habit_score_with_events(
                profile,
                events,
                puzzle_stats.get(client.id),
            )

            # Read-only streak display: apply missed-day decay as a pure
            # calculation so a coach viewing a roster never writes to a
            # client's profile row.
            streak_days = int(habit.get("streak_days", 0) or 0)
            best_streak = int(getattr(profile, "best_streak", 0) or 0)
            if profile is not None:
                decayed = apply_missed_day_decay(
                    streak_days=int(profile.streak_days or 0),
                    best_streak=best_streak,
                    last_successful_wake_date=profile.last_successful_wake_date,
                    today=today_in_timezone(profile.timezone or "UTC"),
                )
                streak_days = decayed.streak_days

            wake_window = window_wakes.get(client.id, {})
            challenge_window = window_challenges.get(client.id, {})
            last_wake_at = last_wakes.get(client.id)

            wake_consistency = round(
                float(getattr(profile, "wake_up_consistency_score", 0.0) or 0.0), 1
            )
            verified_wakes = int(wake_window.get("verified_wakes", 0) or 0)
            wake_event_count = int(wake_window.get("wake_events", 0) or 0)
            period_events = [
                event
                for event in events
                if event.triggered_at is not None
                and window_start <= event.triggered_at <= window_end
            ]
            period_habit = calculate_habit_score_with_events(
                None,
                period_events,
                {
                    "total_puzzle_attempts": int(
                        challenge_window.get("attempts", 0) or 0
                    ),
                    "total_puzzle_correct": int(
                        challenge_window.get("correct", 0) or 0
                    ),
                },
            )

            days_since_wake: Optional[int] = None
            if last_wake_at is not None:
                days_since_wake = max(0, (now - last_wake_at).days)

            alerts = cls._build_alerts(
                habit_score=float(habit["habit_score"]),
                wake_consistency=wake_consistency,
                days_since_wake=days_since_wake,
                verified_wakes=verified_wakes,
                thresholds=thresholds,
            )

            roster.append(
                {
                    "assignment_id": assignment.id,
                    "assigned_at": assignment.created_at,
                    "notes": assignment.notes,
                    "client_id": client.id,
                    "username": client.username,
                    "email": client.email,
                    "full_name": client.full_name,
                    "is_active": bool(client.is_active),
                    "joined_at": client.created_at,
                    "timezone": getattr(profile, "timezone", None) or "UTC",
                    "preferred_wake_time": _time_isoformat(
                        getattr(profile, "preferred_wake_time", None)
                    ),
                    "sleep_duration_hours": float(
                        getattr(profile, "sleep_duration_hours", 0.0) or 0.0
                    ),
                    "habit_score": float(habit["habit_score"]),
                    "period_habit_score": float(period_habit["habit_score"]),
                    "habit_breakdown": habit["breakdown"],
                    "streak_days": streak_days,
                    "best_streak": best_streak,
                    "wake_consistency": wake_consistency,
                    "verified_wakes": verified_wakes,
                    "wake_events": wake_event_count,
                    "wake_success_rate": _percentage(
                        verified_wakes, wake_event_count
                    ),
                    "snoozes": int(window_snoozes.get(client.id, 0) or 0),
                    "avg_wakefulness": wake_window.get("avg_wakefulness"),
                    "challenge_attempts": int(challenge_window.get("attempts", 0) or 0),
                    "challenge_accuracy": float(
                        challenge_window.get("accuracy", 0.0) or 0.0
                    ),
                    "active_alarms": int(alarm_counts.get(client.id, 0) or 0),
                    "last_wake_at": last_wake_at,
                    "days_since_last_wake": days_since_wake,
                    "needs_attention": bool(alerts),
                    "alerts": alerts,
                    "has_activity": bool(
                        wake_event_count
                        or challenge_window.get("attempts")
                    ),
                }
            )

        return roster

    @staticmethod
    def _build_alerts(
        *,
        habit_score: float,
        wake_consistency: float,
        days_since_wake: Optional[int],
        verified_wakes: int,
        thresholds: Dict[str, float],
    ) -> List[str]:
        """Return human-readable coaching alerts from real thresholds.

        Thresholds come from the admin-configured ``system_settings`` row so
        coach flags match the platform's own alerting rules.
        """
        alerts: List[str] = []
        if habit_score < thresholds.get("habit_score", 30.0):
            alerts.append(
                f"Habit score {round(habit_score)}/100 is below the "
                f"{round(thresholds.get('habit_score', 30.0))} alert threshold"
            )
        if wake_consistency < thresholds.get("consistency", 30.0):
            alerts.append(
                f"Wake consistency {round(wake_consistency)} is below the "
                f"{round(thresholds.get('consistency', 30.0))} alert threshold"
            )
        if days_since_wake is None:
            alerts.append("No verified wake-up recorded yet")
        elif days_since_wake >= INACTIVITY_ALERT_DAYS:
            alerts.append(
                f"No verified wake-up in {days_since_wake} days"
            )
        elif verified_wakes == 0:
            alerts.append("No verified wake-ups inside the selected window")
        return alerts

    # ── Public read APIs ─────────────────────────────────────────────────

    @classmethod
    def list_clients(
        cls,
        db: Session,
        coach_id: int,
        *,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        status: str = "all",
        sort_by: str = "full_name",
        sort_order: str = "asc",
        days: int = 30,
    ) -> Dict[str, Any]:
        """Return a filtered, sorted, paginated view of the coach's roster."""
        roster = cls.build_roster(db, coach_id, days=days)
        total_assigned = len(roster)

        if search:
            needle = search.strip().lower()
            roster = [
                row
                for row in roster
                if needle in (row["username"] or "").lower()
                or needle in (row["email"] or "").lower()
                or needle in (row["full_name"] or "").lower()
            ]

        if status == "needs_attention":
            roster = [row for row in roster if row["needs_attention"]]
        elif status == "on_track":
            roster = [row for row in roster if not row["needs_attention"]]
        elif status == "inactive":
            roster = [row for row in roster if not row["has_activity"]]

        roster = cls._sort_roster(roster, sort_by=sort_by, sort_order=sort_order)

        total = len(roster)
        total_pages = max(1, -(-total // per_page))
        offset = (page - 1) * per_page
        page_rows = roster[offset : offset + per_page]

        return {
            "total": total,
            "total_assigned": total_assigned,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "days": days,
            "clients": [cls.serialize_client(row) for row in page_rows],
        }

    @staticmethod
    def _sort_roster(
        roster: List[Dict[str, Any]], *, sort_by: str, sort_order: str
    ) -> List[Dict[str, Any]]:
        """Sort roster rows, using client_id as a deterministic tiebreaker."""
        reverse = sort_order == "desc"

        # Sentinels keep rows with missing values at the bottom regardless of
        # direction, so "never woke up" clients don't top the habit-score sort.
        def key(row: Dict[str, Any]) -> Tuple[Any, int]:
            if sort_by in ("full_name", "username", "email"):
                return ((row.get(sort_by) or "").lower(), row["client_id"])
            if sort_by == "assigned_at":
                return (
                    row["assigned_at"] or datetime.min,
                    row["client_id"],
                )
            if sort_by == "last_wake_at":
                return (
                    row["last_wake_at"] or datetime.min,
                    row["client_id"],
                )
            return (row.get(sort_by) or 0, row["client_id"])

        return sorted(roster, key=key, reverse=reverse)

    @staticmethod
    def serialize_client(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert datetime fields in a roster row to ISO strings."""
        serialized = dict(row)
        serialized["assigned_at"] = _utc_isoformat(row["assigned_at"])
        serialized["joined_at"] = _utc_isoformat(row["joined_at"])
        serialized["last_wake_at"] = _utc_isoformat(row["last_wake_at"])
        return serialized

    @classmethod
    def roster_overview(
        cls, db: Session, coach_id: int, *, days: int = 30
    ) -> Dict[str, Any]:
        """Return roster-wide KPIs across every assigned client."""
        roster = cls.build_roster(db, coach_id, days=days)
        generated_at = datetime.now(timezone.utc).isoformat()

        if not roster:
            return {
                "generated_at": generated_at,
                "days": days,
                "total_clients": 0,
                "active_clients": 0,
                "deactivated_clients": 0,
                "engaged_clients": 0,
                "engagement_rate": 0.0,
                "needs_attention_count": 0,
                "avg_habit_score": 0.0,
                "avg_wake_consistency": 0.0,
                "avg_streak_days": 0.0,
                "total_verified_wakes": 0,
                "total_wake_events": 0,
                "total_snoozes": 0,
                "roster_wake_success_rate": 0.0,
                "challenge_attempts": 0,
                "challenge_accuracy": 0.0,
                "habit_score_distribution": [],
                "attention_clients": [],
                "top_clients": [],
                "is_empty": True,
            }

        active_roster = [row for row in roster if row["is_active"]]
        # Same current habit score the roster/client detail render, so the KPI
        # card and the per-client figures can never disagree.
        habit_scores = [row["habit_score"] for row in active_roster]
        consistencies = [row["wake_consistency"] for row in active_roster]
        streaks = [float(row["streak_days"]) for row in active_roster]

        total_verified = sum(row["verified_wakes"] for row in active_roster)
        total_wake_events = sum(row["wake_events"] for row in active_roster)
        total_snoozes = sum(row["snoozes"] for row in active_roster)
        total_attempts = sum(row["challenge_attempts"] for row in active_roster)
        total_correct = sum(
            round(row["challenge_attempts"] * row["challenge_accuracy"] / 100.0)
            for row in active_roster
        )
        engaged = [row for row in active_roster if row["has_activity"]]
        attention = [row for row in active_roster if row["needs_attention"]]

        buckets = [
            ("0-24", 0, 25),
            ("25-49", 25, 50),
            ("50-74", 50, 75),
            ("75-100", 75, 101),
        ]
        distribution = [
            {
                "band": label,
                "count": sum(1 for s in habit_scores if low <= s < high),
            }
            for label, low, high in buckets
        ]

        by_score = sorted(
            active_roster, key=lambda r: (-r["habit_score"], r["client_id"])
        )

        return {
            "generated_at": generated_at,
            "days": days,
            "total_clients": len(roster),
            "active_clients": len(active_roster),
            "deactivated_clients": sum(1 for row in roster if not row["is_active"]),
            "engaged_clients": len(engaged),
            "engagement_rate": _percentage(len(engaged), len(active_roster)),
            "needs_attention_count": len(attention),
            "avg_habit_score": _mean(habit_scores),
            "avg_wake_consistency": _mean(consistencies),
            "avg_streak_days": _mean(streaks),
            "total_verified_wakes": total_verified,
            "total_wake_events": total_wake_events,
            "total_snoozes": total_snoozes,
            "roster_wake_success_rate": _percentage(total_verified, total_wake_events),
            "challenge_attempts": total_attempts,
            "challenge_accuracy": _percentage(total_correct, total_attempts),
            "habit_score_distribution": distribution,
            "attention_clients": [
                {
                    "client_id": row["client_id"],
                    "full_name": row["full_name"],
                    "username": row["username"],
                    "habit_score": row["habit_score"],
                    "wake_consistency": row["wake_consistency"],
                    "days_since_last_wake": row["days_since_last_wake"],
                    "alerts": row["alerts"],
                }
                for row in sorted(
                    attention, key=lambda r: (r["habit_score"], r["client_id"])
                )[:5]
            ],
            "top_clients": [
                {
                    "client_id": row["client_id"],
                    "full_name": row["full_name"],
                    "username": row["username"],
                    "habit_score": row["habit_score"],
                    "streak_days": row["streak_days"],
                    "verified_wakes": row["verified_wakes"],
                }
                for row in by_score[:5]
            ],
            "is_empty": False,
        }

    # ── Assignment management (admin-facing) ─────────────────────────────

    @classmethod
    def assign_client(
        cls,
        db: Session,
        *,
        coach_id: int,
        client_id: int,
        assigned_by_user_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> CoachAssignment:
        """Create or reactivate a coach/client assignment.

        Raises:
            ValueError: If the roles are wrong, the users are missing, or the
                coach and client are the same account.
        """
        if coach_id == client_id:
            raise ValueError("A coach cannot be assigned to themselves")

        coach = db.query(User).filter(User.id == coach_id).first()
        if coach is None:
            raise ValueError("Coach not found")
        if coach.role != UserRole.WELLNESS_COACH:
            raise ValueError("Assigned coach must hold the wellness_coach role")

        client = db.query(User).filter(User.id == client_id).first()
        if client is None:
            raise ValueError("Client not found")
        if client.role != UserRole.USER:
            raise ValueError("Only users with the 'user' role can be coached")

        existing = (
            db.query(CoachAssignment)
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.client_id == client_id,
            )
            .first()
        )
        if existing is not None:
            existing.is_active = True
            existing.assigned_by_user_id = assigned_by_user_id
            if notes is not None:
                existing.notes = notes
            db.commit()
            db.refresh(existing)
            return existing

        assignment = CoachAssignment(
            coach_id=coach_id,
            client_id=client_id,
            assigned_by_user_id=assigned_by_user_id,
            notes=notes,
            is_active=True,
        )
        db.add(assignment)
        db.commit()
        db.refresh(assignment)
        return assignment

    @classmethod
    def unassign_client(
        cls, db: Session, *, coach_id: int, client_id: int
    ) -> bool:
        """Deactivate an assignment, preserving it for history.

        Returns ``False`` when no active assignment existed.
        """
        assignment = (
            db.query(CoachAssignment)
            .filter(
                CoachAssignment.coach_id == coach_id,
                CoachAssignment.client_id == client_id,
                CoachAssignment.is_active.is_(True),
            )
            .first()
        )
        if assignment is None:
            return False
        assignment.is_active = False
        db.commit()
        return True

    @classmethod
    def list_assignments(
        cls,
        db: Session,
        *,
        coach_id: Optional[int] = None,
        client_id: Optional[int] = None,
        is_active: Optional[bool] = True,
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        """Paginated assignment listing for admin management screens."""
        query = db.query(CoachAssignment)
        if coach_id is not None:
            query = query.filter(CoachAssignment.coach_id == coach_id)
        if client_id is not None:
            query = query.filter(CoachAssignment.client_id == client_id)
        if is_active is not None:
            query = query.filter(CoachAssignment.is_active.is_(is_active))

        total = query.count()
        rows = (
            query.order_by(CoachAssignment.created_at.desc(), CoachAssignment.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        user_ids = {row.coach_id for row in rows} | {row.client_id for row in rows}
        users = (
            {
                user.id: user
                for user in db.query(User).filter(User.id.in_(user_ids)).all()
            }
            if user_ids
            else {}
        )

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, -(-total // per_page)),
            "assignments": [
                {
                    "id": row.id,
                    "coach_id": row.coach_id,
                    "coach_username": getattr(users.get(row.coach_id), "username", None),
                    "coach_full_name": getattr(
                        users.get(row.coach_id), "full_name", None
                    ),
                    "client_id": row.client_id,
                    "client_username": getattr(
                        users.get(row.client_id), "username", None
                    ),
                    "client_full_name": getattr(
                        users.get(row.client_id), "full_name", None
                    ),
                    "client_email": getattr(users.get(row.client_id), "email", None),
                    "is_active": bool(row.is_active),
                    "notes": row.notes,
                    "assigned_by_user_id": row.assigned_by_user_id,
                    "created_at": _utc_isoformat(row.created_at),
                    "updated_at": _utc_isoformat(row.updated_at),
                }
                for row in rows
            ],
        }

    @staticmethod
    def purge_user_assignments(db: Session, user_id: int) -> None:
        """Delete assignments referencing a user about to be removed.

        ``CoachAssignment`` intentionally has no relationship on ``User``, so
        ORM cascades do not reach it — user deletion must call this.
        """
        db.query(CoachAssignment).filter(
            (CoachAssignment.coach_id == user_id)
            | (CoachAssignment.client_id == user_id)
        ).delete(synchronize_session=False)
        db.query(CoachAssignment).filter(
            CoachAssignment.assigned_by_user_id == user_id
        ).update(
            {CoachAssignment.assigned_by_user_id: None}, synchronize_session=False
        )
