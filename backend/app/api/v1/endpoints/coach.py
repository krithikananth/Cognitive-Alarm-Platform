"""
Wellness Coach API endpoints.

Every route requires the ``wellness_coach`` role (admins are also allowed) via
the centralised ``get_current_coach`` dependency, and every client-scoped route
additionally resolves the client through ``CoachService.get_assigned_client``.
A coach therefore sees data for a user only when an active row exists in
``coach_assignments`` — an unassigned client id is indistinguishable from a
non-existent one (both 404).

Analytics payloads are produced by the same services that back the client's own
dashboard, so a coach and their client never see different numbers.

Endpoints:
    GET /coach/overview                                  — roster-wide KPIs
    GET /coach/clients                                   — paginated client list
    GET /coach/clients/{client_id}                        — single client detail
    GET /coach/clients/{client_id}/behavioral            — sleep/wake/habit trends
    GET /coach/clients/{client_id}/sleep-trends          — sleep schedule adherence
    GET /coach/clients/{client_id}/wake-consistency      — wake-up consistency
    GET /coach/clients/{client_id}/habit-score           — habit score + breakdown
    GET /coach/clients/{client_id}/challenge-performance — challenge performance
    GET /coach/clients/{client_id}/productivity          — productivity analytics
    GET /coach/clients/{client_id}/recommendations       — coaching recommendations
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_coach
from app.db.session import get_db
from app.models.alarm import Alarm
from app.models.profile import UserProfile
from app.models.user import User
from app.schemas.coach import (
    CoachClientAnalyticsResponse,
    CoachClientDetailResponse,
    CoachClientListResponse,
    CoachOverviewResponse,
)
from app.schemas.recommendation import RecommendationResponse
from app.services.behavioral_analytics_service import BehavioralAnalyticsService
from app.services.coach_service import (
    CLIENT_SORT_FIELDS,
    CLIENT_STATUS_FILTERS,
    CoachService,
)
from app.services.dashboard_aggregations import (
    compute_challenge_performance,
    compute_productivity_insights,
)
from app.services.habit_score import calculate_habit_score_for_user
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/coach", tags=["Wellness Coach"])

_SORT_FIELD_PATTERN = f"^({'|'.join(CLIENT_SORT_FIELDS)})$"
_STATUS_PATTERN = f"^({'|'.join(CLIENT_STATUS_FILTERS)})$"

# A coach reviews history, so the client's own 5-item dashboard list is short.
COACH_RECENT_ATTEMPTS = 10


def _resolve_client(db: Session, coach: User, client_id: int) -> User:
    """Return the assigned client or raise 404.

    A single 404 for both "not assigned to you" and "does not exist" keeps the
    endpoint from leaking the existence of users outside the coach's roster.
    """
    client = CoachService.get_assigned_client(db, coach.id, client_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found among your assigned clients",
        )
    return client


def _client_display_name(client: User) -> str:
    """Coach-facing label for a client."""
    return client.full_name or client.username


def _analytics_envelope(client: User, days: int, data: dict) -> dict:
    """Wrap a client-scoped analytics payload with its client context."""
    return {
        "client_id": client.id,
        "client_name": _client_display_name(client),
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


# ── 1. GET /coach/overview ──────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=CoachOverviewResponse,
    summary="Roster-wide KPIs across all assigned clients",
)
def coach_overview(
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return aggregate coaching KPIs for every client assigned to the coach.

    A coach with no assignments gets ``is_empty: true`` with zeroed counters
    rather than an error, so the dashboard can render an empty state.
    """
    return CoachService.roster_overview(db, current_user.id, days=days)


# ── 2. GET /coach/clients ───────────────────────────────────────────────


@router.get(
    "/clients",
    response_model=CoachClientListResponse,
    summary="Paginated list of the coach's assigned clients",
)
def list_coach_clients(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(
        None, max_length=100, description="Search by name, username, or email"
    ),
    status_filter: str = Query(
        "all",
        alias="status",
        description="Filter: all, needs_attention, on_track, inactive",
        pattern=_STATUS_PATTERN,
    ),
    sort_by: str = Query(
        "full_name",
        description=(
            "Sort field: full_name, username, email, assigned_at, habit_score, "
            "streak_days, wake_consistency, verified_wakes, challenge_accuracy, "
            "last_wake_at"
        ),
        pattern=_SORT_FIELD_PATTERN,
    ),
    sort_order: str = Query(
        "asc", description="Sort order: asc or desc", pattern="^(asc|desc)$"
    ),
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return the coach's client roster with per-client wellness aggregates.

    ``total_assigned`` is the unfiltered roster size, so the UI can tell
    "no clients assigned" apart from "no clients match this filter".
    """
    return CoachService.list_clients(
        db,
        current_user.id,
        page=page,
        per_page=per_page,
        search=search,
        status=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
        days=days,
    )


# ── 3. GET /coach/clients/{client_id} ───────────────────────────────────


@router.get(
    "/clients/{client_id}",
    response_model=CoachClientDetailResponse,
    summary="Detail for a single assigned client",
)
def get_coach_client(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return one client's roster row plus profile context."""
    client = _resolve_client(db, current_user, client_id)

    # Aggregate only this client — the detail view never needs the roster.
    roster = CoachService.build_roster(
        db, current_user.id, days=days, only_client_ids=[client.id]
    )
    row = next((r for r in roster if r["client_id"] == client.id), None)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found among your assigned clients",
        )

    profile = (
        db.query(UserProfile).filter(UserProfile.user_id == client.id).first()
    )
    total_alarms = (
        db.query(Alarm).filter(Alarm.user_id == client.id).count()
    )

    goals = []
    if profile is not None and profile.productivity_goals:
        raw_goals = profile.productivity_goals
        # Legacy rows may hold a bare string; users.py stores a list.
        if isinstance(raw_goals, list):
            goals = [str(goal).strip() for goal in raw_goals if str(goal).strip()]
        elif isinstance(raw_goals, str):
            goals = [part.strip() for part in raw_goals.split(",") if part.strip()]

    def _difficulty(value) -> Optional[str]:
        if value is None:
            return None
        return value.value if hasattr(value, "value") else str(value)

    return {
        "client": CoachService.serialize_client(row),
        "goals": goals,
        "difficulty_preference": _difficulty(
            getattr(profile, "difficulty_preference", None)
        ),
        "adapted_difficulty": _difficulty(
            getattr(profile, "adapted_difficulty", None)
        ),
        "total_alarms": total_alarms,
        "total_snoozes_lifetime": int(getattr(profile, "total_snoozes", 0) or 0),
        "total_alarms_dismissed": int(
            getattr(profile, "total_alarms_dismissed", 0) or 0
        ),
    }


