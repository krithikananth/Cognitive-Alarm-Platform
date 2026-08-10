"""
Pydantic schemas for platform system / notification settings.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SystemNotificationSettingsUpdate(BaseModel):
    """Partial update for admin notification / ops settings."""

    email_notifications_enabled: Optional[bool] = None
    push_notifications_enabled: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = Field(
        None, min_length=1, max_length=500
    )
    habit_score_alert_threshold: Optional[float] = Field(
        None, ge=0, le=100,
        description="Alert when habit score falls below this value",
    )
    consistency_alert_threshold: Optional[float] = Field(
        None, ge=0, le=100,
        description="Alert when wake-up consistency falls below this value",
    )
    snooze_alert_threshold: Optional[float] = Field(
        None, ge=0, le=100,
        description="Alert when snooze-reduction score falls below this value",
    )


class SystemNotificationSettingsResponse(BaseModel):
    """Current platform notification settings plus infrastructure status."""

    email_notifications_enabled: bool
    push_notifications_enabled: bool
    maintenance_mode: bool
    maintenance_message: str
    habit_score_alert_threshold: float
    consistency_alert_threshold: float
    snooze_alert_threshold: float
    updated_at: Optional[datetime] = None
    updated_by_user_id: Optional[int] = None
    # Read-only infra snapshot (env / credentials — not editable here)
    smtp_configured: bool = False
    fcm_available: bool = False

    model_config = {"from_attributes": True}


class BroadcastAnnouncementRequest(BaseModel):
    """Admin broadcast announcement to all active users."""

    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1, max_length=2000)
    send_push: bool = Field(
        True,
        description="Also enqueue push channel when global push is enabled",
    )


class BroadcastAnnouncementResponse(BaseModel):
    """Result of a broadcast announcement."""

    users_targeted: int
    notifications_created: int
    push_queued: int
    title: str
    body: str


class SystemStatusResponse(BaseModel):
    """Public (unauthenticated) platform status for maintenance banners."""

    maintenance_mode: bool
    maintenance_message: Optional[str] = None
