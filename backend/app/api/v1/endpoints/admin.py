"""
Admin API endpoints.

Provides admin-only endpoints for platform management, monitoring, and
reporting.  All endpoints require ``ADMIN`` role via the centralised
``get_current_admin`` dependency — no duplicate role checkers are created.

Endpoints:
    GET /admin/dashboard          — enhanced admin dashboard summary
    GET /admin/users              — paginated, filterable user list with stats
    GET /admin/users/{user_id}    — deep user detail with profile & activity
    GET /admin/statistics         — platform-wide growth & engagement metrics
    GET /admin/recommendations    — recommendation signal monitoring
    GET /admin/alarms             — cross-user alarm monitoring
    GET /admin/analytics          — analytics event overview
    GET /admin/reports            — system health & audit report
    GET /admin/system-reports                 — list system report types
    GET /admin/system-reports/{type}          — generate User/Alarm/Habit/Platform report
    GET /admin/system-reports/{type}/export   — PDF or Excel download
    GET /admin/notification-settings          — platform notification / ops settings
    PUT /admin/notification-settings          — update platform notification settings
    POST /admin/announcements/broadcast       — broadcast announcement to all users
    GET /admin/coach-assignments              — list coach/client assignments
    POST /admin/coach-assignments             — assign a client to a wellness coach
    DELETE /admin/coach-assignments           — remove a client from a coach
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import and_, case, extract, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.challenge_session import ChallengeSession
from app.models.profile import UserProfile
from app.models.user import User, UserRole
from app.schemas.coach import (
    CoachAssignmentCreate,
    CoachAssignmentListResponse,
    CoachAssignmentResponse,
)
from app.schemas.report import ReportResponse, ReportTypeListResponse
from app.schemas.system_settings import (
    BroadcastAnnouncementRequest,
    BroadcastAnnouncementResponse,
    SystemNotificationSettingsResponse,
    SystemNotificationSettingsUpdate,
)
from app.services.coach_service import CoachService
from app.services.habit_score import calculate_habit_score
from app.services.report_export import export_report
from app.services.report_service import resolve_date_window
from app.services.system_report_service import SystemReportService, SystemReportType
from app.services.system_settings_service import SystemSettingsService

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a stored (UTC-naive) datetime with an explicit UTC offset."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _safe_division(numerator: float, denominator: float, decimals: int = 1) -> float:
    """Return rounded division result, or 0.0 if denominator is zero."""
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, decimals)


def _lookback_start(days: int) -> datetime:
    """Return the UTC datetime marking the start of the lookback window.

    ``days=N`` covers N calendar days ending today (inclusive).
    """
    return (
        datetime.now(timezone.utc) - timedelta(days=max(1, days) - 1)
    ).replace(hour=0, minute=0, second=0, microsecond=0)


def _resolve_admin_window(
    days: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[datetime, datetime, int]:
    """Resolve an admin analytics window from days or explicit dates."""
    try:
        return resolve_date_window(
            days=days, start_date=start_date, end_date=end_date
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _in_window(column, window_start: datetime, window_end: datetime):
    """SQLAlchemy filter for an inclusive datetime window."""
    return and_(column >= window_start, column <= window_end)


def _daily_trend(
    db: Session,
    column,
    window_start: datetime,
    days: int,
    value_key: str,
) -> list:
    """Build a zero-filled per-day count series with a single grouped query.

    Replaces the previous one-COUNT-per-day loop, which issued up to 365
    round-trips per request. Bucketing happens in the database on the stored
    UTC calendar date, which matches the ``[day_start, day_end)`` windows the
    loop used.
    """
    trend_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    trend_end = trend_start + timedelta(days=days)

    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        day_expr = func.to_char(column, "YYYY-MM-DD")
    else:
        day_expr = func.strftime("%Y-%m-%d", column)

    counts = dict(
        db.query(day_expr.label("day"), func.count())
        .filter(column >= trend_start, column < trend_end)
        .group_by("day")
        .all()
    )

    return [
        {
            "date": day,
            value_key: int(counts.get(day, 0)),
        }
        for day in (
            (trend_start + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        )
    ]


def _hour_weekday_exprs(db: Session, column):
    """Dialect-aware SQL extraction of hour-of-day and weekday from ``column``.

    Both dialects number the weekday from Sunday=0, so callers translate it to
    the Monday-first index the API returns. Datetimes are stored naive UTC, so
    these extract exactly what ``datetime.hour`` / ``.weekday()`` used to.
    """
    if db.get_bind().dialect.name == "postgresql":
        return extract("hour", column), extract("dow", column)
    return func.strftime("%H", column), func.strftime("%w", column)


# ── 1. GET /admin/dashboard — Enhanced Dashboard Summary ────────────────


@router.get(
    "/dashboard",
    summary="Enhanced admin dashboard statistics",
)
def admin_dashboard(
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return comprehensive admin dashboard statistics.

    Includes user counts, growth metrics, role distribution, engagement
    summary, top performers, and alarm overview.  Only accessible to
    ``ADMIN`` users.
    """
    now = datetime.now(timezone.utc)
    window_start, window_end, days = _resolve_admin_window(
        days=days, start_date=start_date, end_date=end_date
    )

    # ── User counts & role distribution ──
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

    role_distribution = {}
    role_counts = (
        db.query(User.role, func.count(User.id))
        .group_by(User.role)
        .all()
    )
    for role, count in role_counts:
        role_distribution[role.value if hasattr(role, "value") else str(role)] = count

    # ── User growth (new registrations in period) ──
    new_users_in_period = (
        db.query(func.count(User.id))
        .filter(_in_window(User.created_at, window_start, window_end))
        .scalar()
        or 0
    )
    # Previous period for comparison
    prev_start = window_start - timedelta(days=days)
    new_users_prev = (
        db.query(func.count(User.id))
        .filter(User.created_at >= prev_start, User.created_at < window_start)
        .scalar()
        or 0
    )
    growth_rate = _safe_division(
        (new_users_in_period - new_users_prev), max(new_users_prev, 1), 1
    ) * 100

    # ── Alarm overview ──
    total_alarms = db.query(func.count(Alarm.id)).scalar() or 0
    active_alarms = (
        db.query(func.count(Alarm.id))
        .filter(Alarm.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )

    # ── Engagement: wake events & challenge logs in period ──
    wake_events_in_period = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
        .scalar()
        or 0
    )
    verified_wakes_in_period = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(
            _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
            AlarmWakeEvent.verified == True,  # noqa: E712
        )
        .scalar()
        or 0
    )
    challenge_attempts_in_period = (
        db.query(func.count(AlarmChallengeLog.id))
        .filter(_in_window(AlarmChallengeLog.created_at, window_start, window_end))
        .scalar()
        or 0
    )
    correct_challenges_in_period = (
        db.query(func.count(AlarmChallengeLog.id))
        .filter(
            _in_window(AlarmChallengeLog.created_at, window_start, window_end),
            AlarmChallengeLog.is_correct == True,  # noqa: E712
        )
        .scalar()
        or 0
    )
    snooze_events_in_period = (
        db.query(func.count(AlarmSnoozeEvent.id))
        .filter(_in_window(AlarmSnoozeEvent.created_at, window_start, window_end))
        .scalar()
        or 0
    )

    # ── Active users in period (users with at least 1 wake event) ──
    engaged_users = (
        db.query(func.count(func.distinct(AlarmWakeEvent.user_id)))
        .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
        .scalar()
        or 0
    )

    # ── Top 5 performers by verified wakes in period ──
    top_performers_query = (
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
        .limit(5)
        .all()
    )
    top_performers = [
        {
            "user_id": uid,
            "username": uname,
            "email": email,
            "verified_wakes": vw,
        }
        for uid, uname, email, vw in top_performers_query
    ]

    # ── Per-user alarm counts (original behaviour preserved) ──
    user_alarm_counts = (
        db.query(User, func.count(Alarm.id).label("alarm_count"))
        .outerjoin(Alarm, Alarm.user_id == User.id)
        .group_by(User.id)
        .all()
    )

    users_summary = []
    for user_obj, alarm_count in user_alarm_counts:
        users_summary.append({
            "id": user_obj.id,
            "email": user_obj.email,
            "username": user_obj.username,
            "full_name": user_obj.full_name,
            "role": user_obj.role.value if hasattr(user_obj.role, "value") else str(user_obj.role),
            "is_active": user_obj.is_active,
            "created_at": _utc_isoformat(user_obj.created_at),
            "total_alarms": alarm_count,
        })

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "period": {
            "start_date": window_start.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "days": days,
        },
        # User overview
        "total_users": total_users,
        "active_users": active_users,
        "verified_users": verified_users,
        "role_distribution": role_distribution,
        # Growth
        "new_users_in_period": new_users_in_period,
        "new_users_previous_period": new_users_prev,
        "user_growth_rate_pct": growth_rate,
        # Alarm overview
        "total_alarms": total_alarms,
        "active_alarms": active_alarms,
        # Engagement
        "engagement": {
            "engaged_users": engaged_users,
            "engagement_rate_pct": _safe_division(engaged_users, total_users, 1) * 100 if total_users else 0.0,
            "wake_events": wake_events_in_period,
            "verified_wakes": verified_wakes_in_period,
            "wake_success_rate_pct": _safe_division(verified_wakes_in_period, wake_events_in_period, 1) * 100,
            "challenge_attempts": challenge_attempts_in_period,
            "challenge_accuracy_pct": _safe_division(correct_challenges_in_period, challenge_attempts_in_period, 1) * 100,
            "total_snoozes": snooze_events_in_period,
        },
        "top_performers": top_performers,
        # Per-user breakdown (original)
        "users": users_summary,
    }


