"""
Admin System Reports — platform-wide User / Alarm / Habit / Platform reports.

Builds ReportResponse-compatible payloads so PDF/Excel export can reuse
``report_export.export_report``. Aggregations use the same SSOT tables as
the admin dashboard endpoints.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.challenge_session import ChallengeSession
from app.models.profile import UserProfile
from app.models.user import User
from app.services.habit_score import calculate_habit_score
from app.services.report_service import resolve_date_window


class SystemReportType(str, Enum):
    USER = "user"
    ALARM = "alarm"
    HABIT = "habit"
    PLATFORM = "platform"


SYSTEM_REPORT_META: Dict[SystemReportType, Dict[str, str]] = {
    SystemReportType.USER: {
        "title": "User Report",
        "description": "User growth, engagement, role mix, and top performers.",
    },
    SystemReportType.ALARM: {
        "title": "Alarm Report",
        "description": "Alarm inventory, wake/snooze activity, and top active alarms.",
    },
    SystemReportType.HABIT: {
        "title": "Habit Report",
        "description": "Platform habit scores, streaks, consistency, and difficulty signals.",
    },
    SystemReportType.PLATFORM: {
        "title": "Platform Report",
        "description": "Cross-cutting engagement, challenges, analytics, and system health.",
    },
}

EMPTY_MESSAGES: Dict[SystemReportType, str] = {
    SystemReportType.USER: (
        "No user activity for this period. New registrations or wake events "
        "will appear here once they occur."
    ),
    SystemReportType.ALARM: (
        "No alarm activity for this period. Wake or snooze events will populate "
        "this report."
    ),
    SystemReportType.HABIT: (
        "No habit profiles available. User profiles with wake activity will "
        "unlock habit analytics."
    ),
    SystemReportType.PLATFORM: (
        "No platform activity for this period. Engagement and analytics events "
        "will appear once users interact with alarms."
    ),
}


def _safe_division(numerator: float, denominator: float, decimals: int = 1) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, decimals)


def _in_window(column, window_start: datetime, window_end: datetime):
    return and_(column >= window_start, column <= window_end)


def list_system_report_types() -> List[Dict[str, str]]:
    return [
        {
            "type": rt.value,
            "title": meta["title"],
            "description": meta["description"],
        }
        for rt, meta in SYSTEM_REPORT_META.items()
    ]


class SystemReportService:
    """Build admin system report payloads for preview and export."""

    @staticmethod
    def list_report_types() -> List[Dict[str, str]]:
        return list_system_report_types()

    @classmethod
    def build_report(
        cls,
        db: Session,
        report_type: SystemReportType,
        *,
        days: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        window_start, window_end, window_days = resolve_date_window(
            days=days, start_date=start_date, end_date=end_date
        )
        meta = SYSTEM_REPORT_META[report_type]

        builders = {
            SystemReportType.USER: cls._build_user,
            SystemReportType.ALARM: cls._build_alarm,
            SystemReportType.HABIT: cls._build_habit,
            SystemReportType.PLATFORM: cls._build_platform,
        }
        sections, insights, is_empty = builders[report_type](
            db, window_days, window_start, window_end
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
                EMPTY_MESSAGES.get(report_type) if is_empty else None
            ),
            "sections": sections,
            "insights": insights,
        }

    # ── User report ──────────────────────────────────────────────────────

    @classmethod
    def _build_user(
        cls,
        db: Session,
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], List[str], bool]:
        total_users = db.query(func.count(User.id)).scalar() or 0
        active_users = (
            db.query(func.count(User.id))
            .filter(User.is_active == True)  # noqa: E712
            .scalar()
            or 0
        )
        verified_users = (
            db.query(func.count(User.id))
            .filter(User.is_verified == True)  # noqa: E712
            .scalar()
            or 0
        )

        role_distribution: Dict[str, int] = {}
        for role, count in (
            db.query(User.role, func.count(User.id)).group_by(User.role).all()
        ):
            role_distribution[role.value if hasattr(role, "value") else str(role)] = count

        new_users = (
            db.query(func.count(User.id))
            .filter(_in_window(User.created_at, window_start, window_end))
            .scalar()
            or 0
        )
        prev_start = window_start - timedelta(days=days)
        new_users_prev = (
            db.query(func.count(User.id))
            .filter(User.created_at >= prev_start, User.created_at < window_start)
            .scalar()
            or 0
        )
        growth_rate = _safe_division(
            (new_users - new_users_prev), max(new_users_prev, 1), 1
        ) * 100

        engaged_users = (
            db.query(func.count(func.distinct(AlarmWakeEvent.user_id)))
            .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
            .scalar()
            or 0
        )

        top_rows = (
            db.query(
                User.id,
                User.username,
                User.email,
                func.count(AlarmWakeEvent.id).label("verified_wakes"),
            )
            .join(AlarmWakeEvent, AlarmWakeEvent.user_id == User.id)
            .filter(
                _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
                AlarmWakeEvent.verified == True,  # noqa: E712
            )
            .group_by(User.id)
            .order_by(func.count(AlarmWakeEvent.id).desc())
            .limit(10)
            .all()
        )
        top_performers = [
            {
                "user_id": uid,
                "username": uname,
                "email": email,
                "verified_wakes": vw,
            }
            for uid, uname, email, vw in top_rows
        ]

        recent_users = (
            db.query(User)
            .filter(_in_window(User.created_at, window_start, window_end))
            .order_by(User.created_at.desc())
            .limit(25)
            .all()
        )
        new_user_rows = [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else str(u.role),
                "created_at": (
                    u.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if u.created_at and u.created_at.tzinfo is None
                    else (u.created_at.isoformat() if u.created_at else None)
                ),
            }
            for u in recent_users
        ]

        is_empty = total_users == 0 and new_users == 0
        insights: List[str] = []
        if new_users:
            insights.append(
                f"{new_users} new user(s) registered in this period "
                f"({growth_rate:+.1f}% vs prior period)."
            )
        if engaged_users:
            insights.append(
                f"{engaged_users} user(s) had at least one wake event "
                f"({_safe_division(engaged_users, total_users, 1) * 100:.1f}% of all users)."
            )
        if top_performers:
            lead = top_performers[0]
            insights.append(
                f"Top performer: {lead['username']} with {lead['verified_wakes']} verified wakes."
            )

        sections = {
            "summary": {
                "total_users": total_users,
                "active_users": active_users,
                "verified_users": verified_users,
                "new_users_in_period": new_users,
                "new_users_previous_period": new_users_prev,
                "user_growth_rate_pct": growth_rate,
                "engaged_users": engaged_users,
                "engagement_rate_pct": (
                    _safe_division(engaged_users, total_users, 1) * 100
                    if total_users
                    else 0.0
                ),
            },
            "role_distribution": role_distribution,
            "top_performers": top_performers,
            "tables": [
                {
                    "title": "Top Performers",
                    "headers": ["User ID", "Username", "Email", "Verified Wakes"],
                    "rows": [
                        [r["user_id"], r["username"], r["email"], r["verified_wakes"]]
                        for r in top_performers
                    ],
                },
                {
                    "title": "New Users in Period",
                    "headers": ["ID", "Username", "Email", "Role", "Created"],
                    "rows": [
                        [r["id"], r["username"], r["email"], r["role"], r["created_at"]]
                        for r in new_user_rows
                    ],
                },
            ],
        }
        return sections, insights, is_empty

    # ── Alarm report ─────────────────────────────────────────────────────

    @classmethod
    def _build_alarm(
        cls,
        db: Session,
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], List[str], bool]:
        total_alarms = db.query(func.count(Alarm.id)).scalar() or 0
        active_alarms = (
            db.query(func.count(Alarm.id))
            .filter(Alarm.is_active == True)  # noqa: E712
            .scalar()
            or 0
        )

        type_distribution: Dict[str, int] = {}
        for atype, cnt in (
            db.query(Alarm.alarm_type, func.count(Alarm.id))
            .group_by(Alarm.alarm_type)
            .all()
        ):
            key = atype.value if hasattr(atype, "value") else str(atype)
            type_distribution[key] = cnt

        challenge_type_distribution: Dict[str, int] = {}
        for ctype, cnt in (
            db.query(Alarm.challenge_type, func.count(Alarm.id))
            .group_by(Alarm.challenge_type)
            .all()
        ):
            key = ctype.value if hasattr(ctype, "value") else str(ctype)
            challenge_type_distribution[key] = cnt

        difficulty_distribution = {
            diff: cnt
            for diff, cnt in (
                db.query(Alarm.challenge_difficulty, func.count(Alarm.id))
                .group_by(Alarm.challenge_difficulty)
                .all()
            )
        }

        wake_events = (
            db.query(func.count(AlarmWakeEvent.id))
            .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
            .scalar()
            or 0
        )
        verified = (
            db.query(func.count(AlarmWakeEvent.id))
            .filter(
                _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
                AlarmWakeEvent.verified == True,  # noqa: E712
            )
            .scalar()
            or 0
        )
        snoozes = (
            db.query(func.count(AlarmSnoozeEvent.id))
            .filter(_in_window(AlarmSnoozeEvent.created_at, window_start, window_end))
            .scalar()
            or 0
        )

        top_alarms_query = (
            db.query(
                Alarm.id,
                Alarm.title,
                Alarm.alarm_type,
                Alarm.user_id,
                func.count(AlarmWakeEvent.id).label("wake_events"),
            )
            .join(AlarmWakeEvent, AlarmWakeEvent.alarm_id == Alarm.id)
            .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
            .group_by(Alarm.id)
            .order_by(func.count(AlarmWakeEvent.id).desc())
            .limit(10)
            .all()
        )
        top_alarms = [
            {
                "alarm_id": aid,
                "title": title,
                "alarm_type": atype.value if hasattr(atype, "value") else str(atype),
                "user_id": uid,
                "wake_events": we,
            }
            for aid, title, atype, uid, we in top_alarms_query
        ]

        avg_snooze_limit = db.query(func.avg(Alarm.snooze_limit)).scalar() or 0.0
        avg_snooze_interval = (
            db.query(func.avg(Alarm.snooze_interval_minutes)).scalar() or 0.0
        )
        avg_challenge_count = (
            db.query(func.avg(Alarm.challenge_count)).scalar() or 0.0
        )

        is_empty = total_alarms == 0 and wake_events == 0
        insights: List[str] = []
        if wake_events:
            insights.append(
                f"{wake_events} wake event(s) with "
                f"{_safe_division(verified, wake_events, 1) * 100:.1f}% success rate."
            )
        if snoozes:
            insights.append(
                f"{snoozes} snooze event(s) "
                f"({_safe_division(snoozes, max(wake_events, 1), 2)} per wake)."
            )
        if top_alarms:
            lead = top_alarms[0]
            insights.append(
                f"Most active alarm: \"{lead['title']}\" "
                f"({lead['wake_events']} wakes)."
            )

        sections = {
            "summary": {
                "total_alarms": total_alarms,
                "active_alarms": active_alarms,
                "inactive_alarms": total_alarms - active_alarms,
                "wake_events": wake_events,
                "verified_wakes": verified,
                "abandoned_wakes": wake_events - verified,
                "success_rate_pct": _safe_division(verified, wake_events, 1) * 100,
                "snooze_events": snoozes,
                "snooze_per_wake": _safe_division(snoozes, wake_events, 2),
                "avg_snooze_limit": round(float(avg_snooze_limit), 1),
                "avg_snooze_interval_minutes": round(float(avg_snooze_interval), 1),
                "avg_challenge_count": round(float(avg_challenge_count), 1),
            },
            "type_distribution": type_distribution,
            "challenge_type_distribution": challenge_type_distribution,
            "difficulty_distribution": difficulty_distribution,
            "top_active_alarms": top_alarms,
            "tables": [
                {
                    "title": "Top Active Alarms",
                    "headers": ["Alarm ID", "Title", "Type", "User ID", "Wake Events"],
                    "rows": [
                        [
                            r["alarm_id"],
                            r["title"],
                            r["alarm_type"],
                            r["user_id"],
                            r["wake_events"],
                        ]
                        for r in top_alarms
                    ],
                },
            ],
        }
        return sections, insights, is_empty

    # ── Habit report ─────────────────────────────────────────────────────

    @classmethod
    def _build_habit(
        cls,
        db: Session,
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], List[str], bool]:
        profiles = db.query(UserProfile).all()
        total_profiles = len(profiles)

        if not profiles:
            return (
                {
                    "summary": {"total_profiles": 0},
                    "tables": [],
                },
                [],
                True,
            )

        difficulty_dist: Dict[str, int] = {}
        adapted_dist: Dict[str, int] = {}
        streak_values = []
        best_streak_values = []
        consistency_scores = []
        habit_scores = []
        breakdown_sums = {
            "wake_up_consistency": 0.0,
            "challenge_completion": 0.0,
            "snooze_reduction": 0.0,
            "sleep_adherence": 0.0,
        }

        for p in profiles:
            diff = (
                p.difficulty_preference.value
                if p.difficulty_preference
                else "unknown"
            )
            difficulty_dist[diff] = difficulty_dist.get(diff, 0) + 1
            ad = (
                p.adapted_difficulty.value
                if p.adapted_difficulty
                else "unknown"
            )
            adapted_dist[ad] = adapted_dist.get(ad, 0) + 1
            streak_values.append(p.streak_days or 0)
            best_streak_values.append(p.best_streak or 0)
            consistency_scores.append(p.wake_up_consistency_score or 0.0)
            score_data = calculate_habit_score(p)
            habit_scores.append(float(score_data.get("habit_score", 0.0)))
            breakdown = score_data.get("breakdown") or {}
            for key in breakdown_sums:
                breakdown_sums[key] += float(breakdown.get(key, 0.0) or 0.0)

        # Period activity that feeds habit formation
        verified_wakes = (
            db.query(func.count(AlarmWakeEvent.id))
            .filter(
                _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
                AlarmWakeEvent.verified == True,  # noqa: E712
            )
            .scalar()
            or 0
        )
        challenge_attempts = (
            db.query(func.count(AlarmChallengeLog.id))
            .filter(_in_window(AlarmChallengeLog.created_at, window_start, window_end))
            .scalar()
            or 0
        )
        correct_challenges = (
            db.query(func.count(AlarmChallengeLog.id))
            .filter(
                _in_window(AlarmChallengeLog.created_at, window_start, window_end),
                AlarmChallengeLog.is_correct == True,  # noqa: E712
            )
            .scalar()
            or 0
        )

        avg_habit = round(sum(habit_scores) / total_profiles, 1)
        avg_consistency = round(sum(consistency_scores) / total_profiles, 1)
        avg_breakdown = {
            key: round(val / total_profiles, 1) for key, val in breakdown_sums.items()
        }

        is_empty = verified_wakes == 0 and challenge_attempts == 0
        insights: List[str] = [
            f"Average habit score across {total_profiles} profile(s): {avg_habit}.",
            f"Average wake consistency: {avg_consistency}.",
        ]
        if verified_wakes:
            insights.append(
                f"{verified_wakes} verified wake(s) in period feeding habit scores."
            )
        above_70 = sum(1 for s in habit_scores if s >= 70)
        if above_70:
            insights.append(f"{above_70} user(s) have habit scores of 70+.")

        sections = {
            "summary": {
                "total_profiles": total_profiles,
                "avg_habit_score": avg_habit,
                "min_habit_score": round(min(habit_scores), 1),
                "max_habit_score": round(max(habit_scores), 1),
                "users_above_70": above_70,
                "users_below_40": sum(1 for s in habit_scores if s < 40),
                "avg_current_streak": round(sum(streak_values) / total_profiles, 1),
                "max_current_streak": max(streak_values),
                "avg_best_streak": round(sum(best_streak_values) / total_profiles, 1),
                "max_best_streak": max(best_streak_values),
                "avg_consistency_score": avg_consistency,
                "users_above_80_consistency": sum(
                    1 for s in consistency_scores if s >= 80
                ),
                "verified_wakes_in_period": verified_wakes,
                "challenge_attempts_in_period": challenge_attempts,
                "challenge_accuracy_pct": (
                    _safe_division(correct_challenges, challenge_attempts, 1) * 100
                ),
                "breakdown": avg_breakdown,
            },
            "difficulty_distribution": {
                "user_preference": difficulty_dist,
                "adapted": adapted_dist,
            },
            "tables": [
                {
                    "title": "Habit Score Breakdown (avg)",
                    "headers": ["Component", "Average"],
                    "rows": [[k, v] for k, v in avg_breakdown.items()],
                },
            ],
        }
        return sections, insights, is_empty

    # ── Platform report ──────────────────────────────────────────────────

    @classmethod
    def _build_platform(
        cls,
        db: Session,
        days: int,
        window_start: datetime,
        window_end: datetime,
    ) -> Tuple[Dict[str, Any], List[str], bool]:
        total_users = db.query(func.count(User.id)).scalar() or 0
        wake_events = (
            db.query(func.count(AlarmWakeEvent.id))
            .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
            .scalar()
            or 0
        )
        verified_wakes = (
            db.query(func.count(AlarmWakeEvent.id))
            .filter(
                _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
                AlarmWakeEvent.verified == True,  # noqa: E712
            )
            .scalar()
            or 0
        )
        challenge_attempts = (
            db.query(func.count(AlarmChallengeLog.id))
            .filter(_in_window(AlarmChallengeLog.created_at, window_start, window_end))
            .scalar()
            or 0
        )
        correct_challenges = (
            db.query(func.count(AlarmChallengeLog.id))
            .filter(
                _in_window(AlarmChallengeLog.created_at, window_start, window_end),
                AlarmChallengeLog.is_correct == True,  # noqa: E712
            )
            .scalar()
            or 0
        )
        snoozes = (
            db.query(func.count(AlarmSnoozeEvent.id))
            .filter(_in_window(AlarmSnoozeEvent.created_at, window_start, window_end))
            .scalar()
            or 0
        )
        engaged_users = (
            db.query(func.count(func.distinct(AlarmWakeEvent.user_id)))
            .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
            .scalar()
            or 0
        )
        new_users = (
            db.query(func.count(User.id))
            .filter(_in_window(User.created_at, window_start, window_end))
            .scalar()
            or 0
        )
        analytics_events = (
            db.query(func.count(AnalyticsEvent.id))
            .filter(_in_window(AnalyticsEvent.created_at, window_start, window_end))
            .scalar()
            or 0
        )

        # Challenge type breakdown
        challenge_logs = (
            db.query(AlarmChallengeLog)
            .filter(_in_window(AlarmChallengeLog.created_at, window_start, window_end))
            .all()
        )
        by_type: Dict[str, Dict[str, Any]] = {}
        for log in challenge_logs:
            ct = log.challenge_type or "unknown"
            if ct not in by_type:
                by_type[ct] = {"total": 0, "correct": 0, "points": 0, "avg_time": 0.0}
            by_type[ct]["total"] += 1
            if log.is_correct:
                by_type[ct]["correct"] += 1
            by_type[ct]["points"] += log.points_earned or 0
        for ct_data in by_type.values():
            ct_data["accuracy"] = _safe_division(
                ct_data["correct"], ct_data["total"], 1
            ) * 100

        # System health snapshot
        table_counts = {
            "users": total_users,
            "user_profiles": db.query(func.count(UserProfile.id)).scalar() or 0,
            "alarms": db.query(func.count(Alarm.id)).scalar() or 0,
            "alarm_wake_events": db.query(func.count(AlarmWakeEvent.id)).scalar() or 0,
            "alarm_snooze_events": db.query(func.count(AlarmSnoozeEvent.id)).scalar()
            or 0,
            "alarm_challenge_logs": db.query(func.count(AlarmChallengeLog.id)).scalar()
            or 0,
            "analytics_events": db.query(func.count(AnalyticsEvent.id)).scalar() or 0,
            "challenge_sessions": db.query(func.count(ChallengeSession.id)).scalar()
            or 0,
        }
        users_without_profiles = (
            db.query(func.count(User.id))
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .filter(UserProfile.id == None)  # noqa: E711
            .scalar()
            or 0
        )
        all_user_ids = db.query(User.id).subquery()
        orphaned_alarms = (
            db.query(func.count(Alarm.id))
            .filter(~Alarm.user_id.in_(db.query(all_user_ids)))
            .scalar()
            or 0
        )

        is_empty = wake_events == 0 and challenge_attempts == 0 and new_users == 0
        insights: List[str] = []
        if engaged_users:
            insights.append(
                f"{engaged_users} engaged user(s) "
                f"({_safe_division(engaged_users, total_users, 1) * 100:.1f}% of platform)."
            )
        if challenge_attempts:
            insights.append(
                f"Challenge accuracy: "
                f"{_safe_division(correct_challenges, challenge_attempts, 1) * 100:.1f}% "
                f"across {challenge_attempts} attempt(s)."
            )
        if users_without_profiles or orphaned_alarms:
            insights.append(
                f"Integrity: {users_without_profiles} user(s) missing profiles, "
                f"{orphaned_alarms} orphaned alarm(s)."
            )
        else:
            insights.append("Data integrity checks passed with no issues found.")

        sections = {
            "summary": {
                "total_users": total_users,
                "new_users_in_period": new_users,
                "engaged_users": engaged_users,
                "wake_events": wake_events,
                "verified_wakes": verified_wakes,
                "wake_success_rate_pct": _safe_division(verified_wakes, wake_events, 1)
                * 100,
                "challenge_attempts": challenge_attempts,
                "challenge_accuracy_pct": (
                    _safe_division(correct_challenges, challenge_attempts, 1) * 100
                ),
                "total_snoozes": snoozes,
                "analytics_events": analytics_events,
                "integrity_issues": users_without_profiles + orphaned_alarms,
                "redis_enabled": bool(settings.REDIS_ENABLED),
                "database_total_rows": sum(table_counts.values()),
            },
            "challenge_performance": {
                "total_attempts": challenge_attempts,
                "total_correct": correct_challenges,
                "by_type": by_type,
            },
            "database": {
                "table_row_counts": table_counts,
                "total_rows": sum(table_counts.values()),
            },
            "data_integrity": {
                "users_without_profiles": users_without_profiles,
                "orphaned_alarms": orphaned_alarms,
                "issues_found": users_without_profiles + orphaned_alarms,
            },
            "configuration": {
                "project_name": settings.PROJECT_NAME,
                "version": settings.VERSION,
                "redis_enabled": settings.REDIS_ENABLED,
                "database_type": (
                    "sqlite" if "sqlite" in settings.DATABASE_URL else "other"
                ),
            },
            "tables": [
                {
                    "title": "Database Table Counts",
                    "headers": ["Table", "Rows"],
                    "rows": [[k, v] for k, v in table_counts.items()],
                },
            ],
        }
        return sections, insights, is_empty
