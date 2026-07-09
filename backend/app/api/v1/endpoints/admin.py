"""
Admin API endpoints.

Provides admin-only dashboard and statistics endpoints for platform management.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.alarm import Alarm
from app.api.deps import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the current user has ADMIN role."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


@router.get(
    "/dashboard",
    summary="Get admin dashboard statistics",
)
def admin_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Return admin dashboard statistics.

    Includes total user count, total alarm count, and a per-user
    breakdown with alarm counts. Only accessible to ADMIN users.
    """
    total_users = db.query(func.count(User.id)).scalar()
    total_alarms = db.query(func.count(Alarm.id)).scalar()

    # Per-user stats with alarm counts via left outer join
    user_alarm_counts = (
        db.query(User, func.count(Alarm.id).label("alarm_count"))
        .outerjoin(Alarm, Alarm.user_id == User.id)
        .group_by(User.id)
        .all()
    )

    users = []
    for user, alarm_count in user_alarm_counts:
        users.append({
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "total_alarms": alarm_count,
        })

    return {
        "total_users": total_users,
        "total_alarms": total_alarms,
        "users": users,
    }