# ── 2. GET /admin/users — Paginated, Filterable User List ───────────────


@router.get(
    "/users",
    summary="Paginated admin user list with aggregated stats",
)
def admin_list_users(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    role: Optional[str] = Query(None, description="Filter by role: user, wellness_coach, admin"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, max_length=100, description="Search by email or username"),
    sort_by: str = Query(
        "created_at",
        description=(
            "Sort field: created_at, email, username, full_name, role, "
            "is_active, is_verified, total_alarms, verified_wakes"
        ),
        pattern=(
            "^(created_at|email|username|full_name|role|is_active"
            "|is_verified|total_alarms|verified_wakes)$"
        ),
    ),
    sort_order: str = Query(
        "desc",
        description="Sort order: asc or desc",
        pattern="^(asc|desc)$",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return a paginated, filterable user list with per-user alarm and
    wake-event counts.  Provides richer aggregation than the standard
    ``GET /users/`` CRUD list.
    """
    # ── Validate role filter ──
    if role is not None:
        valid_roles = {r.value for r in UserRole}
        if role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role filter: '{role}'. Must be one of: {', '.join(sorted(valid_roles))}",
            )

    # ── Base query ──
    query = db.query(User)

    if role is not None:
        query = query.filter(User.role == UserRole(role))
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (User.email.ilike(pattern)) | (User.username.ilike(pattern))
        )

    # ── Count total before pagination ──
    total = query.count()

    # ── Sorting ──
    # Aggregate sort keys join a grouped subquery so ordering happens in SQL
    # and stays correct across pages (a page-local sort would not).
    if sort_by == "total_alarms":
        alarm_totals = (
            db.query(
                Alarm.user_id.label("user_id"),
                func.count(Alarm.id).label("value"),
            )
            .group_by(Alarm.user_id)
            .subquery()
        )
        query = query.outerjoin(alarm_totals, alarm_totals.c.user_id == User.id)
        sort_column = func.coalesce(alarm_totals.c.value, 0)
    elif sort_by == "verified_wakes":
        wake_totals = (
            db.query(
                AlarmWakeEvent.user_id.label("user_id"),
                func.count(AlarmWakeEvent.id).label("value"),
            )
            .filter(AlarmWakeEvent.verified == True)  # noqa: E712
            .group_by(AlarmWakeEvent.user_id)
            .subquery()
        )
        query = query.outerjoin(wake_totals, wake_totals.c.user_id == User.id)
        sort_column = func.coalesce(wake_totals.c.value, 0)
    else:
        sort_column = {
            "created_at": User.created_at,
            "email": User.email,
            "username": User.username,
            "full_name": User.full_name,
            "role": User.role,
            "is_active": User.is_active,
            "is_verified": User.is_verified,
        }.get(sort_by, User.created_at)

    # User.id is a deterministic tiebreaker so pagination never repeats or
    # drops rows when the primary sort key has duplicates.
    if sort_order == "asc":
        query = query.order_by(sort_column.asc(), User.id.asc())
    else:
        query = query.order_by(sort_column.desc(), User.id.desc())

    # ── Paginate ──
    offset = (page - 1) * per_page
    users = query.offset(offset).limit(per_page).all()

    # ── Enrich with per-user aggregates ──
    user_ids = [u.id for u in users]
    alarm_counts = {}
    wake_counts = {}

    if user_ids:
        # Alarm counts per user
        alarm_agg = (
            db.query(Alarm.user_id, func.count(Alarm.id))
            .filter(Alarm.user_id.in_(user_ids))
            .group_by(Alarm.user_id)
            .all()
        )
        alarm_counts = {uid: cnt for uid, cnt in alarm_agg}

        # Verified wake counts per user
        wake_agg = (
            db.query(AlarmWakeEvent.user_id, func.count(AlarmWakeEvent.id))
            .filter(
                AlarmWakeEvent.user_id.in_(user_ids),
                AlarmWakeEvent.verified == True,  # noqa: E712
            )
            .group_by(AlarmWakeEvent.user_id)
            .all()
        )
        wake_counts = {uid: cnt for uid, cnt in wake_agg}

    result = []
    for u in users:
        result.append({
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_active": u.is_active,
            "is_verified": u.is_verified,
            "created_at": _utc_isoformat(u.created_at),
            "updated_at": _utc_isoformat(u.updated_at),
            "total_alarms": alarm_counts.get(u.id, 0),
            "verified_wakes": wake_counts.get(u.id, 0),
        })

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),  # ceil division
        "users": result,
    }


# ── 3. GET /admin/users/{user_id} — Deep User Detail ────────────────────


@router.get(
    "/users/{user_id}",
    summary="Admin deep user detail",
)
def admin_get_user_detail(
    user_id: int,
    days: int = Query(30, ge=1, le=365, description="Activity lookback in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return comprehensive read-only detail for a specific user, including
    profile data, alarm summary, challenge performance, and streak info.

    This is a read-only view — write operations (role change, deactivation)
    remain on the existing ``PUT /users/{user_id}`` and
    ``POST /users/{user_id}/deactivate`` endpoints.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    cutoff = _lookback_start(days)

    # Profile
    profile = (
        db.query(UserProfile)
        .filter(UserProfile.user_id == user_id)
        .first()
    )

    # Alarm summary
    total_alarms = (
        db.query(func.count(Alarm.id))
        .filter(Alarm.user_id == user_id)
        .scalar()
        or 0
    )
    active_alarms = (
        db.query(func.count(Alarm.id))
        .filter(Alarm.user_id == user_id, Alarm.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )

    # Wake events in period
    total_wakes = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(
            AlarmWakeEvent.user_id == user_id,
            AlarmWakeEvent.dismissed_at >= cutoff,
        )
        .scalar()
        or 0
    )
    verified_wakes = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(
            AlarmWakeEvent.user_id == user_id,
            AlarmWakeEvent.dismissed_at >= cutoff,
            AlarmWakeEvent.verified == True,  # noqa: E712
        )
        .scalar()
        or 0
    )

    # Challenge performance in period
    challenge_total = (
        db.query(func.count(AlarmChallengeLog.id))
        .filter(
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= cutoff,
        )
        .scalar()
        or 0
    )
    challenge_correct = (
        db.query(func.count(AlarmChallengeLog.id))
        .filter(
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= cutoff,
            AlarmChallengeLog.is_correct == True,  # noqa: E712
        )
        .scalar()
        or 0
    )
    total_points = (
        db.query(func.coalesce(func.sum(AlarmChallengeLog.points_earned), 0))
        .filter(
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

    # Snooze count in period
    snooze_count = (
        db.query(func.count(AlarmSnoozeEvent.id))
        .filter(
            AlarmSnoozeEvent.user_id == user_id,
            AlarmSnoozeEvent.created_at >= cutoff,
        )
        .scalar()
        or 0
    )

    # Profile data
    profile_data = None
    if profile:
        wake = profile.preferred_wake_time
        profile_data = {
            "timezone": profile.timezone,
            "sleep_duration_hours": profile.sleep_duration_hours,
            "preferred_wake_time": wake.strftime("%H:%M:%S") if wake else None,
            "difficulty_preference": (
                profile.difficulty_preference.value
                if profile.difficulty_preference
                else None
            ),
            "adapted_difficulty": (
                profile.adapted_difficulty.value
                if profile.adapted_difficulty
                else None
            ),
            "streak_days": profile.streak_days,
            "best_streak": profile.best_streak,
            "consecutive_success_streak": profile.consecutive_success_streak,
            "consecutive_failure_streak": profile.consecutive_failure_streak,
            "wake_up_consistency_score": profile.wake_up_consistency_score,
            "total_alarms_dismissed": profile.total_alarms_dismissed,
            "total_snoozes": profile.total_snoozes,
            "last_successful_wake_date": (
                profile.last_successful_wake_date.isoformat()
                if profile.last_successful_wake_date
                else None
            ),
        }

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "created_at": _utc_isoformat(user.created_at),
            "updated_at": _utc_isoformat(user.updated_at),
        },
        "profile": profile_data,
        "period_days": days,
        "alarms": {
            "total": total_alarms,
            "active": active_alarms,
        },
        "activity": {
            "wake_events": total_wakes,
            "verified_wakes": verified_wakes,
            "wake_success_rate_pct": _safe_division(verified_wakes, total_wakes, 1) * 100,
            "challenge_attempts": challenge_total,
            "challenge_correct": challenge_correct,
            "challenge_accuracy_pct": _safe_division(challenge_correct, challenge_total, 1) * 100,
            "total_points_earned": total_points,
            "snooze_count": snooze_count,
        },
    }


# ── 4. GET /admin/statistics — Platform-Wide Statistics ──────────────────


@router.get(
    "/statistics",
    summary="Platform-wide statistics and growth trends",
)
def admin_statistics(
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return platform-wide statistics including registration trends,
    activity distributions, challenge performance breakdown, and growth
    trajectory over the lookback period.
    """
    now = datetime.now(timezone.utc)
    window_start, window_end, days = _resolve_admin_window(
        days=days, start_date=start_date, end_date=end_date
    )

    # ── Registration trend (daily counts in period) ──
    registration_trend = _daily_trend(
        db, User.created_at, window_start, days, "registrations"
    )

    # ── Wake events: activity histograms + outcome breakdown (in period) ──
    # One grouped pass serves both. Extracting the hour and weekday in SQL is
    # what keeps a 365-day window off the row-streaming path: this previously
    # pulled every matching ``dismissed_at`` into Python just to bucket it.
    hour_expr, weekday_expr = _hour_weekday_exprs(db, AlarmWakeEvent.dismissed_at)

    by_hour: dict = {}
    by_weekday: dict = {}
    total_wakes = 0
    verified_wake_count = 0
    dismiss_methods: dict = {}
    dismiss_time_sum = 0
    dismiss_time_count = 0

    for hour, weekday, method, verified, count, time_sum, time_count in (
        db.query(
            hour_expr,
            weekday_expr,
            AlarmWakeEvent.dismiss_method,
            AlarmWakeEvent.verified,
            # count(*) rather than count(id): the id column is not part of the
            # covering index, and referencing it would forfeit the index-only scan.
            func.count(),
            func.coalesce(func.sum(AlarmWakeEvent.time_to_dismiss_seconds), 0),
            func.count(AlarmWakeEvent.time_to_dismiss_seconds),
        )
        .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
        .group_by(
            hour_expr,
            weekday_expr,
            AlarmWakeEvent.dismiss_method,
            AlarmWakeEvent.verified,
        )
        .all()
    ):
        count = int(count or 0)
        total_wakes += count
        key = method or "unknown"
        dismiss_methods[key] = dismiss_methods.get(key, 0) + count
        if verified:
            verified_wake_count += count
            dismiss_time_sum += int(time_sum or 0)
            dismiss_time_count += int(time_count or 0)

        h = int(hour)
        by_hour[h] = by_hour.get(h, 0) + count
        # Sunday-first in SQL, Monday-first in the response.
        wd = (int(weekday) + 6) % 7
        by_weekday[wd] = by_weekday.get(wd, 0) + count

    activity_by_hour = [
        {"hour": h, "count": by_hour.get(h, 0)} for h in range(24)
    ]
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    activity_by_weekday = [
        {"weekday": weekday_names[wd], "weekday_index": wd, "count": by_weekday.get(wd, 0)}
        for wd in range(7)
    ]

    avg_dismiss = (
        round(dismiss_time_sum / dismiss_time_count, 1)
        if dismiss_time_count
        else None
    )

    # ── Challenge breakdown (in period) ──
    # Grouped in SQL rather than by scanning every log row into Python.
    challenge_window = _in_window(
        AlarmChallengeLog.created_at, window_start, window_end
    )
    correct_sum = func.sum(
        case((AlarmChallengeLog.is_correct.is_(True), 1), else_=0)
    )

    # Grouping by type *and* difficulty in one pass feeds both breakdowns from
    # a single scan; they used to be two full scans of the same window.
    challenge_by_type: dict = {}
    challenge_by_difficulty: dict = {}
    for ct, diff, total, correct, points in (
        db.query(
            AlarmChallengeLog.challenge_type,
            AlarmChallengeLog.difficulty,
            func.count(),
            correct_sum,
            func.coalesce(func.sum(AlarmChallengeLog.points_earned), 0),
        )
        .filter(challenge_window)
        .group_by(
            AlarmChallengeLog.challenge_type, AlarmChallengeLog.difficulty
        )
        .all()
    ):
        total = int(total or 0)
        correct = int(correct or 0)

        bucket = challenge_by_type.setdefault(
            ct or "unknown", {"total": 0, "correct": 0, "points": 0}
        )
        bucket["total"] += total
        bucket["correct"] += correct
        bucket["points"] += int(points or 0)

        diff_bucket = challenge_by_difficulty.setdefault(
            diff or "unknown", {"total": 0, "correct": 0}
        )
        diff_bucket["total"] += total
        diff_bucket["correct"] += correct

    for ct_data in challenge_by_type.values():
        ct_data["accuracy_pct"] = _safe_division(
            ct_data["correct"], ct_data["total"], 1
        ) * 100

    for diff_data in challenge_by_difficulty.values():
        diff_data["accuracy_pct"] = _safe_division(
            diff_data["correct"], diff_data["total"], 1
        ) * 100

    total_challenge_attempts = sum(
        d["total"] for d in challenge_by_type.values()
    )
    total_challenge_correct = sum(
        d["correct"] for d in challenge_by_type.values()
    )

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "period": {
            "start_date": window_start.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "days": days,
        },
        "registration_trend": registration_trend,
        "activity_by_hour": activity_by_hour,
        "activity_by_weekday": activity_by_weekday,
        "challenge_performance": {
            "total_attempts": total_challenge_attempts,
            "total_correct": total_challenge_correct,
            "overall_accuracy_pct": _safe_division(
                total_challenge_correct,
                total_challenge_attempts,
                1,
            ) * 100,
            "total_points_awarded": sum(d["points"] for d in challenge_by_type.values()),
            "by_type": challenge_by_type,
            "by_difficulty": challenge_by_difficulty,
        },
        "wake_events": {
            "total": total_wakes,
            "verified": verified_wake_count,
            "abandoned": total_wakes - verified_wake_count,
            "success_rate_pct": _safe_division(
                verified_wake_count, total_wakes, 1
            ) * 100,
            "avg_dismiss_seconds": avg_dismiss,
            "by_dismiss_method": dismiss_methods,
        },
    }


# ── 5. GET /admin/recommendations — Recommendation Monitoring ───────────


@router.get(
    "/recommendations",
    summary="Recommendation monitoring and signal overview",
)
def admin_recommendations(
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return a monitoring overview of recommendation signals across all
    users.  Summarises profile-level metrics (habit scores, streaks,
    consistency) that drive the recommendation engine — without generating
    full recommendation payloads.
    """
    now = datetime.now(timezone.utc)
    window_start, window_end, days = _resolve_admin_window(
        days=days, start_date=start_date, end_date=end_date
    )

    # ── Profile signal distribution ──
    profiles = db.query(UserProfile).all()
    total_profiles = len(profiles)

    if not profiles:
        return {
            "generated_at": now.isoformat(),
            "period_days": days,
            "period": {
                "start_date": window_start.date().isoformat(),
                "end_date": window_end.date().isoformat(),
                "days": days,
            },
            "total_profiles": 0,
            "signal_summary": {},
            "difficulty_distribution": {},
            "streak_summary": {},
            "consistency_summary": {},
            "habit_score_overview": {},
        }

    # Difficulty distribution
    difficulty_dist: dict = {}
    for p in profiles:
        diff = (
            p.difficulty_preference.value
            if p.difficulty_preference
            else "unknown"
        )
        difficulty_dist[diff] = difficulty_dist.get(diff, 0) + 1

    # Adapted difficulty distribution
    adapted_dist: dict = {}
    for p in profiles:
        ad = (
            p.adapted_difficulty.value
            if p.adapted_difficulty
            else "unknown"
        )
        adapted_dist[ad] = adapted_dist.get(ad, 0) + 1

    # Streak statistics
    streak_values = [p.streak_days or 0 for p in profiles]
    best_streak_values = [p.best_streak or 0 for p in profiles]
    success_streak_values = [p.consecutive_success_streak or 0 for p in profiles]
    failure_streak_values = [p.consecutive_failure_streak or 0 for p in profiles]

    # Consistency scores
    consistency_scores = [p.wake_up_consistency_score or 0.0 for p in profiles]

    # Habit score overview (profile-counter path — platform aggregate, not per-user SSOT replay)
    habit_scores = []
    breakdown_sums = {
        "wake_up_consistency": 0.0,
        "challenge_completion": 0.0,
        "snooze_reduction": 0.0,
        "sleep_adherence": 0.0,
    }
    for p in profiles:
        score_data = calculate_habit_score(p)
        habit_scores.append(float(score_data.get("habit_score", 0.0)))
        breakdown = score_data.get("breakdown") or {}
        for key in breakdown_sums:
            breakdown_sums[key] += float(breakdown.get(key, 0.0) or 0.0)

    # Users with goals set
    users_with_goals = sum(
        1 for p in profiles
        if p.productivity_goals and (
            (isinstance(p.productivity_goals, list) and len(p.productivity_goals) > 0)
            or (isinstance(p.productivity_goals, str) and p.productivity_goals.strip())
        )
    )

    # Users with preferred wake time set
    users_with_wake_time = sum(
        1 for p in profiles if p.preferred_wake_time is not None
    )

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "period": {
            "start_date": window_start.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "days": days,
        },
        "total_profiles": total_profiles,
        "signal_summary": {
            "users_with_wake_time": users_with_wake_time,
            "users_with_goals": users_with_goals,
            "avg_sleep_duration_hours": round(
                sum(p.sleep_duration_hours or 0 for p in profiles) / total_profiles, 1
            ),
            "avg_total_dismissals": round(
                sum(p.total_alarms_dismissed or 0 for p in profiles) / total_profiles, 1
            ),
            "avg_total_snoozes": round(
                sum(p.total_snoozes or 0 for p in profiles) / total_profiles, 1
            ),
        },
        "difficulty_distribution": {
            "user_preference": difficulty_dist,
            "adapted": adapted_dist,
        },
        "streak_summary": {
            "avg_current_streak": round(sum(streak_values) / total_profiles, 1),
            "max_current_streak": max(streak_values),
            "avg_best_streak": round(sum(best_streak_values) / total_profiles, 1),
            "max_best_streak": max(best_streak_values),
            "avg_success_streak": round(sum(success_streak_values) / total_profiles, 1),
            "max_success_streak": max(success_streak_values),
            "avg_failure_streak": round(sum(failure_streak_values) / total_profiles, 1),
            "max_failure_streak": max(failure_streak_values),
        },
        "consistency_summary": {
            "avg_consistency_score": round(sum(consistency_scores) / total_profiles, 1),
            "min_consistency_score": round(min(consistency_scores), 1),
            "max_consistency_score": round(max(consistency_scores), 1),
            "users_above_80": sum(1 for s in consistency_scores if s >= 80),
            "users_below_30": sum(1 for s in consistency_scores if s < 30),
        },
        "habit_score_overview": {
            "avg_habit_score": round(sum(habit_scores) / total_profiles, 1),
            "min_habit_score": round(min(habit_scores), 1),
            "max_habit_score": round(max(habit_scores), 1),
            "users_above_70": sum(1 for s in habit_scores if s >= 70),
            "users_below_40": sum(1 for s in habit_scores if s < 40),
            "avg_breakdown": {
                key: round(val / total_profiles, 1)
                for key, val in breakdown_sums.items()
            },
        },
    }


# ── 6. GET /admin/alarms — Cross-User Alarm Monitoring ──────────────────


@router.get(
    "/alarms",
    summary="Cross-user alarm monitoring",
)
def admin_alarms(
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return platform-wide alarm monitoring data: type distribution,
    challenge configuration stats, snooze/dismiss rates, and top alarms
    by activity.
    """
    now = datetime.now(timezone.utc)
    window_start, window_end, days = _resolve_admin_window(
        days=days, start_date=start_date, end_date=end_date
    )

    # ── Total alarm counts ──
    total_alarms = db.query(func.count(Alarm.id)).scalar() or 0
    active_alarms = (
        db.query(func.count(Alarm.id))
        .filter(Alarm.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )

    # ── Alarm type distribution ──
    type_dist_query = (
        db.query(Alarm.alarm_type, func.count(Alarm.id))
        .group_by(Alarm.alarm_type)
        .all()
    )
    type_distribution = {}
    for atype, cnt in type_dist_query:
        key = atype.value if hasattr(atype, "value") else str(atype)
        type_distribution[key] = cnt

    # ── Challenge type distribution ──
    ctype_dist_query = (
        db.query(Alarm.challenge_type, func.count(Alarm.id))
        .group_by(Alarm.challenge_type)
        .all()
    )
    challenge_type_distribution = {}
    for ctype, cnt in ctype_dist_query:
        key = ctype.value if hasattr(ctype, "value") else str(ctype)
        challenge_type_distribution[key] = cnt

    # ── Snooze configuration stats ──
    avg_snooze_limit = (
        db.query(func.avg(Alarm.snooze_limit)).scalar() or 0.0
    )
    avg_snooze_interval = (
        db.query(func.avg(Alarm.snooze_interval_minutes)).scalar() or 0.0
    )
    avg_challenge_count = (
        db.query(func.avg(Alarm.challenge_count)).scalar() or 0.0
    )

    # ── Activity in period ──
    # Total dismissals in period (from wake events)
    wake_events_total = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(_in_window(AlarmWakeEvent.dismissed_at, window_start, window_end))
        .scalar()
        or 0
    )
    verified_total = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(
            _in_window(AlarmWakeEvent.dismissed_at, window_start, window_end),
            AlarmWakeEvent.verified == True,  # noqa: E712
        )
        .scalar()
        or 0
    )
    snooze_total = (
        db.query(func.count(AlarmSnoozeEvent.id))
        .filter(_in_window(AlarmSnoozeEvent.created_at, window_start, window_end))
        .scalar()
        or 0
    )

    # ── Top 10 most active alarms (by wake events in period) ──
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

    # ── Difficulty distribution (configured on alarms) ──
    diff_dist_query = (
        db.query(Alarm.challenge_difficulty, func.count(Alarm.id))
        .group_by(Alarm.challenge_difficulty)
        .all()
    )
    difficulty_distribution = {diff: cnt for diff, cnt in diff_dist_query}

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "period": {
            "start_date": window_start.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "days": days,
        },
        "total_alarms": total_alarms,
        "active_alarms": active_alarms,
        "inactive_alarms": total_alarms - active_alarms,
        "type_distribution": type_distribution,
        "challenge_type_distribution": challenge_type_distribution,
        "difficulty_distribution": difficulty_distribution,
        "configuration": {
            "avg_snooze_limit": round(avg_snooze_limit, 1),
            "avg_snooze_interval_minutes": round(avg_snooze_interval, 1),
            "avg_challenge_count": round(avg_challenge_count, 1),
        },
        "period_activity": {
            "wake_events": wake_events_total,
            "verified_wakes": verified_total,
            "abandoned_wakes": wake_events_total - verified_total,
            "success_rate_pct": _safe_division(verified_total, wake_events_total, 1) * 100,
            "snooze_events": snooze_total,
            "snooze_per_wake": _safe_division(snooze_total, wake_events_total, 2),
        },
        "top_active_alarms": top_alarms,
    }


