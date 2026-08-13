"""Response models for the user dashboard aggregate endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import AggregateResponse


class DashboardSummaryResponse(AggregateResponse):
    """GET /dashboard/summary — headline figures for the landing page."""

    period: str
    period_days: int
    generated_at: str
    active_alarms: int
    current_habit_score: float
    habit_score_breakdown: Dict[str, Any] = Field(default_factory=dict)
    current_streak: int
    best_streak: int
    success_streak: int
    failure_streak: int
    preferred_wakeup_time: Optional[str] = None
    period_stats: Dict[str, Any] = Field(default_factory=dict)
    weekly_on_time: int
    weekly_total: int
    weekly_tracker: List[Dict[str, Any]] = Field(default_factory=list)
    upcoming_alarms: List[Dict[str, Any]] = Field(default_factory=list)
    last_successful_wake_date: Optional[str] = None


class AlarmHistoryResponse(AggregateResponse):
    """GET /dashboard/alarm-history — paginated wake/snooze event feed."""

    total: int
    page: int
    per_page: int
    days: int
    events: List[Dict[str, Any]] = Field(default_factory=list)


class WakeStatsResponse(AggregateResponse):
    """GET /dashboard/wake-stats — dismissal timing and outcome breakdown."""

    days: int
    total_wake_events: int
    verified_wakes: int
    abandoned_wakes: int
    success_rate: float
    avg_time_to_dismiss_seconds: Optional[float] = None
    median_time_to_dismiss_seconds: Optional[float] = None
    fastest_dismiss_seconds: Optional[float] = None
    slowest_dismiss_seconds: Optional[float] = None
    first_try_success_rate: float
    avg_snoozes_before_dismiss: float
    avg_failed_attempts: float
    avg_wakefulness_score: Optional[float] = None
    by_hour: List[Dict[str, Any]] = Field(default_factory=list)
    by_weekday: List[Dict[str, Any]] = Field(default_factory=list)
    by_dismiss_method: Dict[str, Any] = Field(default_factory=dict)


class ChallengePerformanceResponse(AggregateResponse):
    """GET /dashboard/challenge-performance — accuracy and completion."""

    days: int
    total_attempts: int
    correct_answers: int
    accuracy: float
    avg_response_time: float
    total_points_earned: int
    completion: Dict[str, Any] = Field(default_factory=dict)
    trend: Dict[str, Any] = Field(default_factory=dict)
    best_type: Optional[str] = None
    worst_type: Optional[str] = None
    by_type: Dict[str, Any] = Field(default_factory=dict)
    by_difficulty: Dict[str, Any] = Field(default_factory=dict)
    recent_activity: List[Dict[str, Any]] = Field(default_factory=list)


class ProductivityInsightsResponse(AggregateResponse):
    """GET /dashboard/productivity — readiness, sleep and correlations."""

    days: int
    generated_at: str
    morning_routine_score: float
    cognitive_readiness_score: float
    habit_score: float
    habit_score_breakdown: Dict[str, Any] = Field(default_factory=dict)
    active_days_in_period: int
    consistency_rate: float
    current_streak: int
    best_streak: int
    verified_wakes: int
    challenge_accuracy: float
    avg_wakefulness: float
    avg_time_to_productive_seconds: Optional[float] = None
    productivity_improvement: Dict[str, Any] = Field(default_factory=dict)
    trend: Dict[str, Any] = Field(default_factory=dict)
    goals: List[Any] = Field(default_factory=list)
    goals_count: int
    sleep_patterns: Dict[str, Any] = Field(default_factory=dict)
    correlations: Dict[str, Any] = Field(default_factory=dict)
