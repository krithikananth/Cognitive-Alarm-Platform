"""
Pydantic schemas for the sleep / wake / productivity recommendation engine.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RecommendationCategory(str, Enum):
    """High-level recommendation domains."""

    SLEEP = "sleep"
    WAKE = "wake"
    HABIT = "habit"
    PRODUCTIVITY = "productivity"
    CHALLENGE = "challenge"


class RecommendationPriority(str, Enum):
    """Urgency of a recommendation."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationItem(BaseModel):
    """A single personalized coaching recommendation."""

    id: str = Field(..., description="Stable recommendation identifier")
    category: RecommendationCategory
    priority: RecommendationPriority
    title: str
    detail: str
    action_hint: Optional[str] = Field(
        None, description="Short CTA describing what the user should do"
    )
    action_path: Optional[str] = Field(
        None, description="Frontend route for the suggested action"
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="How strongly the signals support this advice",
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Supporting metrics that produced this recommendation",
    )


class DailyPlan(BaseModel):
    """Actionable daily sleep/wake/productivity plan."""

    suggested_bedtime: Optional[str] = None
    suggested_wake_time: Optional[str] = None
    morning_focus: Optional[str] = None
    priority_actions: List[str] = Field(default_factory=list)


class RecommendationSummary(BaseModel):
    """Snapshot of signals used to generate recommendations."""

    habit_score: float = 0.0
    wake_consistency: float = 0.0
    streak_days: int = 0
    best_streak: int = 0
    sleep_target_hours: float = 8.0
    preferred_wake_time: Optional[str] = None
    suggested_bedtime: Optional[str] = None
    avg_wakefulness: Optional[float] = None
    avg_wakefulness_level: Optional[str] = None
    snooze_rate: Optional[float] = None
    recent_wake_events: int = 0
    active_alarms: int = 0
    goals_count: int = 0
    top_focus: str = "getting_started"
    top_focus_label: str = "Getting started"


class RecommendationResponse(BaseModel):
    """Full personalized recommendation payload."""

    generated_at: datetime
    summary: RecommendationSummary
    insights: List[str] = Field(default_factory=list)
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    by_category: Dict[str, List[RecommendationItem]] = Field(default_factory=dict)
    daily_plan: DailyPlan = Field(default_factory=DailyPlan)


class CategoryRecommendationResponse(BaseModel):
    """Filtered recommendations for a single category."""

    category: RecommendationCategory
    generated_at: datetime
    summary: RecommendationSummary
    insights: List[str] = Field(default_factory=list)
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    daily_plan: Optional[DailyPlan] = None