# ── 7. GET /admin/analytics — Analytics Event Overview ───────────────────


@router.get(
    "/analytics",
    summary="Platform analytics event overview",
)
def admin_analytics(
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return a platform-wide overview of analytics events: total counts,
    type distribution, source breakdown, and ingestion trend.
    """
    now = datetime.now(timezone.utc)
    window_start, window_end, days = _resolve_admin_window(
        days=days, start_date=start_date, end_date=end_date
    )

    # ── Total events ──
    total_events = db.query(func.count(AnalyticsEvent.id)).scalar() or 0
    events_in_period = (
        db.query(func.count(AnalyticsEvent.id))
        .filter(_in_window(AnalyticsEvent.created_at, window_start, window_end))
        .scalar()
        or 0
    )

    # ── Event type distribution (in period) ──
    type_dist_query = (
        db.query(AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
        .filter(_in_window(AnalyticsEvent.created_at, window_start, window_end))
        .group_by(AnalyticsEvent.event_type)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .all()
    )
    by_event_type = [
        {"event_type": etype, "count": cnt}
        for etype, cnt in type_dist_query
    ]

    # ── Source breakdown (in period) ──
    source_dist_query = (
        db.query(AnalyticsEvent.source, func.count(AnalyticsEvent.id))
        .filter(_in_window(AnalyticsEvent.created_at, window_start, window_end))
        .group_by(AnalyticsEvent.source)
        .all()
    )
    by_source = {src: cnt for src, cnt in source_dist_query}

    # ── Entity type breakdown (in period) ──
    entity_dist_query = (
        db.query(AnalyticsEvent.entity_type, func.count(AnalyticsEvent.id))
        .filter(
            _in_window(AnalyticsEvent.created_at, window_start, window_end),
            AnalyticsEvent.entity_type != None,  # noqa: E711
        )
        .group_by(AnalyticsEvent.entity_type)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .all()
    )
    by_entity_type = {etype: cnt for etype, cnt in entity_dist_query}

    # ── Unique users who generated events in period ──
    unique_event_users = (
        db.query(func.count(func.distinct(AnalyticsEvent.user_id)))
        .filter(_in_window(AnalyticsEvent.created_at, window_start, window_end))
        .scalar()
        or 0
    )

    # ── Daily ingestion trend (full selected window) ──
    ingestion_trend = _daily_trend(
        db, AnalyticsEvent.created_at, window_start, days, "events"
    )

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "period": {
            "start_date": window_start.date().isoformat(),
            "end_date": window_end.date().isoformat(),
            "days": days,
        },
        "total_events_all_time": total_events,
        "events_in_period": events_in_period,
        "avg_events_per_day": _safe_division(events_in_period, days, 1),
        "unique_users": unique_event_users,
        "by_event_type": by_event_type,
        "by_source": by_source,
        "by_entity_type": by_entity_type,
        "ingestion_trend": ingestion_trend,
    }


# ── 8. GET /admin/reports — System Health & Audit Report ─────────────────


@router.get(
    "/reports",
    summary="System health and audit report",
)
def admin_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return a system health report including database table row counts,
    configuration summary (non-sensitive), and data integrity metrics.
    """
    now = datetime.now(timezone.utc)

    # ── Table row counts ──
    table_counts = {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "user_profiles": db.query(func.count(UserProfile.id)).scalar() or 0,
        "alarms": db.query(func.count(Alarm.id)).scalar() or 0,
        "alarm_challenge_logs": db.query(func.count(AlarmChallengeLog.id)).scalar() or 0,
        "alarm_wake_events": db.query(func.count(AlarmWakeEvent.id)).scalar() or 0,
        "alarm_snooze_events": db.query(func.count(AlarmSnoozeEvent.id)).scalar() or 0,
        "analytics_events": db.query(func.count(AnalyticsEvent.id)).scalar() or 0,
        "challenge_sessions": db.query(func.count(ChallengeSession.id)).scalar() or 0,
    }

    # ── Data integrity checks ──
    # Users without profiles
    users_without_profiles = (
        db.query(func.count(User.id))
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .filter(UserProfile.id == None)  # noqa: E711
        .scalar()
        or 0
    )

    # Orphaned alarms (alarm.user_id pointing to non-existent user)
    # Using a subquery approach since SQLite doesn't support all join patterns
    all_user_ids = db.query(User.id).subquery()
    orphaned_alarms = (
        db.query(func.count(Alarm.id))
        .filter(~Alarm.user_id.in_(db.query(all_user_ids)))
        .scalar()
        or 0
    )

    # Active challenge sessions
    active_sessions = db.query(func.count(ChallengeSession.id)).scalar() or 0

    # ── Platform configuration (non-sensitive) ──
    config_summary = {
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "api_prefix": settings.API_V1_STR,
        "database_type": "sqlite" if "sqlite" in settings.DATABASE_URL else "other",
        "access_token_expire_minutes": settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        "refresh_token_expire_days": settings.REFRESH_TOKEN_EXPIRE_DAYS,
        "adaptive_streak_threshold": settings.ADAPTIVE_STREAK_THRESHOLD,
        "redis_enabled": settings.REDIS_ENABLED,
        "cors_origins_count": len(settings.CORS_ORIGINS),
        "smtp_configured": settings.SMTP_HOST is not None,
        "oauth_google_configured": settings.OAUTH2_GOOGLE_CLIENT_ID is not None,
    }

    # ── Recent activity summary (last 24h) ──
    last_24h = now - timedelta(hours=24)
    recent_signups = (
        db.query(func.count(User.id))
        .filter(User.created_at >= last_24h)
        .scalar()
        or 0
    )
    recent_wakes = (
        db.query(func.count(AlarmWakeEvent.id))
        .filter(AlarmWakeEvent.dismissed_at >= last_24h)
        .scalar()
        or 0
    )
    recent_challenges = (
        db.query(func.count(AlarmChallengeLog.id))
        .filter(AlarmChallengeLog.created_at >= last_24h)
        .scalar()
        or 0
    )

    return {
        "generated_at": now.isoformat(),
        "system": {
            "platform": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "status": "healthy",
        },
        "database": {
            "table_row_counts": table_counts,
            "total_rows": sum(table_counts.values()),
        },
        "data_integrity": {
            "users_without_profiles": users_without_profiles,
            "orphaned_alarms": orphaned_alarms,
            "active_challenge_sessions": active_sessions,
            "issues_found": users_without_profiles + orphaned_alarms,
        },
        "configuration": config_summary,
        "last_24h": {
            "new_signups": recent_signups,
            "wake_events": recent_wakes,
            "challenge_attempts": recent_challenges,
        },
    }


# ── 9. System Reports (User / Alarm / Habit / Platform) ──────────────────


def _parse_system_report_type(report_type: str) -> SystemReportType:
    try:
        return SystemReportType(report_type.lower())
    except ValueError as exc:
        allowed = ", ".join(rt.value for rt in SystemReportType)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown system report type '{report_type}'. Allowed: {allowed}",
        ) from exc


