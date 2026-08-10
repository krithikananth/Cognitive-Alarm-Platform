"""
Pydantic schemas for the Notification system.

Covers device token registration, notification preferences CRUD,
notification feed responses, and read-marking payloads.
"""

from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.models.notification import (
    DeviceType,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)


class NotificationSound(str, Enum):
    """Client-facing notification sound presets."""

    DEFAULT = "default"
    GENTLE = "gentle"
    CHIME = "chime"
    SILENT = "silent"


class NotificationFrequency(str, Enum):
    """How broadly scheduled notifications are allowed to fire.

    - ``all``: every enabled type (bedtime, wake, habit, motivational)
    - ``essential``: bedtime + wake only
    - ``minimal``: wake reminders only
    """

    ALL = "all"
    ESSENTIAL = "essential"
    MINIMAL = "minimal"


# ── Device Token ─────────────────────────────────────────────────────

class DeviceTokenRegister(BaseModel):
    """Register or update an FCM device token."""

    fcm_token: str = Field(
        ..., min_length=10, max_length=512,
        description="FCM registration token from the client SDK",
    )
    device_type: DeviceType = Field(
        default=DeviceType.WEB,
        description="Platform type (web, ios, android)",
    )
    device_name: Optional[str] = Field(
        None, max_length=255,
        description="Optional human-readable device name",
    )


class DeviceTokenResponse(BaseModel):
    """Response after registering a device token."""

    id: int
    user_id: int
    device_type: DeviceType
    device_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Notification Preferences ─────────────────────────────────────────

class NotificationPreferenceUpdate(BaseModel):
    """Partial update for notification preferences. All fields optional."""

    notifications_enabled: Optional[bool] = None
    bedtime_reminder_enabled: Optional[bool] = None
    bedtime_reminder_minutes_before: Optional[int] = Field(
        None, ge=5, le=120,
        description="Minutes before computed bedtime (5–120)",
    )
    wake_reminder_enabled: Optional[bool] = None
    wake_reminder_minutes_before: Optional[int] = Field(
        None, ge=5, le=60,
        description="Minutes before alarm trigger (5–60)",
    )
    habit_alerts_enabled: Optional[bool] = None
    motivational_enabled: Optional[bool] = None
    motivational_time: Optional[time] = Field(
        None,
        description="Preferred local time for daily motivational (HH:MM)",
    )
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    notification_sound: Optional[NotificationSound] = None
    notification_frequency: Optional[NotificationFrequency] = None
    push_enabled: Optional[bool] = None
    email_notifications_enabled: Optional[bool] = None


class NotificationPreferenceResponse(BaseModel):
    """Full notification preference state for the user."""

    id: int
    user_id: int
    notifications_enabled: bool = True
    bedtime_reminder_enabled: bool
    bedtime_reminder_minutes_before: int
    wake_reminder_enabled: bool
    wake_reminder_minutes_before: int
    habit_alerts_enabled: bool
    motivational_enabled: bool
    motivational_time: Optional[time] = None
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    notification_sound: str = NotificationSound.DEFAULT.value
    notification_frequency: str = NotificationFrequency.ALL.value
    push_enabled: bool
    email_notifications_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Notification Feed ────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    """Single notification in the user's feed."""

    id: int
    notification_type: NotificationType
    title: str
    body: str
    data: Optional[Dict[str, Any]] = None
    channel: NotificationChannel
    status: NotificationStatus
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    read_at: Optional[datetime] = None
    push_attempts: int = 0
    email_attempts: int = 0
    last_error: Optional[str] = None
    related_alarm_id: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer(
        "scheduled_at", "sent_at", "delivered_at", "read_at", "created_at"
    )
    def serialize_utc_datetimes(
        self, value: Optional[datetime]
    ) -> Optional[str]:
        """Emit UTC ISO-8601 with explicit Z."""
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


class NotificationListResponse(BaseModel):
    """Paginated notification feed."""

    notifications: List[NotificationResponse]
    total: int
    unread_count: int
    page: int
    per_page: int


# ── Actions ──────────────────────────────────────────────────────────

class NotificationMarkRead(BaseModel):
    """Mark one or more notifications as read."""

    notification_ids: List[int] = Field(
        ..., min_length=1, max_length=100,
        description="IDs of notifications to mark as read",
    )

    @field_validator("notification_ids")
    @classmethod
    def validate_ids(cls, v: List[int]) -> List[int]:
        return sorted(set(v))


class UnreadCountResponse(BaseModel):
    """Badge count for the notification bell."""

    unread_count: int
