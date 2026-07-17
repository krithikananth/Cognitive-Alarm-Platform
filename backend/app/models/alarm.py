"""
Alarm ORM model.

Defines the ``alarms`` table with scheduling parameters, cognitive-challenge
configuration, and usage statistics.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlarmType(str, enum.Enum):
    """Supported alarm recurrence patterns."""

    DAILY = "daily"
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    ONE_TIME = "one_time"
    SMART_ADAPTIVE = "smart_adaptive"


class ChallengeType(str, enum.Enum):
    """Types of cognitive challenges that can be assigned to an alarm."""

    MATH = "math"
    LOGIC = "logic"
    MEMORY = "memory"
    WORD_GAME = "word_game"
    WORD = "word"  # frontend alias for WORD_GAME
    PATTERN = "pattern"
    RIDDLE = "riddle"
    QUIZ = "quiz"
    RANDOM = "random"


class Alarm(Base):
    """
    SQLAlchemy model representing a scheduled alarm.

    Attributes:
        id: Auto-incrementing primary key.
        user_id: Foreign key to the owning user.
        title: Short human-readable title for the alarm.
        description: Optional extended description.
        alarm_time: Time of day the alarm should fire.
        alarm_type: Recurrence pattern (daily, weekday, etc.).
        days_of_week: JSON list of integers 0-6 (Mon-Sun).
        is_active: Whether the alarm is currently armed.
        snooze_limit: Maximum number of snoozes allowed.
        snooze_interval_minutes: Duration of each snooze in minutes.
        challenge_type: Type of cognitive challenge presented.
        challenge_count: Number of challenges required to dismiss.
        challenge_difficulty: Baseline difficulty for this alarm's puzzles.
        volume: Alarm volume level (0-100).
        vibrate: Whether haptic feedback is enabled.
        label: Optional user-defined label / tag.
        next_trigger_at: Computed datetime of the next firing.
        last_triggered_at: Datetime of the most recent firing.
        total_dismissals: Lifetime count of dismissals.
        total_snoozes: Snooze count for the current wake cycle
            (reset to 0 on verified dismiss; rolled into profile.total_snoozes).
        created_at: Timestamp of record creation (UTC).
        updated_at: Timestamp of last update (UTC).
        user: Back-reference to the parent ``User`` model.
    """

    __tablename__ = "alarms"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), default="Alarm", nullable=False)
    description = Column(Text, nullable=True)
    alarm_time = Column(Time, nullable=False)
    alarm_type = Column(
        Enum(AlarmType), default=AlarmType.DAILY, nullable=False
    )
    days_of_week = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    snooze_limit = Column(Integer, default=3, nullable=False)
    snooze_interval_minutes = Column(Integer, default=5, nullable=False)
    challenge_type = Column(
        Enum(ChallengeType), default=ChallengeType.RANDOM, nullable=False
    )
    challenge_count = Column(Integer, default=1, nullable=False)
    challenge_difficulty = Column(String(50), default="medium", nullable=False)
    volume = Column(Integer, default=80, nullable=False)
    vibrate = Column(Boolean, default=True, nullable=False)
    label = Column(String(255), nullable=True)
    next_trigger_at = Column(DateTime, nullable=True)
    last_triggered_at = Column(DateTime, nullable=True)
    total_dismissals = Column(Integer, default=0, nullable=False)
    total_snoozes = Column(Integer, default=0, nullable=False)
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
    user = relationship("User", back_populates="alarms")
    challenge_logs = relationship("AlarmChallengeLog", back_populates="alarm", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return (
            f"<Alarm(id={self.id}, title='{self.title}', "
            f"time={self.alarm_time}, active={self.is_active})>"
        )


class AlarmChallengeLog(Base):
    """
    SQLAlchemy model representing a specific challenge attempt event.

    Every verify attempt (correct or incorrect) must land here with normalized
    ``challenge_type`` / ``difficulty`` so adaptive difficulty, habit scoring,
    and recommendations can query clean history.

    Attributes:
        id: Auto-incrementing primary key.
        alarm_id: Foreign key to the parent Alarm.
        user_id: Foreign key to the User (for easy analytics grouping).
        challenge_type: Normalized puzzle type (e.g. math, word_game).
        difficulty: Effective difficulty for this attempt (never null).
        challenge_prompt: The prompt shown to the user.
        is_correct: Whether the attempt was correct (and not timed out).
        time_taken_seconds: How long the attempt took (>= 0).
        failed_attempts: Wrong tries before this attempt (>= 0).
        points_earned: Score awarded for this attempt (>= 0).
        created_at: When the attempt was recorded (UTC).
    """

    __tablename__ = "alarm_challenge_logs"
    __table_args__ = (
        Index("ix_alarm_challenge_logs_user_created", "user_id", "created_at"),
        Index("ix_alarm_challenge_logs_alarm_created", "alarm_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    alarm_id = Column(
        Integer, ForeignKey("alarms.id"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    challenge_type = Column(String(50), nullable=False)
    difficulty = Column(String(50), nullable=False, default="medium")
    challenge_prompt = Column(Text, nullable=False, default="")
    is_correct = Column(Boolean, nullable=False, default=False)
    time_taken_seconds = Column(Integer, nullable=False, default=0)
    failed_attempts = Column(Integer, nullable=False, default=0)
    points_earned = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    alarm = relationship("Alarm", back_populates="challenge_logs")

