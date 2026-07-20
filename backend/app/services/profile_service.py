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
from app.services.challenge_service import (
    ChallengeService,
    _adaptive_streak_threshold,
)
from app.services.habit_score import (
    calculate_habit_score as _calculate_habit_score,
    calculate_habit_score_for_user as _calculate_habit_score_for_user,
    calculate_habit_score_with_events as _calculate_habit_score_with_events,
)


class ProfileService:
    """Service class for user-profile operations."""

    @staticmethod
    def get_or_create_profile(db: Session, user_id: int) -> UserProfile:
        """Return the user's profile, creating a default one when missing."""
        profile = (
            db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        )
        if profile is not None:
            return profile
        profile = UserProfile(
            user_id=user_id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
            consecutive_success_streak=0,
            consecutive_failure_streak=0,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile

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
    def update_adaptive_streaks(
        db: Session,
        profile: Optional[UserProfile],
        *,
        is_correct: bool,
        commit: bool = True,
    ) -> Optional[UserProfile]:
        """
        Update strict consecutive adaptive-difficulty streak counters.

        ``is_correct=True`` means a full wake dismissal (all required steps
        completed). Intermediate correct steps must not call this. A failure
        (wrong/timeout verify) increments the failure streak and resets
        success. Returns the profile, or ``None`` when no profile exists.
        """
        if profile is None:
            return None

        if is_correct:
            profile.consecutive_success_streak = (
                int(profile.consecutive_success_streak or 0) + 1
            )
            profile.consecutive_failure_streak = 0
        else:
            profile.consecutive_failure_streak = (
                int(profile.consecutive_failure_streak or 0) + 1
            )
            profile.consecutive_success_streak = 0

        if commit:
            db.commit()
            db.refresh(profile)
        else:
            db.flush()
        return profile

    @staticmethod
    def reset_adaptive_streaks(
        db: Session,
        profile: Optional[UserProfile],
        *,
        commit: bool = False,
    ) -> None:
        """Clear both adaptive streak counters after a difficulty adjustment."""
        if profile is None:
            return
        profile.consecutive_success_streak = 0
        profile.consecutive_failure_streak = 0
        if commit:
            db.commit()
            db.refresh(profile)
        else:
            db.flush()

    @staticmethod
    def persist_adaptive_difficulty_if_needed(
        db: Session,
        profile: Optional[UserProfile],
        recent_logs: Optional[list] = None,
        alarm_difficulty: Optional[str] = None,
        *,
        commit: bool = True,
    ) -> bool:
        """
        Persist an adaptive-engine difficulty change onto the user profile.

        Uses stored consecutive streak counters (strict N-in-a-row rules) with
        the profile preference as the baseline. When the preference changes,
        streak counters reset and existing alarms are synced the same way as a
        manual preference update.

        ``recent_logs`` is retained for call-site compatibility but unused when
        a profile is present (counters are authoritative).

        Returns True when ``difficulty_preference`` was updated.
        """
        if profile is None:
            return False

        base = ChallengeService.resolve_baseline_difficulty(
            profile, alarm_difficulty
        )
        success_streak = int(profile.consecutive_success_streak or 0)
        failure_streak = int(profile.consecutive_failure_streak or 0)
        adaptation = ChallengeService.adapt_difficulty(
            base,
            recent_logs,
            success_streak=success_streak,
            failure_streak=failure_streak,
        )
        threshold = int(
            adaptation.get("streak_threshold") or _adaptive_streak_threshold()
        )
        threshold_met = (
            success_streak >= threshold or failure_streak >= threshold
        )

        if not adaptation.get("adjustment"):
            # Ceiling/floor: still consume the streak so it cannot re-fire.
            if threshold_met:
                ProfileService.reset_adaptive_streaks(
                    db, profile, commit=commit
                )
            return False

        adapted = ChallengeService.resolve_baseline_difficulty(
            None, adaptation.get("difficulty")
        )
        try:
            new_pref = DifficultyPreference(adapted)
        except ValueError:
            return False

        current = profile.difficulty_preference
        current_val = (
            current.value if hasattr(current, "value") else str(current or "")
        )
        if current_val == new_pref.value:
            if threshold_met:
                ProfileService.reset_adaptive_streaks(
                    db, profile, commit=commit
                )
            return False

        profile.difficulty_preference = new_pref
        ProfileService.sync_alarm_difficulties(
            db, profile.user_id, new_pref, commit=False
        )
        ProfileService.reset_adaptive_streaks(db, profile, commit=False)

        if commit:
            db.commit()
            db.refresh(profile)
        return True

    @staticmethod
    def calculate_habit_score(
        profile: UserProfile,
        db: Optional[Session] = None,
        events: Optional[Any] = None,
        puzzle_stats: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Compute the weighted habit score (0–100).

        Delegates to ``app.services.habit_score`` — the single source of truth.
        When ``db`` or ``events`` is provided, inputs are recalculated from
        verified wake events (falling back to stored counters if none exist).
        Weights: wake-up consistency 35%, challenge completion 25%,
        snooze reduction 20%, sleep schedule adherence 20%.
        Challenge completion uses puzzle-log accuracy when available
        (``db`` path loads lifetime logs; ``events`` path accepts optional
        ``puzzle_stats`` overlay).
        """
        if events is not None:
            return _calculate_habit_score_with_events(
                profile, events, puzzle_stats=puzzle_stats
            )
        if db is not None and getattr(profile, "user_id", None) is not None:
            return _calculate_habit_score_for_user(db, profile.user_id, profile)
        return _calculate_habit_score(profile)
