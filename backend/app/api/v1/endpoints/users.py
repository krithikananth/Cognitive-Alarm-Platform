"""User management API endpoints (admin + current-user profile helpers)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.profile import UserProfile, DifficultyPreference
from app.schemas.user import UserResponse, UserUpdate, AdminUserUpdate
from app.api.deps import get_current_user, get_current_admin
from app.api.v1.endpoints.profiles import _get_or_create_profile
from app.services.habit_score import (
    calculate_habit_score_for_user,
    load_verified_wake_events,
    resolve_habit_score_inputs,
)
from app.services.profile_service import ProfileService
from app.services.recommendation_cache import RecommendationCache

router = APIRouter(prefix="/users", tags=["Users"])


class ProfileUserUpdate(BaseModel):
    """Mixed user + profile fields accepted by the frontend profile form."""

    full_name: Optional[str] = None
    username: Optional[str] = None
    timezone: Optional[str] = None


class SleepScheduleBody(BaseModel):
    preferred_wakeup_time: Optional[str] = None
    preferred_wake_time: Optional[str] = None
    sleep_duration_hours: Optional[float] = Field(None, ge=1.0, le=24.0)


class PreferencesBody(BaseModel):
    preferred_challenge_types: Optional[list[str]] = None
    difficulty_preference: Optional[str] = None
    productivity_goals: Optional[Any] = None


def _profile_bundle(user: User, profile: UserProfile) -> dict:
    """Shape expected by the frontend Profile page."""
    wake = profile.preferred_wake_time
    wake_str = wake.strftime("%H:%M:%S") if wake else None
    habits = profile.habit_preferences or {}
    goals = profile.productivity_goals
    if isinstance(goals, list):
        goals_str = ", ".join(goals)
    else:
        goals_str = goals or ""
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "timezone": profile.timezone,
        "is_active": user.is_active,
        "profile": {
            "preferred_wakeup_time": wake_str,
            "preferred_wake_time": wake_str,
            "sleep_duration_hours": profile.sleep_duration_hours,
            "timezone": profile.timezone,
            "difficulty_preference": (
                profile.difficulty_preference.value
                if profile.difficulty_preference
                else "medium"
            ),
            "preferred_challenge_types": habits.get(
                "preferred_challenge_types", ["math", "logic"]
            ),
            "productivity_goals": goals_str,
            "habit_preferences": habits,
            "streak_days": profile.streak_days,
            "best_streak": profile.best_streak,
        },
    }


def _weekly_tracker(db: Session, user_id: int) -> list[dict]:
    """Build a simple 7-day on-time tracker from challenge logs."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=6)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    logs = (
        db.query(AlarmChallengeLog)
        .filter(
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= start,
            AlarmChallengeLog.is_correct == True,  # noqa: E712
        )
        .all()
    )
    by_day = {i: "pending" for i in range(7)}
    for log in logs:
        created = log.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day_idx = (created.date() - start.date()).days
        if 0 <= day_idx <= 6:
            by_day[day_idx] = "on_time"
    return [
        {
            "day": (start + timedelta(days=i)).strftime("%a").upper()[:3],
            "status": by_day[i],
        }
        for i in range(7)
    ]


# ── Current-user profile routes (must be registered before /{user_id}) ──


@router.get("/profile")
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's profile bundle."""
    profile = _get_or_create_profile(current_user.id, db)
    return _profile_bundle(current_user, profile)


