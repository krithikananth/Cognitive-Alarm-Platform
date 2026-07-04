"""
User profile and habit management API endpoints.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.user_service import UserService
from app.schemas.user_schema import (
    UserResponse, UserUpdate, UserFullResponse,
    ProfileResponse, ProfileUpdate, SleepScheduleUpdate, GoalsUpdate,
)
from app.middleware.auth_middleware import get_current_user
from app.models.user import User


router = APIRouter(prefix="/users", tags=["Users & Profiles"])


# ═══════════════════════════════════════════
# User Info
# ═══════════════════════════════════════════

@router.get("/profile", response_model=UserFullResponse)
async def get_full_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user with full profile data."""
    service = UserService(db)
    return await service.get_user_with_profile(current_user.id)


@router.put("/profile", response_model=UserResponse)
async def update_user(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update basic user information (name, timezone, etc.)."""
    service = UserService(db)
    return await service.update_user(current_user.id, data)


# ═══════════════════════════════════════════
# Profile Preferences
# ═══════════════════════════════════════════

@router.get("/profile/preferences", response_model=ProfileResponse)
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user profile preferences."""
    service = UserService(db)
    return await service.get_profile(current_user.id)


@router.put("/profile/preferences", response_model=ProfileResponse)
async def update_preferences(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update profile preferences (difficulty, challenge types, etc.)."""
    service = UserService(db)
    return await service.update_profile(current_user.id, data)


# ═══════════════════════════════════════════
# Sleep Schedule
# ═══════════════════════════════════════════

@router.put("/profile/sleep-schedule", response_model=ProfileResponse)
async def update_sleep_schedule(
    data: SleepScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update preferred wake-up time and sleep duration."""
    service = UserService(db)
    return await service.update_sleep_schedule(current_user.id, data)


# ═══════════════════════════════════════════
# Goals
# ═══════════════════════════════════════════

@router.put("/profile/goals", response_model=ProfileResponse)
async def update_goals(
    data: GoalsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update productivity goals and difficulty preference."""
    service = UserService(db)
    return await service.update_goals(current_user.id, data)


# ═══════════════════════════════════════════
# Stats
# ═══════════════════════════════════════════

@router.get("/profile/stats")
async def get_user_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated user statistics (alarms, scores, streaks)."""
    service = UserService(db)
    return await service.get_user_stats(current_user.id)


# ═══════════════════════════════════════════
# Account
# ═══════════════════════════════════════════

@router.delete("/account")
async def deactivate_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete (deactivate) the current user account."""
    service = UserService(db)
    return await service.deactivate_account(current_user.id)
