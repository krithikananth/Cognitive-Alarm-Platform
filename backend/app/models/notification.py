"""
Notification and Recommendation SQLAlchemy models.
Compatible with both PostgreSQL and SQLite.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), nullable=True)
    is_read = Column(Boolean, default=False)
    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notifications",
                        foreign_keys=[user_id],
                        primaryjoin="Notification.user_id == User.id")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), nullable=True)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    priority = Column(Integer, default=5)
    is_dismissed = Column(Boolean, default=False)
    generated_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="recommendations",
                        foreign_keys=[user_id],
                        primaryjoin="Recommendation.user_id == User.id")
