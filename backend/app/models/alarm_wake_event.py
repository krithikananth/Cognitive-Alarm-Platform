"""
Wake-up confirmation events — audit trail for each alarm ring cycle.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlarmWakeEvent(Base):
    """Records one wake-up cycle from trigger through verified dismissal."""

    __tablename__ = "alarm_wake_events"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    alarm_id = Column(Integer, ForeignKey("alarms.id"), nullable=False, index=True)

    triggered_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    dismissed_at = Column(DateTime, nullable=True)

    # challenge = solved without exhausting snooze limit
    # snooze_exhausted = dismissed only after max snoozes were used
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
