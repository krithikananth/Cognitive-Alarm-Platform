"""
Platform-wide system settings (singleton).

Stores admin-configurable ops toggles for notifications, maintenance mode,
and habit-alert thresholds. Distinct from per-user ``notification_preferences``
and from env-based infrastructure config (SMTP / FCM credentials).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class SystemSettings(Base):
    """
    Singleton row (``id=1``) for platform notification / ops settings.

    Attributes:
        id: Always ``1`` for the singleton row.
        email_notifications_enabled: Global kill-switch for email channel.
        push_notifications_enabled: Global kill-switch for FCM push.
        maintenance_mode: When True, non-admin mutating APIs return 503.
        maintenance_message: Optional banner / status text during maintenance.
        habit_score_alert_threshold: Habit score below which alerts fire.
        consistency_alert_threshold: Wake consistency below which alerts fire.
        snooze_alert_threshold: Snooze-reduction score below which alerts fire.
        updated_by_user_id: Last admin who saved settings.
        created_at / updated_at: Audit timestamps (UTC).
    """

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, default=1)

    # ── Global channel toggles ────────────────────────────────────
    email_notifications_enabled = Column(Boolean, default=True, nullable=False)
    push_notifications_enabled = Column(Boolean, default=True, nullable=False)

    # ── Maintenance ───────────────────────────────────────────────
    maintenance_mode = Column(Boolean, default=False, nullable=False)
    maintenance_message = Column(
        String(500),
        default="The platform is undergoing scheduled maintenance.",
        nullable=False,
    )

    # ── Habit / system alert thresholds (0–100 scores) ────────────
    habit_score_alert_threshold = Column(Float, default=30.0, nullable=False)
    consistency_alert_threshold = Column(Float, default=30.0, nullable=False)
    snooze_alert_threshold = Column(Float, default=30.0, nullable=False)

    updated_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_by = relationship("User", foreign_keys=[updated_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<SystemSettings(id={self.id}, "
            f"email={self.email_notifications_enabled}, "
            f"push={self.push_notifications_enabled}, "
            f"maintenance={self.maintenance_mode})>"
        )
