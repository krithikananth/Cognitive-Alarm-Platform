"""
Pydantic schemas for Alarm CRUD operations.

Includes validation for ``days_of_week`` (0-6) and volume (0-100).
"""

from datetime import datetime, time, date, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, field_serializer

from app.models.alarm import AlarmType, ChallengeType


class AlarmCreate(BaseModel):
    """
    Schema for creating a new alarm.

    Attributes:
        title: Short name for the alarm.
        description: Optional extended description.
        alarm_time: Time of day the alarm should ring (HH:MM:SS or HH:MM).
        alarm_type: Recurrence pattern.
        days_of_week: List of weekday integers (0=Mon … 6=Sun).
        snooze_limit: Maximum allowed snoozes.
        snooze_interval_minutes: Minutes per snooze.
        challenge_type: Cognitive challenge type.
        challenge_count: Number of challenges to dismiss.
        challenge_difficulty: Baseline puzzle difficulty for this alarm.
        volume: Alarm volume (0-100).
        vibrate: Enable haptic feedback.
        label: Optional tag / label.
    """

    title: str = Field(
        default="Alarm", max_length=255, description="Alarm title"
    )
    description: Optional[str] = Field(None, description="Alarm description")
    alarm_time: time = Field(..., description="Alarm time (HH:MM or HH:MM:SS)")
    alarm_type: AlarmType = Field(
        default=AlarmType.DAILY, description="Recurrence pattern"
    )
    days_of_week: Optional[List[int]] = Field(
        None, description="Days of week (0=Mon … 6=Sun)"
    )
    snooze_limit: int = Field(
        default=3, ge=0, le=10, description="Max snoozes"
    )
    snooze_interval_minutes: int = Field(
        default=5, ge=1, le=60, description="Snooze interval in minutes"
    )
    challenge_type: ChallengeType = Field(
        default=ChallengeType.RANDOM, description="Challenge type"
    )
    challenge_count: int = Field(
        default=1, ge=1, le=10, description="Number of challenges"
    )
    challenge_difficulty: str = Field(
        default="medium",
        description="Baseline difficulty (beginner/easy/medium/hard/expert)",
    )
    volume: int = Field(default=80, ge=0, le=100, description="Volume level")
    vibrate: bool = Field(default=True, description="Enable vibration")
    label: Optional[str] = Field(
        None, max_length=255, description="Custom label"
    )
    one_time_date: Optional[date] = Field(
        None, description="Calendar date for one-time alarms (local timezone)"
    )

    @field_validator("challenge_difficulty")
    @classmethod
    def validate_challenge_difficulty(cls, v: str) -> str:
        """Normalize and validate difficulty labels."""
        allowed = {"beginner", "easy", "medium", "hard", "expert"}
        normalized = (v or "medium").strip().lower()
        if normalized not in allowed:
            raise ValueError(
                f"challenge_difficulty must be one of: {', '.join(sorted(allowed))}"
            )
        return normalized

    @field_validator("days_of_week")
    @classmethod
    def validate_days_of_week(
        cls, v: Optional[List[int]]
    ) -> Optional[List[int]]:
        """Ensure every day value is between 0 and 6."""
        if v is not None:
            for day in v:
                if day < 0 or day > 6:
                    raise ValueError(
                        f"Day value {day} is out of range. Must be 0-6 "
                        "(0=Monday, 6=Sunday)."
                    )
            # Deduplicate and sort
            v = sorted(set(v))
        return v


