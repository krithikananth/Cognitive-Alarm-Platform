"""
Alarm and AlarmEvent SQLAlchemy models.
Compatible with both PostgreSQL and SQLite.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, Float, Integer, Text, ForeignKey
)
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Alarm(Base):
    """User alarm configuration."""
    __tablename__ = "alarms"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=True)
    alarm_time = Column(String(10), nullable=False)  # "HH:MM" format
    alarm_type = Column(String(20), nullable=False)  # daily, weekday, weekend, one_time, smart_adaptive
    is_active = Column(Boolean, default=True)
    days_of_week = Column(Text, default="[]")  # JSON string: [0,1,2,3,4,5,6]
    challenge_type = Column(String(50), nullable=True)  # math, logic, memory, word, pattern, riddle, quiz
    challenge_difficulty = Column(String(20), default="medium")
    snooze_limit = Column(Integer, default=3)
    snooze_interval_minutes = Column(Integer, default=5)
    sound = Column(String(100), default="default")
    vibration = Column(Boolean, default=True)
    smart_wakeup_window_minutes = Column(Integer, default=30)
    one_time_date = Column(String(10), nullable=True)  # "YYYY-MM-DD" for one_time alarms
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="alarms")
    events = relationship("AlarmEvent", back_populates="alarm", cascade="all, delete-orphan")


class AlarmEvent(Base):
    """Individual alarm trigger events / history."""
    __tablename__ = "alarm_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    alarm_id = Column(String(36), ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    dismissed_at = Column(DateTime, nullable=True)
    snooze_count = Column(Integer, default=0)
    challenge_completed = Column(Boolean, default=False)
    challenge_id = Column(String(100), nullable=True)  # MongoDB ObjectId reference
    wake_up_verified = Column(Boolean, default=False)
    response_time_seconds = Column(Float, nullable=True)
    status = Column(String(20), default="triggered")  # triggered, snoozed, dismissed, missed
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    alarm = relationship("Alarm", back_populates="events")
    user = relationship("User", back_populates="alarm_events")
