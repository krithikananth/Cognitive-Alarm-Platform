"""
Profile service layer.

Handles CRUD and partial updates for ``UserProfile``, as well as
computing the weighted habit score.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.profile import DifficultyPreference, UserProfile
from app.schemas.profile import (
    GoalsUpdate,
    HabitPreferencesUpdate,
    ProfileCreate,
    ProfileUpdate,
    SleepScheduleUpdate,
)


class ProfileService:
    """Service class for user-profile operations."""

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
        Compute a weighted habit score (0–100) from profile statistics.

        Weights:
            - Wake-up consistency   : 35%
            - Streak performance    : 25%
            - Dismissal efficiency  : 25%
            - Snooze discipline     : 15%

        Dismissal efficiency is defined as the ratio of dismissals to
        total interactions (dismissals + snoozes).  Snooze discipline is
        ``1 - snooze_ratio``.

        Args:
            profile: The ``UserProfile`` to evaluate.

        Returns:
            Dictionary with ``habit_score`` (float 0–100) and a ``breakdown``
            dict containing the individual component scores.
        """
        # ── Component 1: Consistency (0–100, stored directly) ────────
        consistency_score: float = min(
            profile.wake_up_consistency_score, 100.0
        )

        # ── Component 2: Streak performance (0–100) ─────────────────
        # Cap at 30-day streak = 100
        streak_score: float = min((profile.streak_days / 30.0) * 100.0, 100.0)

        # ── Component 3: Dismissal efficiency (0–100) ───────────────
        total_interactions = (
            profile.total_alarms_dismissed + profile.total_snoozes
        )
        if total_interactions > 0:
            dismissal_ratio = (
                profile.total_alarms_dismissed / total_interactions
            )
        else:
            dismissal_ratio = 1.0  # no interactions yet → perfect
        dismissal_score: float = dismissal_ratio * 100.0

        # ── Component 4: Snooze discipline (0–100) ──────────────────
        snooze_discipline: float = (1.0 - (1.0 - dismissal_ratio)) * 100.0

        # ── Weighted total ──────────────────────────────────────────
        habit_score: float = (
            consistency_score * 0.35
            + streak_score * 0.25
            + dismissal_score * 0.25
            + snooze_discipline * 0.15
        )
        habit_score = round(min(habit_score, 100.0), 2)

        breakdown = {
            "consistency_score": round(consistency_score, 2),
            "consistency_weight": 0.35,
            "streak_score": round(streak_score, 2),
            "streak_weight": 0.25,
            "dismissal_score": round(dismissal_score, 2),
            "dismissal_weight": 0.25,
            "snooze_discipline_score": round(snooze_discipline, 2),
            "snooze_discipline_weight": 0.15,
        }

        return {"habit_score": habit_score, "breakdown": breakdown}
