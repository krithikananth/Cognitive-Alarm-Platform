"""
Wake-up confirmation events — audit trail for each alarm ring cycle.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlarmWakeEvent(Base):
    """Records one wake-up cycle from trigger through final outcome.

    Successful cycles set ``verified=True``. Final failed wakes
    (abandoned cycles) set ``verified=False`` with
    ``dismiss_method="abandoned"``. Mid-cycle wrong answers and snoozes
    do not create wake events.
    """

    __tablename__ = "alarm_wake_events"
    __table_args__ = (
        # Per-user dashboard windows: user_id = ? AND dismissed_at >= ?
        Index(
            "ix_alarm_wake_events_user_dismissed", "user_id", "dismissed_at"
        ),
        # Habit-score replay: lifetime verified history for one user, in order
        Index(
            "ix_alarm_wake_events_user_verified_dismissed",
            "user_id",
            "verified",
            "dismissed_at",
        ),
        # Platform-wide admin windows, which have no user_id predicate
        Index("ix_alarm_wake_events_dismissed", "dismissed_at"),
        # Covers the admin statistics outcome/activity aggregate end to end, so
        # a year-wide window is an index-only scan instead of 160k row lookups
        Index(
            "ix_alarm_wake_events_dismissed_outcome",
            "dismissed_at",
            "verified",
            "dismiss_method",
            "time_to_dismiss_seconds",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id"), nullable=False, index=True)

    triggered_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    dismissed_at = Column(DateTime, nullable=True)

    # challenge = solved without exhausting snooze limit
    # snooze_exhausted = dismissed only after max snoozes were used
    # abandoned = final failed wake (user gave up / cycle ended in failure)
    # unverified_blocked = dismiss rejected (no verification)
    dismiss_method = Column(String(50), nullable=True)
    challenges_required = Column(Integer, nullable=False, default=1)
    challenges_completed = Column(Integer, nullable=False, default=0)
    consecutive_correct = Column(Integer, nullable=False, default=0)
    failed_attempts = Column(Integer, nullable=False, default=0)
    snooze_count_at_dismiss = Column(Integer, nullable=False, default=0)
    time_to_dismiss_seconds = Column(Integer, nullable=True)
    wakefulness_score = Column(Float, nullable=True)
    wakefulness_level = Column(String(20), nullable=True)
    verified = Column(Boolean, nullable=False, default=False)

    alarm = relationship("Alarm", backref="wake_events")
