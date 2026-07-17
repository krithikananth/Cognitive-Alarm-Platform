"""
Per-snooze audit events — one row each time a user snoozes an alarm.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import relationship

from app.db.base import Base


class AlarmSnoozeEvent(Base):
    """Records a single snooze action within an alarm wake cycle."""

    __tablename__ = "alarm_snooze_events"
    __table_args__ = (
        Index("ix_alarm_snooze_events_user_created", "user_id", "created_at"),
        Index("ix_alarm_snooze_events_alarm_created", "alarm_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    alarm_id = Column(
        Integer, ForeignKey("alarms.id"), nullable=False, index=True
    )

    # 1-based snooze ordinal within the current wake cycle after this action
    snooze_number = Column(Integer, nullable=False, default=1)
    snooze_limit_at_event = Column(Integer, nullable=False, default=0)
    next_trigger_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    alarm = relationship("Alarm", backref="snooze_events")
