"""
Alarm Pydantic schemas — uses str for IDs and time fields.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class AlarmCreate(BaseModel):
    label: Optional[str] = None
    alarm_time: str  # "HH:MM"
    alarm_type: str = Field(..., pattern="^(daily|weekday|weekend|one_time|smart_adaptive)$")
    days_of_week: List[int] = Field(default=[], description="0=Mon..6=Sun")
    challenge_type: Optional[str] = Field(None, pattern="^(math|logic|memory|word|pattern|riddle|quiz)$")
    challenge_difficulty: str = Field(default="medium", pattern="^(beginner|easy|medium|hard|expert)$")
    snooze_limit: int = Field(default=3, ge=0, le=10)
    snooze_interval_minutes: int = Field(default=5, ge=1, le=30)
    sound: str = "default"
    vibration: bool = True
    smart_wakeup_window_minutes: int = Field(default=30, ge=5, le=60)
    one_time_date: Optional[str] = None  # "YYYY-MM-DD"


class AlarmUpdate(BaseModel):
    label: Optional[str] = None
    alarm_time: Optional[str] = None
    alarm_type: Optional[str] = Field(None, pattern="^(daily|weekday|weekend|one_time|smart_adaptive)$")
    days_of_week: Optional[List[int]] = None
    challenge_type: Optional[str] = Field(None, pattern="^(math|logic|memory|word|pattern|riddle|quiz)$")
    challenge_difficulty: Optional[str] = Field(None, pattern="^(beginner|easy|medium|hard|expert)$")
    snooze_limit: Optional[int] = Field(None, ge=0, le=10)
    snooze_interval_minutes: Optional[int] = Field(None, ge=1, le=30)
    sound: Optional[str] = None
    vibration: Optional[bool] = None
    smart_wakeup_window_minutes: Optional[int] = Field(None, ge=5, le=60)
    one_time_date: Optional[str] = None
    is_active: Optional[bool] = None


class AlarmResponse(BaseModel):
    id: str
    user_id: str
    label: Optional[str] = None
    alarm_time: str
    alarm_type: str
    is_active: bool
    days_of_week: List[int] = []
    challenge_type: Optional[str] = None
    challenge_difficulty: str
    snooze_limit: int
    snooze_interval_minutes: int
    sound: str
    vibration: bool
    smart_wakeup_window_minutes: int
    one_time_date: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_json(cls, alarm):
        """Create response from ORM object, parsing JSON fields."""
        import json
        data = {}
        for col in alarm.__table__.columns:
            data[col.name] = getattr(alarm, col.name)
        # Parse days_of_week from JSON string
        if isinstance(data.get("days_of_week"), str):
            try:
                data["days_of_week"] = json.loads(data["days_of_week"])
            except (json.JSONDecodeError, TypeError):
                data["days_of_week"] = []
        return cls(**data)


class AlarmToggle(BaseModel):
    is_active: bool


class AlarmEventResponse(BaseModel):
    id: str
    alarm_id: str
    user_id: str
    triggered_at: datetime
    dismissed_at: Optional[datetime] = None
    snooze_count: int
    challenge_completed: bool
    challenge_id: Optional[str] = None
    wake_up_verified: bool
    response_time_seconds: Optional[float] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AlarmListResponse(BaseModel):
    alarms: List[AlarmResponse]
    total: int


class AlarmEventListResponse(BaseModel):
    events: List[AlarmEventResponse]
    total: int