@router.get(
    "/system-reports",
    response_model=ReportTypeListResponse,
    summary="List available system report types",
)
def list_system_reports(
    current_user: User = Depends(get_current_admin),
):
    """Return User, Alarm, Habit, and Platform system report types."""
    return ReportTypeListResponse(reports=SystemReportService.list_report_types())


@router.get(
    "/system-reports/{report_type}",
    response_model=ReportResponse,
    summary="Generate a system report (JSON)",
)
def get_system_report(
    report_type: str,
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Lookback window in days (default 30)"
    ),
    start_date: Optional[date] = Query(
        None, description="Inclusive start date (YYYY-MM-DD); requires end_date"
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive end date (YYYY-MM-DD); requires start_date"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Build a date-scoped system report for admin preview."""
    rt = _parse_system_report_type(report_type)
    try:
        return SystemReportService.build_report(
            db,
            rt,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/system-reports/{report_type}/export",
    summary="Export a system report as PDF or Excel",
)
def export_system_report(
    report_type: str,
    format: str = Query(
        "pdf",
        pattern="^(pdf|excel|xlsx)$",
        description="Export format: pdf or excel",
    ),
    days: Optional[int] = Query(None, ge=1, le=365),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Download a formatted PDF or Excel system report."""
    rt = _parse_system_report_type(report_type)
    try:
        payload = SystemReportService.build_report(
            db,
            rt,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        content, media_type, filename = export_report(payload, format)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ── 10. Notification Settings & Broadcast ────────────────────────────────


@router.get(
    "/notification-settings",
    response_model=SystemNotificationSettingsResponse,
    summary="Get platform notification settings",
)
def get_notification_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return global email/push toggles, maintenance mode, and alert thresholds."""
    return SystemSettingsService.to_response_dict(db)


@router.put(
    "/notification-settings",
    response_model=SystemNotificationSettingsResponse,
    summary="Update platform notification settings",
)
def update_notification_settings(
    payload: SystemNotificationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Persist admin notification / ops settings to the database."""
    if not payload.model_dump(exclude_unset=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No settings fields provided",
        )
    row = SystemSettingsService.update(
        db, payload, updated_by_user_id=current_user.id
    )
    return SystemSettingsService.to_response_dict(db, row)


@router.post(
    "/announcements/broadcast",
    response_model=BroadcastAnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Broadcast announcement to all active users",
)
def broadcast_announcement(
    payload: BroadcastAnnouncementRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Create in-app (and optional push) announcement notifications for every active user."""
    result = SystemSettingsService.broadcast_announcement(
        db,
        title=payload.title.strip(),
        body=payload.body.strip(),
        send_push=payload.send_push,
        created_by_user_id=current_user.id,
    )
    return result


# ── 11. Coach/Client Assignments ─────────────────────────────────────────


@router.get(
    "/coach-assignments",
    response_model=CoachAssignmentListResponse,
    summary="List coach/client assignments",
)
def list_coach_assignments(
    coach_id: Optional[int] = Query(None, description="Filter by coach user id"),
    client_id: Optional[int] = Query(None, description="Filter by client user id"),
    is_active: Optional[bool] = Query(
        True, description="Filter by active status; omit for all"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Return the paginated coach/client assignment roster.

    Assignments are what scope a wellness coach's data access, so this is the
    control surface for that permission.
    """
    return CoachService.list_assignments(
        db,
        coach_id=coach_id,
        client_id=client_id,
        is_active=is_active,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/coach-assignments",
    response_model=CoachAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a client to a wellness coach",
)
def create_coach_assignment(
    payload: CoachAssignmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Assign a client to a coach, granting the coach access to their data.

    Re-assigning a previously removed pair reactivates the existing row so the
    coaching history is preserved.
    """
    try:
        assignment = CoachService.assign_client(
            db,
            coach_id=payload.coach_id,
            client_id=payload.client_id,
            assigned_by_user_id=current_user.id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    listing = CoachService.list_assignments(
        db,
        coach_id=assignment.coach_id,
        client_id=assignment.client_id,
        is_active=None,
        page=1,
        per_page=1,
    )
    return listing["assignments"][0]


@router.delete(
    "/coach-assignments",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a client from a wellness coach",
)
def delete_coach_assignment(
    coach_id: int = Query(..., description="Coach user id"),
    client_id: int = Query(..., description="Client user id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Deactivate an assignment, revoking the coach's access to that client.

    The row is kept (``is_active = False``) so past coaching relationships stay
    auditable.
    """
    removed = CoachService.unassign_client(
        db, coach_id=coach_id, client_id=client_id
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active assignment not found",
        )
    return None

