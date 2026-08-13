"""Response models for the admin console aggregate endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import AggregateResponse


class AdminDashboardResponse(AggregateResponse):
    """GET /admin/dashboard — platform headline figures."""

    generated_at: str
    period_days: int
    period: Dict[str, Any] = Field(default_factory=dict)
    total_users: int
    active_users: int
    verified_users: int
    role_distribution: Dict[str, Any] = Field(default_factory=dict)
    new_users_in_period: int
    new_users_previous_period: int
    user_growth_rate_pct: float
    total_alarms: int
    active_alarms: int
    engagement: Dict[str, Any] = Field(default_factory=dict)
    top_performers: List[Dict[str, Any]] = Field(default_factory=list)
    users: List[Dict[str, Any]] = Field(default_factory=list)


class AdminUserListResponse(AggregateResponse):
    """GET /admin/users — paginated user list with aggregated stats."""

    total: int
    page: int
    per_page: int
    total_pages: int
    users: List[Dict[str, Any]] = Field(default_factory=list)


class AdminUserDetailResponse(AggregateResponse):
    """GET /admin/users/{user_id} — one account with its activity rollup."""

    user: Dict[str, Any] = Field(default_factory=dict)
    profile: Optional[Dict[str, Any]] = None
    period_days: int
    alarms: Dict[str, Any] = Field(default_factory=dict)
    activity: Dict[str, Any] = Field(default_factory=dict)


class AdminStatisticsResponse(AggregateResponse):
    """GET /admin/statistics — growth and activity trends."""

    generated_at: str
    period_days: int
    period: Dict[str, Any] = Field(default_factory=dict)
    registration_trend: List[Dict[str, Any]] = Field(default_factory=list)
    activity_by_hour: List[Dict[str, Any]] = Field(default_factory=list)
    activity_by_weekday: List[Dict[str, Any]] = Field(default_factory=list)
    challenge_performance: Dict[str, Any] = Field(default_factory=dict)
    wake_events: Dict[str, Any] = Field(default_factory=dict)


class AdminRecommendationsResponse(AggregateResponse):
    """GET /admin/recommendations — personalization signal rollup."""

    generated_at: str
    period_days: int
    period: Dict[str, Any] = Field(default_factory=dict)
    total_profiles: int
    signal_summary: Dict[str, Any] = Field(default_factory=dict)
    difficulty_distribution: Dict[str, Any] = Field(default_factory=dict)
    streak_summary: Dict[str, Any] = Field(default_factory=dict)
    consistency_summary: Dict[str, Any] = Field(default_factory=dict)
    habit_score_overview: Dict[str, Any] = Field(default_factory=dict)


class AdminAlarmsResponse(AggregateResponse):
    """GET /admin/alarms — alarm configuration distribution."""

    generated_at: str
    period_days: int
    period: Dict[str, Any] = Field(default_factory=dict)
    total_alarms: int
    active_alarms: int
    inactive_alarms: int
    type_distribution: Dict[str, Any] = Field(default_factory=dict)
    challenge_type_distribution: Dict[str, Any] = Field(default_factory=dict)
    difficulty_distribution: Dict[str, Any] = Field(default_factory=dict)
    configuration: Dict[str, Any] = Field(default_factory=dict)
    period_activity: Dict[str, Any] = Field(default_factory=dict)
    top_active_alarms: List[Dict[str, Any]] = Field(default_factory=list)


class AdminAnalyticsResponse(AggregateResponse):
    """GET /admin/analytics — event ingestion volumes."""

    generated_at: str
    period_days: int
    period: Dict[str, Any] = Field(default_factory=dict)
    total_events_all_time: int
    events_in_period: int
    avg_events_per_day: float
    unique_users: int
    by_event_type: List[Dict[str, Any]] = Field(default_factory=list)
    by_source: Dict[str, Any] = Field(default_factory=dict)
    by_entity_type: Dict[str, Any] = Field(default_factory=dict)
    ingestion_trend: List[Dict[str, Any]] = Field(default_factory=list)


class AdminReportsResponse(AggregateResponse):
    """GET /admin/reports — operational health snapshot."""

    generated_at: str
    system: Dict[str, Any] = Field(default_factory=dict)
    database: Dict[str, Any] = Field(default_factory=dict)
    data_integrity: Dict[str, Any] = Field(default_factory=dict)
    configuration: Dict[str, Any] = Field(default_factory=dict)
    last_24h: Dict[str, Any] = Field(default_factory=dict)
