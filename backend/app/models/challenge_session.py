"""
Persisted challenge sessions for reliable verify across process restarts.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.db.base import Base


class ChallengeSession(Base):
    """Server-side challenge session keyed by (user_id, alarm_id)."""

    __tablename__ = "challenge_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "alarm_id", name="uq_challenge_session_user_alarm"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    alarm_id = Column(Integer, nullable=False, index=True)
    answer = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False, default="")
    difficulty = Column(String(50), nullable=False, default="medium")
    time_limit_seconds = Column(Integer, nullable=False, default=30)
    issued_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
