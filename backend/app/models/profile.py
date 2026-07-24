"""
UserProfile ORM model.

Stores user preferences related to sleep, productivity, habits, and
cognitive-alarm difficulty.  Maintains running statistics used for
habit-score calculations.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Time,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class DifficultyPreference(str, enum.Enum):
    """Cognitive-challenge difficulty levels available to the user."""

    BEGINNER = "beginner"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class UserProfile(Base):
    """
    SQLAlchemy model representing a user's profile and preferences.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: Foreign key linking to the ``users`` table (one-to-one).
        preferred_wake_time: User's desired wake-up time.
        sleep_duration_hours: Target sleep duration in hours.
        timezone: IANA timezone string (e.g. ``America/New_York``).
        productivity_goals: JSON list of the user's productivity goals.
        difficulty_preference: User-controlled cognitive challenge preference
            (never modified by the adaptive engine).
        adapted_difficulty: Working difficulty used by the adaptive engine
            (±1 around this baseline). Reset to preference on manual change.
        habit_preferences: JSON dict of habit-related preferences.
        wake_up_consistency_score: Rolling consistency metric (0–100).
        total_alarms_dismissed: Lifetime count of dismissed alarms.
        total_snoozes: Lifetime count of snooze events.
        streak_days: Current consecutive calendar-day wake-up streak.
        best_streak: Highest Day Streak ever achieved.
        last_successful_wake_date: Local calendar date of the last verified
            successful wake (used to continue / reset the Day Streak).
        consecutive_success_streak: Success Streak — consecutive successful
            wake completions. +1 on verified dismiss only; resets on final
            wake failure only; never touched by ring/snooze/mid-wrong or by
            the adaptive engine (survives threshold adapts).
        consecutive_failure_streak: Consecutive failed wake completions used
            by adaptive difficulty. +1 only via ``POST /alarms/{id}/fail-wake``
            (final abandoned cycle); resets on verified dismiss; never touched
            by ring/snooze/mid-wrong. Survives adapt watermarks.
        last_adapted_success_streak: Success-streak watermark consumed by the
            last difficulty raise (prevents re-firing until +N more successes).
        last_adapted_failure_streak: Failure-streak watermark consumed by the
            last difficulty drop.
        created_at: Timestamp of record creation (UTC).
        updated_at: Timestamp of last update (UTC).
        user: Back-reference to the parent ``User`` model.
    """

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )
    preferred_wake_time = Column(Time, nullable=True)
    sleep_duration_hours = Column(Float, default=8.0, nullable=False)
    timezone = Column(String(50), default="UTC", nullable=False)
    productivity_goals = Column(JSON, nullable=True)
    difficulty_preference = Column(
        Enum(DifficultyPreference),
        default=DifficultyPreference.MEDIUM,
        nullable=False,
    )
    adapted_difficulty = Column(
        Enum(DifficultyPreference),
        default=DifficultyPreference.MEDIUM,
        nullable=False,
    )
    habit_preferences = Column(JSON, nullable=True)
    wake_up_consistency_score = Column(Float, default=0.0, nullable=False)
    total_alarms_dismissed = Column(Integer, default=0, nullable=False)
    total_snoozes = Column(Integer, default=0, nullable=False)
    streak_days = Column(Integer, default=0, nullable=False)
    best_streak = Column(Integer, default=0, nullable=False)
    last_successful_wake_date = Column(Date, nullable=True)
    consecutive_success_streak = Column(Integer, default=0, nullable=False)
    consecutive_failure_streak = Column(Integer, default=0, nullable=False)
    last_adapted_success_streak = Column(Integer, default=0, nullable=False)
    last_adapted_failure_streak = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────
    user = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return (
            f"<UserProfile(id={self.id}, user_id={self.user_id}, "
            f"difficulty='{self.difficulty_preference}')>"
        )
