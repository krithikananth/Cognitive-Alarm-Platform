"""
Profile service layer.

Handles CRUD and partial updates for ``UserProfile``. Habit score
computation is delegated to ``app.services.habit_score``.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.alarm import Alarm
from app.models.profile import DifficultyPreference, UserProfile
from app.schemas.profile import (
    GoalsUpdate,
    HabitPreferencesUpdate,
    ProfileCreate,
    ProfileUpdate,
    SleepScheduleUpdate,
)
from app.services.challenge_service import ChallengeService
from app.services.habit_score import calculate_habit_score as _calculate_habit_score


class ProfileService:
    """Service class for user-profile operations."""

    @staticmethod
    def sync_alarm_difficulties(
        db: Session,
        user_id: int,
        difficulty: str,
        *,
        commit: bool = False,
    ) -> int:
        """
        Align existing alarms with the user's difficulty preference.

        Keeps per-alarm ``challenge_difficulty`` compatible with the challenge
        engine baseline after a profile preference change. Returns the number
        of alarms updated.
        """
        raw = (
            difficulty.value
            if hasattr(difficulty, "value")
            else difficulty
        )
        # Reuse engine normalization (invalid → medium)
        level = ChallengeService.resolve_baseline_difficulty(
            None, str(raw) if raw is not None else None
        )

        updated = (
            db.query(Alarm)
            .filter(Alarm.user_id == user_id)
            .update(
                {Alarm.challenge_difficulty: level},
                synchronize_session=False,
            )
        )
        if commit:
            db.commit()
        return int(updated or 0)

    @staticmethod
    def get_profile(db: Session, user_id: int) -> UserProfile:
        """
        Retrieve the profile for a given user.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.

        Returns:
            The ``UserProfile`` instance.

        Raises:
            HTTPException: 404 if no profile exists for the user.
        """
        profile: Optional[UserProfile] = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found. Please create a profile first.",
            )
        return profile

    @staticmethod
    def create_profile(
        db: Session, user_id: int, data: ProfileCreate
    ) -> UserProfile:
        """
        Create a profile for a user that does not yet have one.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated profile creation payload.

        Returns:
            The newly created ``UserProfile``.

        Raises:
            HTTPException: 400 if a profile already exists.
        """
        existing = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Profile already exists. Use update instead.",
            )

        profile = UserProfile(
            user_id=user_id,
            **data.model_dump(exclude_unset=True),
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def update_profile(
        db: Session, user_id: int, data: ProfileUpdate
    ) -> UserProfile:
        """
        Partially update a user's profile.

        Only non-``None`` / explicitly-set fields from *data* are applied.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated partial-update payload.

        Returns:
            The updated ``UserProfile``.

        Raises:
            HTTPException: 404 if no profile exists.
        """
        profile = ProfileService.get_profile(db, user_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(profile, field, value)

        if "difficulty_preference" in update_data and update_data[
            "difficulty_preference"
        ] is not None:
            ProfileService.sync_alarm_difficulties(
                db,
                user_id,
                update_data["difficulty_preference"],
                commit=False,
            )

        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def update_sleep_schedule(
        db: Session, user_id: int, data: SleepScheduleUpdate
    ) -> UserProfile:
        """
        Update only sleep-related fields on the user's profile.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated sleep-schedule payload.

        Returns:
            The updated ``UserProfile``.

        Raises:
            HTTPException: 404 if no profile exists.
        """
        profile = ProfileService.get_profile(db, user_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(profile, field, value)

        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def update_goals(
        db: Session, user_id: int, data: GoalsUpdate
    ) -> UserProfile:
        """
        Replace the user's productivity goals list.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated goals payload.

        Returns:
            The updated ``UserProfile``.

        Raises:
            HTTPException: 404 if no profile exists.
        """
        profile = ProfileService.get_profile(db, user_id)
        profile.productivity_goals = data.productivity_goals
        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def update_habit_preferences(
        db: Session, user_id: int, data: HabitPreferencesUpdate
    ) -> UserProfile:
        """
        Replace the user's habit preferences dictionary.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated habit-preferences payload.

        Returns:
            The updated ``UserProfile``.

        Raises:
            HTTPException: 404 if no profile exists.
        """
        profile = ProfileService.get_profile(db, user_id)
        profile.habit_preferences = data.habit_preferences
        db.commit()
        db.refresh(profile)
        return profile

    @staticmethod
    def calculate_habit_score(profile: UserProfile) -> Dict[str, Any]:
        """
        Compute the weighted habit score (0–100).

        Delegates to ``app.services.habit_score`` — the single source of truth.
        Weights: wake-up consistency 35%, challenge completion 25%,
        snooze reduction 20%, sleep schedule adherence 20%.
        """
        return _calculate_habit_score(profile)
