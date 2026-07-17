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
    SleepAdherenceResponse,
    SnoozePatternResponse,
    WakeConsistencyResponse,
)
from app.services.analytics_ingestion_service import AnalyticsIngestionService
from app.services.behavioral_analytics_service import BehavioralAnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


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
    return BehavioralAnalyticsOverview(
        **BehavioralAnalyticsService.get_overview(
            db, user_id=current_user.id, days=days
        )
    )


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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
    return WakeConsistencyResponse(**overview["wake_up_consistency"])


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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
    return SleepAdherenceResponse(**overview["sleep_schedule_adherence"])


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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
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
    overview = BehavioralAnalyticsService.get_overview(
        db, user_id=current_user.id, days=days
    )
    return HabitTrendsResponse(**overview["habit_trends"])