@router.put("/profile")
def update_my_profile(
    data: ProfileUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user fields and optional timezone on the profile."""
    profile = _get_or_create_profile(current_user.id, db)
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.username is not None:
        conflict = (
            db.query(User)
            .filter(User.username == data.username, User.id != current_user.id)
            .first()
        )
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken",
            )
        current_user.username = data.username
    if data.timezone is not None:
        profile.timezone = data.timezone
    db.commit()
    db.refresh(current_user)
    db.refresh(profile)
    return _profile_bundle(current_user, profile)


@router.get("/profile/stats")
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dashboard stats for the current user."""
    profile = _get_or_create_profile(current_user.id, db)
    score = calculate_habit_score_for_user(db, current_user.id, profile)
    active_alarms = (
        db.query(Alarm)
        .filter(Alarm.user_id == current_user.id, Alarm.is_active == True)  # noqa: E712
        .count()
    )
    # Derive dismiss/snooze totals from the same wake-event replay as habit score
    # so success rate cannot drift from stale profile counters.
    inputs = resolve_habit_score_inputs(
        profile, load_verified_wake_events(db, current_user.id)
    )
    if isinstance(inputs, dict):
        dismissed = int(inputs.get("total_alarms_dismissed", 0) or 0)
        snoozes = int(inputs.get("total_snoozes", 0) or 0)
    else:
        dismissed = int(getattr(inputs, "total_alarms_dismissed", 0) or 0)
        snoozes = int(getattr(inputs, "total_snoozes", 0) or 0)
    total_events = dismissed + snoozes
    if total_events > 0:
        success_rate = (dismissed / total_events) * 100
    else:
        success_rate = 0.0

    tracker = _weekly_tracker(db, current_user.id)
    weekly_on_time = sum(1 for d in tracker if d["status"] == "on_time")
    wake = profile.preferred_wake_time
    return {
        "active_alarms": active_alarms,
        "current_habit_score": score["habit_score"],
        "current_streak": profile.streak_days,
        "wakeup_success_rate": round(success_rate, 2),
        "preferred_wakeup_time": wake.strftime("%H:%M:%S") if wake else None,
        "weekly_on_time": weekly_on_time,
        "weekly_total": 7,
        "weekly_tracker": tracker,
    }


@router.put("/profile/sleep-schedule")
def update_my_sleep_schedule(
    data: SleepScheduleBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update sleep schedule fields used by the frontend."""
    from datetime import time as time_cls

    profile = _get_or_create_profile(current_user.id, db)
    raw = data.preferred_wakeup_time or data.preferred_wake_time
    if raw:
        parts = [int(p) for p in raw.split(":")[:2]]
        profile.preferred_wake_time = time_cls(parts[0], parts[1])
    if data.sleep_duration_hours is not None:
        profile.sleep_duration_hours = data.sleep_duration_hours
    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _profile_bundle(current_user, profile)


@router.put("/profile/goals")
def update_my_goals(
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update productivity goals (accepts string or list)."""
    profile = _get_or_create_profile(current_user.id, db)
    goals = data.get("productivity_goals", data.get("goals"))
    if isinstance(goals, str):
        profile.productivity_goals = [
            g.strip() for g in goals.split(",") if g.strip()
        ]
    elif isinstance(goals, list):
        profile.productivity_goals = goals
    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _profile_bundle(current_user, profile)


@router.get("/profile/preferences")
def get_my_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return difficulty / challenge preferences for the current user."""
    profile = _get_or_create_profile(current_user.id, db)
    habits = profile.habit_preferences or {}
    goals = profile.productivity_goals
    if isinstance(goals, list):
        goals_out = goals
    elif goals:
        goals_out = [goals]
    else:
        goals_out = []
    return {
        "preferred_challenge_types": habits.get(
            "preferred_challenge_types", ["math", "logic"]
        ),
        "difficulty_preference": (
            profile.difficulty_preference.value
            if profile.difficulty_preference
            else "medium"
        ),
        "productivity_goals": goals_out,
        "habit_preferences": habits,
    }


@router.put("/profile/preferences")
def update_my_preferences(
    data: PreferencesBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update difficulty / challenge preferences."""
    profile = _get_or_create_profile(current_user.id, db)
    habits = dict(profile.habit_preferences or {})
    if data.preferred_challenge_types is not None:
        habits["preferred_challenge_types"] = data.preferred_challenge_types
    profile.habit_preferences = habits
    if data.difficulty_preference:
        try:
            profile.difficulty_preference = DifficultyPreference(
                data.difficulty_preference.lower()
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid difficulty: {data.difficulty_preference}",
            )
        # Keep existing alarms aligned so future challenges use the preference
        ProfileService.sync_alarm_difficulties(
            db,
            current_user.id,
            profile.difficulty_preference,
            commit=False,
        )
    if data.productivity_goals is not None:
        goals = data.productivity_goals
        if isinstance(goals, str):
            profile.productivity_goals = [
                g.strip() for g in goals.split(",") if g.strip()
            ]
        elif isinstance(goals, list):
            profile.productivity_goals = goals
    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _profile_bundle(current_user, profile)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete the authenticated user's account."""
    db.delete(current_user)
    db.commit()
    return None


# ── Admin user management ──


@router.get("/", response_model=list[UserResponse])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """List all users (admin only)."""
    users = db.query(User).offset(skip).limit(limit).all()
    return users


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Get a specific user by ID (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    user_update: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Update a user's fields including role and active state (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    update_data = user_update.model_dump(exclude_unset=True)
    if "role" in update_data and update_data["role"] is not None:
        try:
            update_data["role"] = UserRole(update_data["role"])
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {update_data['role']}",
            )

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Deactivate a user account (admin only). Admins cannot deactivate themselves."""
    if str(current_user.id) == str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    user.is_active = False
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/activate", response_model=UserResponse)
def activate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Re-activate a deactivated user account (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    """Delete a user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    db.delete(user)
    db.commit()
    return None
