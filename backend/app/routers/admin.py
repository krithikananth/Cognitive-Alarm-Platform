"""
Admin management API endpoints.

Provides admin-only operations for user management, role assignment,
and platform oversight. All endpoints require admin role.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.user import User, UserProfile
from app.models.alarm import Alarm, AlarmEvent
from app.models.habit import HabitScore
from app.schemas.user_schema import (
    UserResponse, UserRoleUpdate, UserFullResponse, ProfileResponse,
)
from app.middleware.auth_middleware import get_current_user, require_role


router = APIRouter(prefix="/admin", tags=["Admin Management"])


# ═══════════════════════════════════════════
# User Management (Admin Only)
# ═══════════════════════════════════════════

@router.get(
    "/users",
    response_model=dict,
    summary="List all users (Admin only)",
)
async def list_all_users(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search by email or username"),
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """List all registered users with pagination, filtering, and search.

    Admin-only endpoint for platform user management.
    """
    query = select(User)

    # Apply filters
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            (User.email.ilike(search_pattern)) | (User.username.ilike(search_pattern))
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
    query = query.order_by(User.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "users": [UserResponse.model_validate(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


@router.get(
    "/users/{user_id}",
    response_model=UserFullResponse,
    summary="Get user details (Admin only)",
)
async def get_user_details(
    user_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific user including their profile."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(User).options(selectinload(User.profile)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    profile_resp = None
    if user.profile:
        import json
        habit_prefs = user.profile.habit_preferences
        if isinstance(habit_prefs, str):
            try:
                habit_prefs = json.loads(habit_prefs)
            except (json.JSONDecodeError, TypeError):
                habit_prefs = {}

        challenge_types = user.profile.preferred_challenge_types
        if isinstance(challenge_types, str):
            try:
                challenge_types = json.loads(challenge_types)
            except (json.JSONDecodeError, TypeError):
                challenge_types = []

        profile_resp = ProfileResponse(
            id=user.profile.id,
            user_id=user.profile.user_id,
            preferred_wakeup_time=user.profile.preferred_wakeup_time,
            sleep_duration_hours=user.profile.sleep_duration_hours,
            difficulty_preference=user.profile.difficulty_preference,
            productivity_goals=user.profile.productivity_goals,
            habit_preferences=habit_prefs,
            notification_enabled=user.profile.notification_enabled,
            sound_preference=user.profile.sound_preference,
            preferred_challenge_types=challenge_types,
            created_at=user.profile.created_at,
            updated_at=user.profile.updated_at,
        )

    return UserFullResponse(
        user=UserResponse.model_validate(user),
        profile=profile_resp,
    )


@router.put(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Update user role (Admin only)",
)
async def update_user_role(
    user_id: str,
    data: UserRoleUpdate,
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Change a user's role. Available roles: user, wellness_coach, admin.

    Admins cannot demote themselves to prevent lockout.
    """
    if user_id == current_user.id and data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own admin role",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.role = data.role
    await db.flush()
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/activate",
    response_model=UserResponse,
    summary="Activate user account (Admin only)",
)
async def activate_user(
    user_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Re-activate a deactivated user account."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_active = True
    await db.flush()
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    summary="Deactivate user account (Admin only)",
)
async def deactivate_user(
    user_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account (soft delete).

    Admins cannot deactivate their own account.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_active = False
    await db.flush()
    return UserResponse.model_validate(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete user account (Admin only)",
)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user and all associated data.

    Admins cannot delete their own account.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await db.delete(user)
    await db.flush()
    return {"message": f"User {user.username} deleted successfully"}


# ═══════════════════════════════════════════
# Platform Statistics (Admin Only)
# ═══════════════════════════════════════════

@router.get(
    "/stats",
    summary="Platform statistics (Admin only)",
)
async def get_platform_stats(
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide statistics for the admin dashboard."""
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0
    total_alarms = (await db.execute(select(func.count(Alarm.id)))).scalar() or 0
    active_alarms = (await db.execute(
        select(func.count(Alarm.id)).where(Alarm.is_active == True)
    )).scalar() or 0
    total_events = (await db.execute(select(func.count(AlarmEvent.id)))).scalar() or 0

    # Role distribution
    role_counts = {}
    for role in ["user", "wellness_coach", "admin"]:
        count = (await db.execute(
            select(func.count(User.id)).where(User.role == role)
        )).scalar() or 0
        role_counts[role] = count

    return {
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": total_users - active_users,
        "total_alarms": total_alarms,
        "active_alarms": active_alarms,
        "total_alarm_events": total_events,
        "role_distribution": role_counts,
    }
