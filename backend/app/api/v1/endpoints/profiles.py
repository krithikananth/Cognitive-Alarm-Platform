"""
User profile API endpoints.

Provides profile retrieval, updates for sleep schedule, goals, habit
preferences, and habit score (via ``app.services.habit_score``).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.profile import UserProfile, DifficultyPreference
from app.schemas.profile import (
    ProfileResponse,
    ProfileUpdate,
    SleepScheduleUpdate,
    GoalsUpdate,
    HabitPreferencesUpdate,
)
from app.api.deps import get_current_user
from app.services.habit_score import (
    calculate_habit_score,
    calculate_habit_score_for_user,
)
from app.services.profile_service import ProfileService
from app.services.recommendation_cache import RecommendationCache

router = APIRouter(prefix="/profiles", tags=["User Profiles"])


def _get_or_create_profile(user_id: int, db: Session) -> UserProfile:
    """Get the user's profile, creating a default one if it doesn't exist.

    Args:
        user_id: The user's primary key.
        db: Active database session.

    Returns:
        The user's profile instance.
    """
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(
            user_id=user_id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


# Backward-compatible alias for callers that imported the old private helper.
_calculate_habit_score = calculate_habit_score


def _attach_habit_score(profile: UserProfile, db: Session) -> UserProfile:
    """Attach habit score recalculated from behavioral data when available."""
    score_data = calculate_habit_score_for_user(db, profile.user_id, profile)
    profile.habit_score = score_data["habit_score"]
    return profile


@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Get own profile",
)
def get_own_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's profile with computed habit score."""
    profile = _get_or_create_profile(current_user.id, db)
    return _attach_habit_score(profile, db)


@router.put(
    "/me",
    response_model=ProfileResponse,
    summary="Update profile",
)
def update_profile(
    profile_data: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's profile."""
    profile = _get_or_create_profile(current_user.id, db)

    update_data = profile_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    if "difficulty_preference" in update_data and update_data[
        "difficulty_preference"
    ] is not None:
        ProfileService.sync_alarm_difficulties(
            db,
            current_user.id,
            update_data["difficulty_preference"],
            commit=False,
        )

    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _attach_habit_score(profile, db)


@router.patch(
    "/me/sleep-schedule",
    response_model=ProfileResponse,
    summary="Update sleep schedule",
)
def update_sleep_schedule(
    schedule_data: SleepScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's sleep schedule settings."""
    profile = _get_or_create_profile(current_user.id, db)

    update_data = schedule_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _attach_habit_score(profile, db)


@router.patch(
    "/me/goals",
    response_model=ProfileResponse,
    summary="Update productivity goals",
)
def update_goals(
    goals_data: GoalsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's productivity goals."""
    profile = _get_or_create_profile(current_user.id, db)
    profile.productivity_goals = goals_data.productivity_goals
    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _attach_habit_score(profile, db)


@router.patch(
    "/me/habits",
    response_model=ProfileResponse,
    summary="Update habit preferences",
)
def update_habit_preferences(
    habits_data: HabitPreferencesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the current user's habit preferences."""
    profile = _get_or_create_profile(current_user.id, db)
    profile.habit_preferences = habits_data.habit_preferences
    db.commit()
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)
    return _attach_habit_score(profile, db)


@router.get(
    "/me/habit-score",
    summary="Get habit score breakdown",
)
def get_habit_score(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's computed habit score with full breakdown.

    The habit score is calculated using the weighted model:
    - Wake-Up Consistency (35%)
    - Challenge Completion Success (25%)
    - Snooze Reduction (20%)
    - Sleep Schedule Adherence (20%)

    Inputs are recalculated from verified wake events when available.
    """
    profile = _get_or_create_profile(current_user.id, db)
    return calculate_habit_score_for_user(db, current_user.id, profile)