class AlarmUpdate(BaseModel):
    """
    Schema for partial alarm updates.  All fields are optional.

    Attributes:
        title: Updated title.
        description: Updated description.
        alarm_time: Updated alarm time.
        alarm_type: Updated recurrence pattern.
        days_of_week: Updated weekday list.
        snooze_limit: Updated snooze limit.
        snooze_interval_minutes: Updated snooze interval.
        challenge_type: Updated challenge type.
        challenge_count: Updated challenge count.
        challenge_difficulty: Updated baseline difficulty.
        volume: Updated volume.
        vibrate: Updated vibration setting.
        label: Updated label.
    """

    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    alarm_time: Optional[time] = None
    alarm_type: Optional[AlarmType] = None
    days_of_week: Optional[List[int]] = None
    snooze_limit: Optional[int] = Field(None, ge=0, le=10)
    snooze_interval_minutes: Optional[int] = Field(None, ge=1, le=60)
    challenge_type: Optional[ChallengeType] = None
    challenge_count: Optional[int] = Field(None, ge=1, le=10)
    challenge_difficulty: Optional[str] = Field(
        None,
        description="Baseline difficulty (beginner/easy/medium/hard/expert)",
    )
    volume: Optional[int] = Field(None, ge=0, le=100)
    vibrate: Optional[bool] = None
    label: Optional[str] = Field(None, max_length=255)
    one_time_date: Optional[date] = Field(
        None, description="Calendar date for one-time alarms (local timezone)"
    )

    @field_validator("challenge_difficulty")
    @classmethod
    def validate_challenge_difficulty(cls, v: Optional[str]) -> Optional[str]:
        """Normalize and validate difficulty labels when provided."""
        if v is None:
            return v
        allowed = {"beginner", "easy", "medium", "hard", "expert"}
        normalized = v.strip().lower()
        if normalized not in allowed:
            raise ValueError(
                f"challenge_difficulty must be one of: {', '.join(sorted(allowed))}"
            )
        return normalized

    @field_validator("days_of_week")
    @classmethod
    def validate_days_of_week(
        cls, v: Optional[List[int]]
    ) -> Optional[List[int]]:
        """Ensure every day value is between 0 and 6."""
        if v is not None:
            for day in v:
                if day < 0 or day > 6:
                    raise ValueError(
                        f"Day value {day} is out of range. Must be 0-6."
                    )
            v = sorted(set(v))
        return v


class AlarmResponse(BaseModel):
    """
    Public-facing alarm representation returned by the API.

    Attributes:
        All columns from the ``alarms`` table are exposed.
    """

    id: int
    user_id: int
    title: str
    description: Optional[str] = None
    alarm_time: time
    alarm_type: AlarmType
    days_of_week: Optional[List[int]] = None
    is_active: bool
    snooze_limit: int
    snooze_interval_minutes: int
    challenge_type: ChallengeType
    challenge_count: int
    challenge_difficulty: str = "medium"
    volume: int
    vibrate: bool
    label: Optional[str] = None
    next_trigger_at: Optional[datetime] = None
    last_triggered_at: Optional[datetime] = None
    total_dismissals: int
    total_snoozes: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("next_trigger_at", "last_triggered_at", "created_at", "updated_at")
    def serialize_utc_datetimes(self, value: Optional[datetime]) -> Optional[str]:
        """Emit UTC ISO-8601 with explicit Z so clients parse correctly."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class AlarmListResponse(BaseModel):
    """
    Paginated list of alarms.

    Attributes:
        alarms: List of alarm records for the current page.
        total: Total number of alarms matching the query.
        page: Current page number (1-indexed).
        per_page: Number of records per page.
    """

    alarms: List[AlarmResponse]
    total: int
    page: int
    per_page: int


class AlarmToggle(BaseModel):
    """
    Schema for toggling an alarm's active state.

    Attributes:
        is_active: Desired active state.
    """

    is_active: bool = Field(..., description="Set alarm active or inactive")


class SnoozeInfoResponse(BaseModel):
    """Anti-snooze status for the active wake cycle.

    Used by the client to disable snooze and preview difficulty escalation.
    """

    alarm_id: int
    snooze_count: int = Field(..., ge=0, description="Snoozes used this wake cycle")
    snooze_limit: int = Field(..., ge=0, description="Max snoozes allowed (0 = disabled)")
    can_snooze: bool = Field(..., description="Whether another snooze is allowed")
    snooze_interval_minutes: int = Field(..., ge=1)
    escalation_level: int = Field(
        ..., ge=0, description="Difficulty steps raised by prior snoozes"
    )
    next_challenge_difficulty: str = Field(
        ..., description="Difficulty that will apply on the next challenge"
    )
    anti_snooze_enforced: bool = Field(
        ...,
        description="True when snooze is blocked (limit reached or limit is 0)",
    )
