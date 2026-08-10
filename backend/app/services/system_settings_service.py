"""
Platform system-settings service.

Provides get-or-create singleton access, partial updates, and
broadcast announcements to all active users.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.system_settings import SystemNotificationSettingsUpdate
from app.services.email_service import EmailService
from app.services.fcm_service import FCMService

logger = logging.getLogger(__name__)

_SINGLETON_ID = 1

_DEFAULTS = {
    "email_notifications_enabled": True,
    "push_notifications_enabled": True,
    "maintenance_mode": False,
    "maintenance_message": "The platform is undergoing scheduled maintenance.",
    "habit_score_alert_threshold": 30.0,
    "consistency_alert_threshold": 30.0,
    "snooze_alert_threshold": 30.0,
}

# In-process cache so middleware can check maintenance without a DB round-trip
# (and so TestClient overrides stay consistent with service updates).
_maintenance_cache: Dict[str, Any] = {
    "enabled": False,
    "message": _DEFAULTS["maintenance_message"],
    "warmed": False,
}


class SystemSettingsService:
    """CRUD helpers for the singleton ``system_settings`` row."""

    @classmethod
    def _refresh_maintenance_cache(cls, row: SystemSettings) -> None:
        _maintenance_cache["enabled"] = bool(row.maintenance_mode)
        _maintenance_cache["message"] = (
            row.maintenance_message or _DEFAULTS["maintenance_message"]
        )
        _maintenance_cache["warmed"] = True

    @classmethod
    def get_maintenance_status(cls) -> Tuple[bool, str]:
        """Return ``(enabled, message)`` from the in-process cache."""
        return (
            bool(_maintenance_cache["enabled"]),
            str(_maintenance_cache["message"]),
        )

    @classmethod
    def reset_maintenance_cache(cls) -> None:
        """Reset cache (used by tests between cases)."""
        _maintenance_cache["enabled"] = False
        _maintenance_cache["message"] = _DEFAULTS["maintenance_message"]
        _maintenance_cache["warmed"] = False

    @classmethod
    def get_or_create(cls, db: Session) -> SystemSettings:
        """Return the singleton settings row, creating defaults if missing."""
        row = (
            db.query(SystemSettings)
            .filter(SystemSettings.id == _SINGLETON_ID)
            .first()
        )
        if row is not None:
            cls._refresh_maintenance_cache(row)
            return row

        row = SystemSettings(id=_SINGLETON_ID, **_DEFAULTS)
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
        except Exception:
            db.rollback()
            # Race: another request may have inserted the row
            row = (
                db.query(SystemSettings)
                .filter(SystemSettings.id == _SINGLETON_ID)
                .first()
            )
            if row is None:
                raise
        cls._refresh_maintenance_cache(row)
        return row

    @classmethod
    def update(
        cls,
        db: Session,
        payload: SystemNotificationSettingsUpdate,
        *,
        updated_by_user_id: Optional[int] = None,
    ) -> SystemSettings:
        """Apply a partial update and return the refreshed singleton."""
        row = cls.get_or_create(db)
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(row, key, value)
        if updated_by_user_id is not None:
            row.updated_by_user_id = updated_by_user_id
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(row)
        cls._refresh_maintenance_cache(row)
        logger.info(
            "System settings updated by user_id=%s: %s",
            updated_by_user_id,
            list(data.keys()),
        )
        return row

    @classmethod
    def to_response_dict(
        cls, db: Session, row: Optional[SystemSettings] = None
    ) -> Dict[str, Any]:
        """Serialize settings with infrastructure availability flags."""
        if row is None:
            row = cls.get_or_create(db)
        return {
            "email_notifications_enabled": bool(row.email_notifications_enabled),
            "push_notifications_enabled": bool(row.push_notifications_enabled),
            "maintenance_mode": bool(row.maintenance_mode),
            "maintenance_message": row.maintenance_message
            or _DEFAULTS["maintenance_message"],
            "habit_score_alert_threshold": float(row.habit_score_alert_threshold),
            "consistency_alert_threshold": float(row.consistency_alert_threshold),
            "snooze_alert_threshold": float(row.snooze_alert_threshold),
            "updated_at": row.updated_at,
            "updated_by_user_id": row.updated_by_user_id,
            "smtp_configured": EmailService.is_configured(),
            "fcm_available": FCMService.is_available(),
        }

    @classmethod
    def is_push_globally_enabled(cls, db: Session) -> bool:
        return bool(cls.get_or_create(db).push_notifications_enabled)

    @classmethod
    def is_email_globally_enabled(cls, db: Session) -> bool:
        return bool(cls.get_or_create(db).email_notifications_enabled)

    @classmethod
    def get_alert_thresholds(cls, db: Session) -> Dict[str, float]:
        row = cls.get_or_create(db)
        return {
            "habit_score": float(row.habit_score_alert_threshold),
            "consistency": float(row.consistency_alert_threshold),
            "snooze": float(row.snooze_alert_threshold),
        }

    @classmethod
    def broadcast_announcement(
        cls,
        db: Session,
        *,
        title: str,
        body: str,
        send_push: bool = True,
        created_by_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create in-app (and optionally push) notifications for all active users.

        Announcements bypass per-user preference type filters at dispatch.
        Global push kill-switch still gates FCM delivery.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        users = (
            db.query(User)
            .filter(User.is_active.is_(True))
            .all()
        )

        settings_row = cls.get_or_create(db)
        push_allowed = bool(settings_row.push_notifications_enabled) and send_push

        created = 0
        push_queued = 0
        data_payload = {
            "announcement": True,
            "broadcast_by": created_by_user_id,
        }

        for user in users:
            in_app = Notification(
                user_id=user.id,
                notification_type=NotificationType.ANNOUNCEMENT,
                title=title,
                body=body,
                data=data_payload,
                channel=NotificationChannel.IN_APP,
                status=NotificationStatus.PENDING,
                scheduled_at=now,
            )
            db.add(in_app)
            created += 1

            if push_allowed:
                push = Notification(
                    user_id=user.id,
                    notification_type=NotificationType.ANNOUNCEMENT,
                    title=title,
                    body=body,
                    data=data_payload,
                    channel=NotificationChannel.PUSH,
                    status=NotificationStatus.PENDING,
                    scheduled_at=now,
                )
                db.add(push)
                created += 1
                push_queued += 1

        db.commit()
        logger.info(
            "Broadcast announcement to %d users (%d notifications, %d push)",
            len(users),
            created,
            push_queued,
        )
        return {
            "users_targeted": len(users),
            "notifications_created": created,
            "push_queued": push_queued,
            "title": title,
            "body": body,
        }
