"""
Analytics Data Ingestion + Behavioral Analytics API.

Dedicated endpoints for storing and reading generic analytics events,
plus pandas/numpy behavioral aggregates over domain SSOT tables.

Does not replace domain challenge/snooze/wake logs or existing dashboard APIs.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsEventBatchIngest,
    AnalyticsEventIngest,
    AnalyticsEventListResponse,
    AnalyticsEventResponse,
    AnalyticsIngestResponse,
    AnalyticsSummaryResponse,
    BehavioralAnalyticsOverview,
    HabitTrendsResponse,
    PeriodTrendsResponse,
    ProductivityCorrelationResponse,
    SleepAdherenceResponse,
    SleepPatternsResponse,
    SnoozePatternResponse,
    VerificationAccuracyResponse,
    WakeConsistencyResponse,
)
from app.services.analytics_ingestion_service import AnalyticsIngestionService
from app.services.behavioral_analytics_service import BehavioralAnalyticsService
from app.services import aggregate_cache

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _overview(db: Session, user_id: int, days: int) -> dict:
    """One behavioural pass, shared by every ``/behavioral*`` endpoint.

    All ten endpoints below are projections of the same overview, and a
    dashboard renders several of them at once. Without this, each one repeats
    the full pandas pass — the dominant cost of these routes, since their SQL
    is only a handful of queries.
    """
    params = {"days": days}
    cached = aggregate_cache.read("behavioral_overview", user_id, params)
    if cached is not None:
        return cached

    payload = BehavioralAnalyticsService.get_overview(db, user_id=user_id, days=days)
    aggregate_cache.write("behavioral_overview", user_id, params, payload)
    return payload


def _to_response(row) -> AnalyticsEventResponse:
    return AnalyticsEventResponse.model_validate(row)


@router.post(
    "/events",
    response_model=AnalyticsIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a single analytics event",
)
def ingest_event(
    payload: AnalyticsEventIngest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept one client-side analytics event for the authenticated user."""
    try:
        rows = AnalyticsIngestionService.ingest_many(
            db,
            user_id=current_user.id,
            events=[payload.model_dump()],
            source="client",
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return AnalyticsIngestResponse(
        accepted=len(rows),
        events=[_to_response(r) for r in rows],
    )


@router.post(
    "/events/batch",
    response_model=AnalyticsIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a batch of analytics events",
)
def ingest_events_batch(
    payload: AnalyticsEventBatchIngest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Accept up to 100 client-side analytics events in one request."""
    try:
        rows = AnalyticsIngestionService.ingest_many(
            db,
            user_id=current_user.id,
            events=[e.model_dump() for e in payload.events],
            source="client",
            commit=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return AnalyticsIngestResponse(
        accepted=len(rows),
        events=[_to_response(r) for r in rows],
    )


@router.get(
    "/events",
    response_model=AnalyticsEventListResponse,
    summary="List ingested analytics events",
)
def list_analytics_events(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    event_type: str | None = Query(None, description="Filter by exact event_type"),
    entity_type: str | None = Query(None),
    entity_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's analytics event stream (newest first)."""
    result = AnalyticsIngestionService.list_events(
        db,
        user_id=current_user.id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        page=page,
        per_page=per_page,
    )
    return AnalyticsEventListResponse(
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        events=[_to_response(r) for r in result["events"]],
    )


@router.get(
    "/summary",
    response_model=AnalyticsSummaryResponse,
    summary="Analytics event type summary",
)
def analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Counts by event_type for future dashboards and feature work."""
    result = AnalyticsIngestionService.summarize(db, user_id=current_user.id)
    return AnalyticsSummaryResponse(**result)


# ── Behavioral analytics (pandas / numpy) ───────────────────────────────


@router.get(
    "/behavioral",
    response_model=BehavioralAnalyticsOverview,
    summary="Full behavioral analytics overview",
)
def behavioral_overview(
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snooze, wake consistency, sleep adherence, weekly/monthly/habit trends."""
    return BehavioralAnalyticsOverview(**_overview(db, current_user.id, days))


@router.get(
    "/behavioral/snooze",
    response_model=SnoozePatternResponse,
    summary="Snooze pattern analytics",
)
def behavioral_snooze(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return SnoozePatternResponse(**overview["snooze_pattern"])


@router.get(
    "/behavioral/wake-consistency",
    response_model=WakeConsistencyResponse,
    summary="Wake-up consistency analytics",
)
def behavioral_wake_consistency(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return WakeConsistencyResponse(**overview["wake_up_consistency"])


@router.get(
    "/behavioral/verification-accuracy",
    response_model=VerificationAccuracyResponse,
    summary="Wake-up verification accuracy",
)
def behavioral_verification_accuracy(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """How often the verification gate's verdict matched the evidence it held."""
    overview = _overview(db, current_user.id, days)
    return VerificationAccuracyResponse(**overview["verification_accuracy"])


@router.get(
    "/behavioral/sleep-adherence",
    response_model=SleepAdherenceResponse,
    summary="Sleep schedule adherence analytics",
)
def behavioral_sleep_adherence(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return SleepAdherenceResponse(**overview["sleep_schedule_adherence"])


@router.get(
    "/behavioral/sleep-patterns",
    response_model=SleepPatternsResponse,
    summary="Observed sleep pattern analytics",
)
def behavioral_sleep_patterns(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Measured bedtime, duration, regularity and social jetlag per night."""
    overview = _overview(db, current_user.id, days)
    return SleepPatternsResponse(**overview["sleep_patterns"])


@router.get(
    "/behavioral/productivity-correlation",
    response_model=ProductivityCorrelationResponse,
    summary="Correlation between wake/habit behaviour and productivity outcomes",
)
def behavioral_productivity_correlation(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pearson/Spearman coefficients with Fisher-z significance per pair."""
    overview = _overview(db, current_user.id, days)
    return ProductivityCorrelationResponse(**overview["productivity_correlation"])


@router.get(
    "/behavioral/trends/weekly",
    response_model=PeriodTrendsResponse,
    summary="Weekly behavioral trends",
)
def behavioral_weekly_trends(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return PeriodTrendsResponse(**overview["weekly_trends"])


@router.get(
    "/behavioral/trends/monthly",
    response_model=PeriodTrendsResponse,
    summary="Monthly behavioral trends",
)
def behavioral_monthly_trends(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return PeriodTrendsResponse(**overview["monthly_trends"])


@router.get(
    "/behavioral/habits",
    response_model=HabitTrendsResponse,
    summary="Habit score trends",
)
def behavioral_habit_trends(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    overview = _overview(db, current_user.id, days)
    return HabitTrendsResponse(**overview["habit_trends"])
