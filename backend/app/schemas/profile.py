"""
Pydantic schemas for UserProfile CRUD operations.

Supports partial updates for sleep schedule, goals, and habit preferences
independently.
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.profile import DifficultyPreference


class ProfileCreate(BaseModel):
    """
    Schema for creating a user profile.

    Attributes:
        preferred_wake_time: Desired wake-up time (HH:MM).
        sleep_duration_hours: Target hours of sleep.
        timezone: IANA timezone string.
        productivity_goals: List of goal strings.
        difficulty_preference: Cognitive-challenge difficulty.
        habit_preferences: Arbitrary key-value habit settings.
    """

    preferred_wake_time: Optional[time] = Field(
        None, description="Preferred wake-up time"
    )
    sleep_duration_hours: float = Field(
        default=8.0, ge=1.0, le=24.0, description="Target sleep hours"
    )
    timezone: str = Field(default="UTC", max_length=50, description="IANA timezone")
    productivity_goals: Optional[List[str]] = Field(
        None, description="List of productivity goals"
    )
    difficulty_preference: DifficultyPreference = Field(
        default=DifficultyPreference.MEDIUM,
        description="Cognitive challenge difficulty",
    )
    habit_preferences: Optional[Dict[str, Any]] = Field(
        None, description="Habit preference settings"
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate that the timezone string is recognized by pytz."""
        import pytz

        if v not in pytz.all_timezones:
            raise ValueError(f"Unknown timezone: {v}")
        return v


class ProfileUpdate(BaseModel):
    """
    Schema for partial profile updates.  All fields are optional.

    Attributes:
        preferred_wake_time: Updated wake-up time.
        sleep_duration_hours: Updated sleep target.
        timezone: Updated timezone.
        productivity_goals: Updated goal list.
        difficulty_preference: Updated difficulty.
        habit_preferences: Updated habit settings.
    """

    preferred_wake_time: Optional[time] = None
    sleep_duration_hours: Optional[float] = Field(None, ge=1.0, le=24.0)
    timezone: Optional[str] = Field(None, max_length=50)
    productivity_goals: Optional[List[str]] = None
    difficulty_preference: Optional[DifficultyPreference] = None
    habit_preferences: Optional[Dict[str, Any]] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        """Validate timezone if provided."""
        if v is not None:
            import pytz

            if v not in pytz.all_timezones:
                raise ValueError(f"Unknown timezone: {v}")
        return v


class SleepScheduleUpdate(BaseModel):
    """
    Targeted update for sleep-related profile fields.

    Attributes:
        preferred_wake_time: New preferred wake-up time.
        sleep_duration_hours: New target sleep hours.
    """

    preferred_wake_time: Optional[time] = Field(
        None, description="Preferred wake-up time"
    )
    sleep_duration_hours: Optional[float] = Field(
        None, ge=1.0, le=24.0, description="Target sleep hours"
    )


class GoalsUpdate(BaseModel):
    """
    Targeted update for productivity goals.

    Attributes:
        productivity_goals: Replacement list of goal strings.
    """

    productivity_goals: List[str] = Field(
        ..., description="Updated productivity goals"
    )


class HabitPreferencesUpdate(BaseModel):
    """
    Targeted update for habit preferences.

    Attributes:
        habit_preferences: Replacement dictionary of habit preferences.
    """

    habit_preferences: Dict[str, Any] = Field(
        ..., description="Updated habit preferences"
    )


class ProfileResponse(BaseModel):
    """
    Public-facing profile representation returned by the API.

    Includes all stored fields plus a computed ``habit_score``.

    Attributes:
        id: Profile primary key.
        user_id: Owning user's primary key.
        preferred_wake_time: Current wake-up time preference.
        sleep_duration_hours: Current sleep target.
        timezone: IANA timezone.
        productivity_goals: List of goals.
        difficulty_preference: Current difficulty.
        habit_preferences: Current habit settings.
        wake_up_consistency_score: Consistency metric (0-100).
        total_alarms_dismissed: Lifetime dismissal count.
        total_snoozes: Lifetime snooze count.
        streak_days: Current streak.
        best_streak: All-time best streak.
        habit_score: Computed overall habit score (0-100).
        created_at: Profile creation timestamp.
        updated_at: Profile last-updated timestamp.
    """

    id: int
    user_id: int
    preferred_wake_time: Optional[time] = None
    sleep_duration_hours: float
    timezone: str
    productivity_goals: Optional[List[str]] = None
    difficulty_preference: DifficultyPreference
    habit_preferences: Optional[Dict[str, Any]] = None
    wake_up_consistency_score: float
    total_alarms_dismissed: int
    total_snoozes: int
    streak_days: int
    best_streak: int
    habit_score: float = Field(
        default=0.0, description="Computed overall habit score"
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
