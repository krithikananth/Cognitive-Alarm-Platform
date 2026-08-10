"""Schemas for the Wellness Coach APIs."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CoachClientSummary(BaseModel):
    """One row of a coach's client roster."""

    assignment_id: int
    assigned_at: Optional[str] = None
    notes: Optional[str] = None
    client_id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    joined_at: Optional[str] = None
    timezone: str = "UTC"
    preferred_wake_time: Optional[str] = None
    sleep_duration_hours: float = 0.0
    habit_score: float = 0.0
    habit_breakdown: Dict[str, float] = Field(default_factory=dict)
    streak_days: int = 0
    best_streak: int = 0
    wake_consistency: float = 0.0
    verified_wakes: int = 0
    wake_events: int = 0
    wake_success_rate: float = 0.0
    snoozes: int = 0
    avg_wakefulness: Optional[float] = None
    challenge_attempts: int = 0
    challenge_accuracy: float = 0.0
    active_alarms: int = 0
    last_wake_at: Optional[str] = None
    days_since_last_wake: Optional[int] = None
    needs_attention: bool = False
    alerts: List[str] = Field(default_factory=list)
    has_activity: bool = False


class CoachClientListResponse(BaseModel):
    """Paginated client roster."""

    total: int
    total_assigned: int
    page: int
    per_page: int
    total_pages: int
    days: int
    clients: List[CoachClientSummary] = Field(default_factory=list)


class CoachHabitScoreBand(BaseModel):
    band: str
    count: int


class CoachAttentionClient(BaseModel):
    client_id: int
    full_name: Optional[str] = None
    username: str
    habit_score: float = 0.0
    wake_consistency: float = 0.0
    days_since_last_wake: Optional[int] = None
    alerts: List[str] = Field(default_factory=list)


class CoachTopClient(BaseModel):
    client_id: int
    full_name: Optional[str] = None
    username: str
    habit_score: float = 0.0
    streak_days: int = 0
    verified_wakes: int = 0


class CoachOverviewResponse(BaseModel):
    """Roster-wide KPIs across every assigned client."""

    generated_at: str
    days: int
    total_clients: int
    active_clients: int
    deactivated_clients: int
    engaged_clients: int
    engagement_rate: float
    needs_attention_count: int
    avg_habit_score: float
    avg_wake_consistency: float
    avg_streak_days: float
    total_verified_wakes: int
    total_wake_events: int
    total_snoozes: int
    roster_wake_success_rate: float
    challenge_attempts: int
    challenge_accuracy: float
    habit_score_distribution: List[CoachHabitScoreBand] = Field(default_factory=list)
    attention_clients: List[CoachAttentionClient] = Field(default_factory=list)
    top_clients: List[CoachTopClient] = Field(default_factory=list)
    is_empty: bool = False


class CoachClientDetailResponse(BaseModel):
    """Single client's roster row plus profile context."""

    client: CoachClientSummary
    goals: List[str] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    adapted_difficulty: Optional[str] = None
    total_alarms: int = 0
    total_snoozes_lifetime: int = 0
    total_alarms_dismissed: int = 0


class CoachAssignmentCreate(BaseModel):
    """Admin request to assign a client to a coach."""

    coach_id: int
    client_id: int
    notes: Optional[str] = Field(default=None, max_length=500)


class CoachAssignmentResponse(BaseModel):
    """A single coach/client assignment."""

    id: int
    coach_id: int
    coach_username: Optional[str] = None
    coach_full_name: Optional[str] = None
    client_id: int
    client_username: Optional[str] = None
    client_full_name: Optional[str] = None
    client_email: Optional[str] = None
    is_active: bool
    notes: Optional[str] = None
    assigned_by_user_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CoachAssignmentListResponse(BaseModel):
    """Paginated assignment listing for admin management."""

    total: int
    page: int
    per_page: int
    total_pages: int
    assignments: List[CoachAssignmentResponse] = Field(default_factory=list)


class CoachClientAnalyticsResponse(BaseModel):
    """Envelope for a client-scoped analytics payload.

    The ``data`` block is the untouched output of the same service the client's
    own dashboard calls, so coach and client always see identical numbers.
    """

    client_id: int
    client_name: str
    days: int
    generated_at: str
    data: Dict[str, Any] = Field(default_factory=dict)
