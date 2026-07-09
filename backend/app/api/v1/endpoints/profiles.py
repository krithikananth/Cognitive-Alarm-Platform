"""
User profile API endpoints.

Provides profile retrieval, updates for sleep schedule, goals, habit
preferences, and habit score calculation.
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


def _calculate_habit_score(profile: UserProfile) -> dict:
    """Calculate the weighted habit score based on the project specification.

    Habit Score =
        Wake-Up Consistency (35%) +
        Challenge Completion Success (25%) +
        Snooze Reduction (20%) +
        Sleep Schedule Adherence (20%)

    Args:
        profile: The user's profile instance.

    Returns:
        Dictionary with overall score and component breakdown.
    """
    # Wake-up consistency (0-100 scale)
    wake_up_score = min(profile.wake_up_consistency_score, 100.0)

    # Challenge completion success - based on dismissals vs total
    total_events = profile.total_alarms_dismissed + profile.total_snoozes
    if total_events > 0:
        challenge_score = (profile.total_alarms_dismissed / total_events) * 100
    else:
        challenge_score = 50.0  # neutral default

    # Snooze reduction - fewer snoozes = higher score
    if total_events > 0:
        snooze_ratio = profile.total_snoozes / total_events
        snooze_score = max(0, (1 - snooze_ratio)) * 100
    else:
        snooze_score = 50.0

    # Sleep schedule adherence - based on streak
    max_streak_target = 30  # 30-day target for 100%
    adherence_score = min((profile.streak_days / max_streak_target) * 100, 100.0)

    # Weighted calculation
    overall = (
        wake_up_score * 0.35
        + challenge_score * 0.25
        + snooze_score * 0.20
        + adherence_score * 0.20
    )

    return {
        "habit_score": round(overall, 2),
        "breakdown": {
            "wake_up_consistency": round(wake_up_score, 2),
            "challenge_completion": round(challenge_score, 2),
            "snooze_reduction": round(snooze_score, 2),
            "sleep_adherence": round(adherence_score, 2),
        },
        "weights": {
            "wake_up_consistency": 0.35,
            "challenge_completion": 0.25,
            "snooze_reduction": 0.20,
            "sleep_adherence": 0.20,
        },
    }


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
    score_data = _calculate_habit_score(profile)
    # Attach computed score for response serialization
    profile.habit_score = score_data["habit_score"]
    return profile


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

    db.commit()
    db.refresh(profile)
    score_data = _calculate_habit_score(profile)
    profile.habit_score = score_data["habit_score"]
    return profile


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
    score_data = _calculate_habit_score(profile)
    profile.habit_score = score_data["habit_score"]
    return profile


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
    score_data = _calculate_habit_score(profile)
    profile.habit_score = score_data["habit_score"]
    return profile


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
    score_data = _calculate_habit_score(profile)
    profile.habit_score = score_data["habit_score"]
    return profile


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
    """
    profile = _get_or_create_profile(current_user.id, db)
    return _calculate_habit_score(profile)
