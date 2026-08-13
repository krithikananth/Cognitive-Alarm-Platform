"""Response models for the alarm challenge and wake-tracking endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import Field

from app.schemas.common import AggregateResponse


class ChallengeResponse(AggregateResponse):
    """A challenge served to a client — never carries the answer.

    The multi-step progress fields are attached by
    ``public_challenge_payload`` and are absent on the practice path, so only
    the challenge itself is required.
    """

    type: str
    prompt: str
    options: Optional[List[Any]] = None
    difficulty: str
    time_limit_seconds: int
    requested_type: Optional[str] = None
    selection_reason: Optional[str] = None
    adaptive_difficulty: Dict[str, Any] = Field(default_factory=dict)
    source: Optional[str] = None
    ai_generated: Optional[bool] = None
    generator: Optional[str] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    consecutive_correct: Optional[int] = None
    required_correct: Optional[int] = None
    escalation_level: Optional[int] = None
    requires_consecutive: Optional[bool] = None


class ChallengeVerifyResponse(AggregateResponse):
    """Outcome of a submitted answer.

    Fields are optional because one route serves three shapes: mid-sequence
    progress, full dismissal, and (via a raw ``JSONResponse``, which bypasses
    this model entirely) a rejected answer.
    """

    status: Optional[str] = None
    message: Optional[str] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    consecutive_correct: Optional[int] = None
    required_correct: Optional[int] = None
    is_dismissed: Optional[bool] = None
    verification_token: Optional[str] = None
    wake_confirmed: Optional[bool] = None
    score: Dict[str, Any] = Field(default_factory=dict)
    wakefulness: Dict[str, Any] = Field(default_factory=dict)
    alarm: Optional[Dict[str, Any]] = None
    success_streak: Optional[int] = None
    failure_streak: Optional[int] = None


class PracticeVerifyResponse(AggregateResponse):
    """Outcome of a practice answer — never affects streaks or alarms."""

    mode: str
    correct: bool
    timed_out: bool
    message: str
    score: Dict[str, Any] = Field(default_factory=dict)
    time_taken_seconds: Optional[float] = None
    challenge_type: str
    difficulty: str


class FailWakeResponse(AggregateResponse):
    """Outcome of abandoning a wake cycle."""

    status: str
    message: str
    wake_confirmed: bool
    is_dismissed: bool
    dismiss_method: Optional[str] = None
    success_streak: int
    failure_streak: int
    adapted_difficulty: Optional[str] = None
    day_streak: Optional[int] = None
    alarm: Optional[Dict[str, Any]] = None


class WakeConfirmationListResponse(AggregateResponse):
    """GET /alarms/wake-confirmations."""

    total: int
    events: List[Dict[str, Any]] = Field(default_factory=list)


class SnoozeHistoryResponse(AggregateResponse):
    """GET /alarms/snooze-history."""

    total: int
    events: List[Dict[str, Any]] = Field(default_factory=list)


class WakefulnessResponse(AggregateResponse):
    """GET /alarms/wakefulness.

    Only ``score`` and ``level`` are guaranteed: the cold-start branch (no
    attempts and no wake events yet) omits the narrative fields.
    """

    score: float
    level: str
    message: Optional[str] = None
    recent_wake_events: Optional[int] = None
    factors: Dict[str, Any] = Field(default_factory=dict)


class ChallengeStatsResponse(AggregateResponse):
    """GET /alarms/challenge/stats."""

    total_attempts: int
    correct_answers: int
    accuracy_percentage: float
    avg_response_time: float
    by_type: Dict[str, Any] = Field(default_factory=dict)
    by_difficulty: Dict[str, Any] = Field(default_factory=dict)


class ChallengeHistoryResponse(AggregateResponse):
    """GET /alarms/challenge/history and the per-alarm variant."""

    total: int
    page: int
    per_page: int
    history: List[Dict[str, Any]] = Field(default_factory=list)
    alarm_id: Optional[int] = None


class ChallengeAnalysisResponse(AggregateResponse):
    """GET /alarms/challenge/analysis."""

    summary: Dict[str, Any] = Field(default_factory=dict)
    strengths: List[Any] = Field(default_factory=list)
    weaknesses: List[Any] = Field(default_factory=list)
    by_type: Dict[str, Any] = Field(default_factory=dict)
    by_difficulty: Dict[str, Any] = Field(default_factory=dict)
    recommendations: List[Any] = Field(default_factory=list)
    insights: List[Any] = Field(default_factory=list)
    personalization: Dict[str, Any] = Field(default_factory=dict)


class LearningProfileResponse(AggregateResponse):
    """GET /alarms/challenge/learning-profile."""

    learning_patterns: Dict[str, Any] = Field(default_factory=dict)
    engagement: Dict[str, Any] = Field(default_factory=dict)
    current_baseline_difficulty: str
    projected_difficulty: str
    difficulty_levels: List[str] = Field(default_factory=list)


class ChallengeLogHealthResponse(AggregateResponse):
    """GET /alarms/challenge/log-health — attempt-log integrity audit."""

    is_clean: bool
    queryable: bool
    query_error: Optional[str] = None
    total_attempts: int
    correct_attempts: int
    incorrect_attempts: int
    total_snoozes: int
    total_dismisses: int
    issue_count: int
    issue_counts: Dict[str, Any] = Field(default_factory=dict)
    sample_issues: List[Any] = Field(default_factory=list)
    valid_challenge_types: List[str] = Field(default_factory=list)
    valid_difficulties: List[str] = Field(default_factory=list)
    duplicate_window_seconds: int
    repaired: bool
