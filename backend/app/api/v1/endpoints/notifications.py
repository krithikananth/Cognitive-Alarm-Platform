"""
Notification API endpoints.

Provides FCM device token management, notification preferences CRUD,
in-app notification feed with pagination, unread badge count, read-marking,
and a developer test-send endpoint.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.notification import NotificationType
from app.models.user import User
from app.schemas.notification import (
    DeviceTokenRegister,
    DeviceTokenResponse,
    NotificationListResponse,
    NotificationMarkRead,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


# ── Device Token Management ──────────────────────────────────────

@router.post(
    "/device-token",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register FCM device token",
)
def register_device_token(
    payload: DeviceTokenRegister,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register or reactivate an FCM device token for push notifications."""
    token = NotificationService.register_device_token(
        db,
        user_id=current_user.id,
        fcm_token=payload.fcm_token,
        device_type=payload.device_type.value,
        device_name=payload.device_name,
    )
    return token


@router.delete(
    "/device-token",
    status_code=status.HTTP_200_OK,
    summary="Unregister FCM device token",
)
def remove_device_token(
    fcm_token: str = Query(..., min_length=10, description="Token to remove"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate an FCM device token so it no longer receives pushes."""
    removed = NotificationService.remove_device_token(
        db, current_user.id, fcm_token
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device token not found",
        )
    return {"message": "Device token deactivated"}


# ── Notification Preferences ─────────────────────────────────────

@router.get(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Get notification preferences",
)
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's notification preferences."""
    return NotificationService.get_preferences(db, current_user.id)


@router.put(
    "/preferences",
    response_model=NotificationPreferenceResponse,
    summary="Update notification preferences",
)
def update_preferences(
    payload: NotificationPreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partially update notification preferences."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields to update",
        )
    return NotificationService.update_preferences(
        db, current_user.id, updates
    )


# ── Notification Feed ────────────────────────────────────────────

@router.get(
    "/pending",
    response_model=NotificationListResponse,
    summary="List upcoming pending notifications",
)
def list_pending_notifications(
    within_hours: int = Query(24, ge=1, le=48, description="Lookahead window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return pending notifications for local client-side scheduling.

    Used by web/PWA (and future native) clients as a local-notification
    fallback when FCM background delivery is unavailable. Each item includes
    a stable ``id`` for deduplication tags.
    """
    pending = NotificationService.get_upcoming_pending(
        db, current_user.id, within_hours=within_hours
    )
    return {
        "notifications": pending,
        "total": len(pending),
        "unread_count": 0,
        "page": 1,
        "per_page": len(pending) or 1,
    }


@router.get(
    "/",
    response_model=NotificationListResponse,
    summary="List notifications",
)
def list_notifications(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    notification_type: Optional[str] = Query(
        None, description="Filter by type (bedtime_reminder, wake_reminder, habit_alert, motivational)"
    ),
    unread_only: bool = Query(False, description="Show only unread"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return paginated notification feed for the current user."""
    ntype = None
    if notification_type:
        try:
            ntype = NotificationType(notification_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid notification_type: {notification_type}",
            )

    result = NotificationService.get_user_notifications(
        db,
        user_id=current_user.id,
        page=page,
        per_page=per_page,
        notification_type=ntype,
        unread_only=unread_only,
    )
    return result


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Get unread notification count",
)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the number of unread notifications (for badge display)."""
    count = NotificationService.get_unread_count(db, current_user.id)
    return {"unread_count": count}


@router.post(
    "/mark-read",
    status_code=status.HTTP_200_OK,
    summary="Mark notifications as read",
)
def mark_read(
    payload: NotificationMarkRead,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark one or more notifications as read."""
    count = NotificationService.mark_read(
        db, current_user.id, payload.notification_ids
    )
    return {"marked_read": count}


# ── Test Endpoint (development) ──────────────────────────────────

@router.post(
    "/test",
    status_code=status.HTTP_200_OK,
    summary="Send a test notification",
)
def send_test_notification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a test push notification to all of the current user's devices.

    Also creates an in-app notification entry. Useful for verifying that
    FCM tokens are correctly registered and push delivery is working.
    """
    from app.models.notification import (
        Notification,
        NotificationChannel,
        NotificationStatus,
    )
    from datetime import datetime, timezone
    from app.services.fcm_service import FCMService

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    title = "Test Notification 🧪"
    body = "If you're seeing this, notifications are working correctly!"

    # Send push
    push_result = FCMService.send_to_user_devices(
        db, current_user.id, title, body, {"test": "true"}
    )
    delivered = push_result.get("success_count", 0) > 0

    # Counts only — the raw result carries registration tokens, which must
    # never reach the notification feed or an API response.
    push_summary = {
        "success_count": push_result.get("success_count", 0),
        "failure_count": push_result.get("failure_count", 0),
        "invalid_tokens_retired": len(push_result.get("invalid_tokens") or []),
        "retryable": bool(push_result.get("retryable")),
    }

    errors = push_result.get("errors") or []

    # Create in-app record
    notif = Notification(
        user_id=current_user.id,
        notification_type=NotificationType.MOTIVATIONAL,
        title=title,
        body=body,
        data={
            "test": True,
            "push_delivered": delivered,
            "push_result": push_summary,
        },
        channel=NotificationChannel.IN_APP,
        status=(
            NotificationStatus.DELIVERED if delivered else NotificationStatus.SENT
        ),
        scheduled_at=now_utc,
        sent_at=now_utc,
        delivered_at=now_utc if delivered else None,
        push_attempts=1,
        last_error=None if delivered else "; ".join(errors)[:500] or None,
    )
    db.add(notif)
    db.commit()

    return {
        "message": "Test notification sent",
        "push_result": push_summary,
        "push_delivered": delivered,
        "notification_id": notif.id,
        "fcm_available": FCMService.is_available(),
        "fcm_unavailable_reason": FCMService.unavailable_reason(),
    }
