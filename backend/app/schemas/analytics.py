"""Pydantic schemas for analytics event ingestion and read APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AnalyticsEventIngest(BaseModel):
    """Single event accepted by the ingestion API."""

    event_type: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Dotted event name, e.g. alarm.triggered",
    )
    entity_type: Optional[str] = Field(
        None, max_length=50, description="Optional entity kind (alarm, challenge, …)"
    )
    entity_id: Optional[int] = Field(
        None, ge=1, description="Optional entity primary key"
    )
    event_data: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary JSON payload"
    )
    occurred_at: Optional[datetime] = Field(
        None, description="Client event time; defaults to server receive time"
    )

    @field_validator("event_type")
    @classmethod
    def normalize_event_type(cls, value: str) -> str:
        cleaned = (value or "").strip().lower().replace(" ", "_")
        if not cleaned:
            raise ValueError("event_type is required")
        return cleaned

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip().lower()
        return cleaned or None


class AnalyticsEventBatchIngest(BaseModel):
    """Batch ingestion payload (future-friendly for client SDKs)."""

    events: List[AnalyticsEventIngest] = Field(
        ..., min_length=1, max_length=100
    )


class AnalyticsEventResponse(BaseModel):
    """Stored analytics event returned to clients."""

    id: int
    user_id: int
    event_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    source: str
    event_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalyticsIngestResponse(BaseModel):
    """Result of a single or batch ingest call."""

    accepted: int
    events: List[AnalyticsEventResponse]


class AnalyticsEventListResponse(BaseModel):
    """Paginated event list."""

    total: int
    page: int
    per_page: int
    events: List[AnalyticsEventResponse]


class AnalyticsEventTypeCount(BaseModel):
    event_type: str
    count: int


class AnalyticsSummaryResponse(BaseModel):
    """Lightweight aggregate for future dashboards."""

    total_events: int
    by_event_type: List[AnalyticsEventTypeCount]


# ── Behavioral analytics (pandas / numpy aggregates) ────────────────────


class HourCount(BaseModel):
    hour: int
    count: int


class WeekdayCount(BaseModel):
    weekday: str
    weekday_index: int
    count: int


class SnoozePatternResponse(BaseModel):
    total_snoozes: int
    avg_snoozes_per_wake: float
    avg_snooze_number: float
    limit_hit_count: int
    limit_hit_rate: float
    by_hour: List[HourCount]
    by_weekday: List[WeekdayCount]
    peak_hour: Optional[int] = None
    peak_weekday: Optional[str] = None
    trend: str
    recent_7d_count: int
    previous_7d_count: int


class WakeConsistencyResponse(BaseModel):
    verified_wakes: int
    mean_wake_time: Optional[str] = None
    std_wake_minutes: Optional[float] = None
    consistency_score: float
    rolling_profile_score: float
    on_time_count: int
    on_time_rate: float
    avg_deviation_minutes: Optional[float] = None
    preferred_wake_time: Optional[str] = None
    tolerance_minutes: int
    trend: str


class SleepAdherenceResponse(BaseModel):
    preferred_wake_time: Optional[str] = None
    target_sleep_hours: float
    suggested_bedtime: Optional[str] = None
    adherence_rate: float
    adherent_days: int
    observed_days: int
    avg_deviation_minutes: Optional[float] = None
    profile_streak_days: int
    profile_adherence_score: float
    tolerance_minutes: int
    trend: str


class TrendDayPoint(BaseModel):
    date: str
    weekday: str
    snoozes: int
    verified_wakes: int
    on_time_wakes: int
    avg_snoozes_per_wake: float
    avg_time_to_dismiss_seconds: Optional[float] = None
    challenge_attempts: int
    challenge_accuracy: Optional[float] = None


class TrendTotals(BaseModel):
    snoozes: int
    verified_wakes: int
    on_time_wakes: int
    challenge_attempts: int
    on_time_rate: float


class PeriodTrendsResponse(BaseModel):
    period: str
    days: int
    start_date: str
    end_date: str
    totals: TrendTotals
    trend: str
    series: List[TrendDayPoint]


class HabitBreakdown(BaseModel):
    wake_up_consistency: float
    challenge_completion: float
    snooze_reduction: float
    sleep_adherence: float


class HabitTrendPoint(BaseModel):
    date: str
    habit_score: float
    breakdown: HabitBreakdown
    has_activity: bool


class HabitTrendsResponse(BaseModel):
    current_habit_score: float
    current_breakdown: HabitBreakdown
    weights: Dict[str, float]
    avg_proxy_score: float
    trend: str
    series: List[HabitTrendPoint]


class BehavioralAnalyticsOverview(BaseModel):
    """Complete behavioral analytics payload."""

    generated_at: str
    window_days: int
    window_start: str
    window_end: str
    snooze_pattern: SnoozePatternResponse
    wake_up_consistency: WakeConsistencyResponse
    sleep_schedule_adherence: SleepAdherenceResponse
    weekly_trends: PeriodTrendsResponse
    monthly_trends: PeriodTrendsResponse
    habit_trends: HabitTrendsResponse
    insights: List[str] = Field(default_factory=list)
