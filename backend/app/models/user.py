"""
User and UserProfile SQLAlchemy models.
Compatible with both PostgreSQL and SQLite.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, Float, Text, ForeignKey, Time
)
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    """Core user account table."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)  # nullable for OAuth users
    full_name = Column(String(255), nullable=True)
    role = Column(String(20), default="user", nullable=False)  # user, wellness_coach, admin
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    oauth_provider = Column(String(50), nullable=True)  # google, github
    oauth_id = Column(String(255), nullable=True)
    avatar_url = Column(Text, nullable=True)
    timezone = Column(String(50), default="UTC")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    alarms = relationship("Alarm", back_populates="user", cascade="all, delete-orphan")
    alarm_events = relationship("AlarmEvent", back_populates="user", cascade="all, delete-orphan")
    habit_scores = relationship("HabitScore", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="user", cascade="all, delete-orphan")


class UserProfile(Base):
    """Extended user profile with sleep/habit preferences."""
    __tablename__ = "user_profiles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    preferred_wakeup_time = Column(String(10), nullable=True)  # Store as "HH:MM" string
    sleep_duration_hours = Column(Float, default=8.0)
    difficulty_preference = Column(String(20), default="medium")  # beginner, easy, medium, hard, expert
    productivity_goals = Column(Text, nullable=True)
    habit_preferences = Column(Text, default="{}")  # JSON string
    notification_enabled = Column(Boolean, default=True)
    sound_preference = Column(String(100), default="default")
    preferred_challenge_types = Column(Text, default='["math","logic"]')  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="profile")
