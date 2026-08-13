"""
Notification ORM models.

Defines ``notifications``, ``user_device_tokens``, and
``notification_preferences`` tables for the multi-channel notification
system (FCM push, in-app feed, email).
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


# ── Enums ────────────────────────────────────────────────────────────

class NotificationType(str, enum.Enum):
    """Categories of notifications the platform can send."""

    BEDTIME_REMINDER = "bedtime_reminder"
    WAKE_REMINDER = "wake_reminder"
    ALARM_TRIGGER = "alarm_trigger"
    HABIT_ALERT = "habit_alert"
    CHALLENGE_REMINDER = "challenge_reminder"
    PROGRESS_UPDATE = "progress_update"
    MOTIVATIONAL = "motivational"
    ANNOUNCEMENT = "announcement"


class NotificationChannel(str, enum.Enum):
    """Delivery channels for notifications."""

    PUSH = "push"
    IN_APP = "in_app"
    EMAIL = "email"


class NotificationStatus(str, enum.Enum):
    """Lifecycle states of a notification."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    READ = "read"


class DeviceType(str, enum.Enum):
    """Supported device types for FCM tokens."""

    WEB = "web"
    IOS = "ios"
    ANDROID = "android"


# ── Models ───────────────────────────────────────────────────────────

class Notification(Base):
    """
    SQLAlchemy model representing a scheduled or delivered notification.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: Foreign key to the target user.
        notification_type: Category (bedtime, wake, habit, motivational).
        title: Short notification title.
        body: Notification body text.
        data: Optional JSON payload for deep-linking / metadata.
        channel: Delivery channel (push, in_app, email).
        status: Current lifecycle state.
        scheduled_at: When the notification should be sent (UTC).
        sent_at: When the notification was actually dispatched.
        delivered_at: When an external channel (FCM/SMTP) accepted the message.
        read_at: When the user read/acknowledged the notification.
        push_attempts: Number of FCM delivery attempts made so far.
        email_attempts: Number of SMTP delivery attempts made so far.
        next_retry_at: When the next delivery retry is due (UTC), if any.
        last_error: Truncated reason for the most recent delivery failure.
        related_alarm_id: Optional FK to the alarm that triggered this.
        created_at: Timestamp of record creation (UTC).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_status", "user_id", "status"),
        Index("ix_notifications_user_type", "user_id", "notification_type"),
        Index("ix_notifications_scheduled", "status", "scheduled_at"),
        Index("ix_notifications_retry", "next_retry_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    notification_type = Column(
        Enum(NotificationType), nullable=False
    )
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)
    channel = Column(
        Enum(NotificationChannel),
        default=NotificationChannel.IN_APP,
        nullable=False,
    )
    status = Column(
        Enum(NotificationStatus),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)

    # ── Delivery tracking / retry bookkeeping ─────────────────────
    push_attempts = Column(Integer, default=0, nullable=False)
    email_attempts = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)

    related_alarm_id = Column(
        Integer,
        ForeignKey("alarms.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────
    user = relationship("User", backref="notifications")

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, type='{self.notification_type}', "
            f"status='{self.status}')>"
        )


class UserDeviceToken(Base):
    """
    SQLAlchemy model for FCM device token registration.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: Foreign key to the owning user.
        fcm_token: Firebase Cloud Messaging registration token.
        device_type: Platform type (web, ios, android).
        device_name: Optional human-readable device identifier.
        is_active: Whether this token should receive pushes.
        last_success_at: Last time FCM accepted a push for this token (UTC).
        failure_count: Consecutive transient failures since the last success.
        deactivated_at: When the token was retired (UTC).
        deactivated_reason: Why the token was retired (e.g. FCM ``UNREGISTERED``).
        created_at: Timestamp of registration (UTC).
        updated_at: Timestamp of last update (UTC).
    """

    __tablename__ = "user_device_tokens"
    __table_args__ = (
        Index("ix_device_tokens_user_active", "user_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    fcm_token = Column(String(512), nullable=False, unique=True)
    device_type = Column(
        Enum(DeviceType), default=DeviceType.WEB, nullable=False
    )
    device_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # ── Health / cleanup bookkeeping ──────────────────────────────
    last_success_at = Column(DateTime, nullable=True)
    failure_count = Column(Integer, default=0, nullable=False)
    deactivated_at = Column(DateTime, nullable=True)
    deactivated_reason = Column(String(255), nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────
    user = relationship("User", backref="device_tokens")

    def __repr__(self) -> str:
        return (
            f"<UserDeviceToken(id={self.id}, user_id={self.user_id}, "
            f"type='{self.device_type}', active={self.is_active})>"
        )


class NotificationPreference(Base):
    """
    SQLAlchemy model for per-user notification preferences.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: Foreign key to the user (one-to-one).
        bedtime_reminder_enabled: Send bedtime reminders.
        bedtime_reminder_minutes_before: Minutes before computed bedtime.
        wake_reminder_enabled: Send pre-alarm wake reminders.
        wake_reminder_minutes_before: Minutes before alarm trigger.
        habit_alerts_enabled: Alert on declining habit metrics.
        motivational_enabled: Daily motivational notification.
        motivational_time: Preferred time for motivational messages.
        notifications_enabled: Master on/off for all scheduled notifications.
        bedtime_reminder_enabled: Send bedtime reminders.
        bedtime_reminder_minutes_before: Minutes before computed bedtime.
        wake_reminder_enabled: Send pre-alarm wake reminders.
        wake_reminder_minutes_before: Minutes before alarm trigger.
        habit_alerts_enabled: Alert on declining habit metrics.
        challenge_reminders_enabled: Nudge to practise a cognitive challenge.
        progress_updates_enabled: Weekly progress / milestone recap.
        motivational_enabled: Daily motivational notification.
        motivational_time: Preferred time for motivational messages.
        quiet_hours_start: No-send window start.
        quiet_hours_end: No-send window end.
        notification_sound: Preferred notification sound key.
        notification_frequency: Cadence filter (all / essential / minimal).
        push_enabled: Whether push notifications are opted-in.
        email_notifications_enabled: Whether email channel is enabled.
        created_at: Timestamp of record creation (UTC).
        updated_at: Timestamp of last update (UTC).
    """

    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    # ── Master toggle ─────────────────────────────────────────────
    notifications_enabled = Column(Boolean, default=True, nullable=False)

    # ── Bedtime reminders ─────────────────────────────────────────
    bedtime_reminder_enabled = Column(Boolean, default=True, nullable=False)
    bedtime_reminder_minutes_before = Column(
        Integer, default=30, nullable=False
    )

    # ── Wake reminders ────────────────────────────────────────────
    wake_reminder_enabled = Column(Boolean, default=True, nullable=False)
    wake_reminder_minutes_before = Column(Integer, default=15, nullable=False)

    # ── Habit alerts ──────────────────────────────────────────────
    habit_alerts_enabled = Column(Boolean, default=True, nullable=False)

    # ── Challenge practice reminders ──────────────────────────────
    challenge_reminders_enabled = Column(Boolean, default=True, nullable=False)

    # ── Weekly progress recap ─────────────────────────────────────
    progress_updates_enabled = Column(Boolean, default=True, nullable=False)

    # ── Daily motivational ────────────────────────────────────────
    motivational_enabled = Column(Boolean, default=True, nullable=False)
    motivational_time = Column(Time, nullable=True)  # user's local time

    # ── Quiet hours ───────────────────────────────────────────────
    quiet_hours_start = Column(Time, nullable=True)
    quiet_hours_end = Column(Time, nullable=True)

    # ── Sound & frequency ─────────────────────────────────────────
    notification_sound = Column(String(32), default="default", nullable=False)
    notification_frequency = Column(String(32), default="all", nullable=False)

    # ── Channel toggles ──────────────────────────────────────────
    push_enabled = Column(Boolean, default=True, nullable=False)
    email_notifications_enabled = Column(Boolean, default=False, nullable=False)

    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────
    user = relationship("User", backref="notification_preferences")

    def __repr__(self) -> str:
        return (
            f"<NotificationPreference(id={self.id}, user_id={self.user_id})>"
        )