# ── 4. GET /coach/clients/{client_id}/behavioral ────────────────────────


@router.get(
    "/clients/{client_id}/behavioral",
    response_model=CoachClientAnalyticsResponse,
    summary="Client behavioral overview (sleep, wake, habit, snooze trends)",
)
def get_client_behavioral(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return the full behavioral analytics overview for one client.

    Same payload as the client's own ``GET /analytics/behavioral`` — it carries
    sleep schedule adherence, wake-up consistency, habit trends, snooze
    patterns, and the weekly/monthly series the dashboard charts.
    """
    client = _resolve_client(db, current_user, client_id)
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=client.id, days=days
    )
    return _analytics_envelope(client, days, overview)


# ── 5. GET /coach/clients/{client_id}/sleep-trends ──────────────────────


@router.get(
    "/clients/{client_id}/sleep-trends",
    response_model=CoachClientAnalyticsResponse,
    summary="Client sleep schedule adherence and daily sleep series",
)
def get_client_sleep_trends(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return sleep adherence plus the daily series needed to chart it."""
    client = _resolve_client(db, current_user, client_id)
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=client.id, days=days
    )
    return _analytics_envelope(
        client,
        days,
        {
            "sleep_schedule_adherence": overview["sleep_schedule_adherence"],
            "wake_up_consistency": overview["wake_up_consistency"],
            "habit_trends": overview["habit_trends"],
            "window_trends": overview["window_trends"],
            "monthly_trends": overview["monthly_trends"],
            "weekly_trends": overview["weekly_trends"],
        },
    )


# ── 6. GET /coach/clients/{client_id}/wake-consistency ──────────────────


@router.get(
    "/clients/{client_id}/wake-consistency",
    response_model=CoachClientAnalyticsResponse,
    summary="Client wake-up consistency and snooze pattern",
)
def get_client_wake_consistency(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return wake-up consistency alongside the snooze pattern driving it."""
    client = _resolve_client(db, current_user, client_id)
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=client.id, days=days
    )
    return _analytics_envelope(
        client,
        days,
        {
            "wake_up_consistency": overview["wake_up_consistency"],
            "verification_accuracy": overview["verification_accuracy"],
            "snooze_pattern": overview["snooze_pattern"],
            "weekly_trends": overview["weekly_trends"],
        },
    )


# ── 7. GET /coach/clients/{client_id}/habit-score ───────────────────────


@router.get(
    "/clients/{client_id}/habit-score",
    response_model=CoachClientAnalyticsResponse,
    summary="Client habit score with component breakdown and trend",
)
def get_client_habit_score(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return the client's habit score from the canonical scoring service."""
    client = _resolve_client(db, current_user, client_id)
    profile = (
        db.query(UserProfile).filter(UserProfile.user_id == client.id).first()
    )
    score = calculate_habit_score_for_user(db, client.id, profile)
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=client.id, days=days
    )
    return _analytics_envelope(
        client,
        days,
        {**score, "habit_trends": overview["habit_trends"]},
    )


# ── 8. GET /coach/clients/{client_id}/challenge-performance ─────────────


@router.get(
    "/clients/{client_id}/challenge-performance",
    response_model=CoachClientAnalyticsResponse,
    summary="Client cognitive challenge performance",
)
def get_client_challenge_performance(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return challenge accuracy, response times, and per-type breakdowns."""
    client = _resolve_client(db, current_user, client_id)
    performance = compute_challenge_performance(
        db, client.id, days, recent_limit=COACH_RECENT_ATTEMPTS
    )
    return _analytics_envelope(client, days, performance)


# ── 9. GET /coach/clients/{client_id}/productivity ──────────────────────


@router.get(
    "/clients/{client_id}/productivity",
    response_model=CoachClientAnalyticsResponse,
    summary="Client productivity analytics",
)
def get_client_productivity(
    client_id: int,
    days: int = Query(30, ge=1, le=365, description="Reporting window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return morning-routine, cognitive-readiness, and consistency analytics."""
    client = _resolve_client(db, current_user, client_id)
    insights = compute_productivity_insights(db, client.id, days)
    return _analytics_envelope(client, days, insights)


# ── 10. GET /coach/clients/{client_id}/recommendations ──────────────────


@router.get(
    "/clients/{client_id}/recommendations",
    response_model=RecommendationResponse,
    summary="Coaching recommendations generated for a client",
)
def get_client_recommendations(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_coach),
):
    """Return the client's personalized recommendation digest.

    Generated by the same engine as the client's own feed, so coaching advice
    matches what the client is being shown in-app. The coach gets the full
    feed (every category) rather than the 5-item client digest, since the
    dashboard splits it into coaching, productivity, and category panels.
    """
    client = _resolve_client(db, current_user, client_id)
    return RecommendationService.generate_recommendations(client, db)
