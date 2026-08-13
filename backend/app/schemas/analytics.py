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


class SnoozeReductionResponse(BaseModel):
    """Snoozes per wake in the current period vs the period before it."""

    period_days: int
    current_period_start: Optional[str] = None
    current_period_end: Optional[str] = None
    previous_period_start: Optional[str] = None
    previous_period_end: Optional[str] = None
    current_snoozes: int
    previous_snoozes: int
    current_wakes: int
    previous_wakes: int
    current_snoozes_per_wake: Optional[float] = None
    previous_snoozes_per_wake: Optional[float] = None
    absolute_change_per_wake: Optional[float] = None
    # Positive = snoozing went down. None when there is no usable baseline.
    reduction_rate: Optional[float] = None
    direction: str
    status: str
    min_wakes_required: int


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
    reduction: SnoozeReductionResponse


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


class VerificationAccuracyResponse(BaseModel):
    """Accuracy of the wake-up verification gate's own decisions.

    ``accuracy_rate`` replays each finished cycle against the contract
    ``verified <=> consecutive_correct >= challenges_required``. It is neither
    the dismissal success rate nor challenge accuracy.
    """

    decisions: int
    verified: int
    rejected: int
    correct_decisions: int
    accuracy_rate: Optional[float] = None
    false_verifications: int
    missed_verifications: int
    first_pass_verifications: int
    first_pass_rate: Optional[float] = None
    answers_recorded: int
    avg_answers_per_verification: Optional[float] = None
    avg_wrong_answers_per_verification: Optional[float] = None
    min_decisions_required: int
    status: str
    integrity: str


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


class SleepSegmentSummary(BaseModel):
    nights: int
    avg_duration_hours: Optional[float] = None
    avg_wake_time: Optional[str] = None
    avg_bedtime: Optional[str] = None


class SleepNightPoint(BaseModel):
    """One night. ``source`` says whether the start was logged or inferred."""

    date: str
    weekday: str
    is_weekend: bool
    source: str
    sleep_end_source: str
    wake_time: Optional[str] = None
    wake_minutes: Optional[float] = None
    bedtime: Optional[str] = None
    bedtime_minutes: Optional[float] = None
    sleep_duration_hours: Optional[float] = None
    mid_sleep_minutes: Optional[float] = None
    wake_latency_seconds: Optional[int] = None


class SleepPatternsResponse(BaseModel):
    nights_observed: int
    nights_with_duration: int
    nights_recorded: int
    nights_estimated: int
    has_recorded_sleep: bool
    duration_source: str
    avg_recorded_duration_hours: Optional[float] = None
    avg_estimated_duration_hours: Optional[float] = None
    avg_sleep_duration_hours: Optional[float] = None
    std_sleep_duration_hours: Optional[float] = None
    min_sleep_duration_hours: Optional[float] = None
    max_sleep_duration_hours: Optional[float] = None
    avg_bedtime: Optional[str] = None
    bedtime_std_minutes: Optional[float] = None
    avg_wake_time: Optional[str] = None
    wake_time_std_minutes: Optional[float] = None
    avg_mid_sleep: Optional[str] = None
    social_jetlag_minutes: Optional[float] = None
    schedule_regularity_score: float
    duration_consistency_score: float
    target_sleep_hours: float
    avg_sleep_debt_hours: Optional[float] = None
    short_sleep_nights: int
    long_sleep_nights: int
    avg_wake_latency_seconds: Optional[float] = None
    weekday: SleepSegmentSummary
    weekend: SleepSegmentSummary
    recent_7d_avg_duration_hours: Optional[float] = None
    previous_7d_avg_duration_hours: Optional[float] = None
    trend: str
    bedtime_coverage_rate: float
    has_open_session: bool = False
    nights: List[SleepNightPoint] = Field(default_factory=list)


class CorrelationMethod(BaseModel):
    coefficients: List[str]
    significance_test: str
    alpha: float
    min_pairs: int


class CorrelationPair(BaseModel):
    id: str
    behavior: str
    behavior_label: str
    outcome: str
    outcome_label: str
    expected_direction: str
    status: str
    n: int
    min_pairs: int
    pearson_r: Optional[float] = None
    spearman_rho: Optional[float] = None
    p_value: Optional[float] = None
    significant: bool
    strength: str
    direction: str
    interpretation: str


class ProductivityCorrelationResponse(BaseModel):
    status: str
    method: CorrelationMethod
    window_days: int
    days_analyzed: int
    pairs: List[CorrelationPair] = Field(default_factory=list)
    significant_findings: List[str] = Field(default_factory=list)
    strongest: Optional[CorrelationPair] = None
    insights: List[str] = Field(default_factory=list)


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
    verification_accuracy: VerificationAccuracyResponse
    sleep_schedule_adherence: SleepAdherenceResponse
    sleep_patterns: SleepPatternsResponse
    productivity_correlation: ProductivityCorrelationResponse
    weekly_trends: PeriodTrendsResponse
    monthly_trends: PeriodTrendsResponse
    habit_trends: HabitTrendsResponse
    insights: List[str] = Field(default_factory=list)
