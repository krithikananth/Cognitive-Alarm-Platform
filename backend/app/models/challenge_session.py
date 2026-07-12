"""
Persisted challenge sessions for reliable verify across process restarts.

Tracks both the active puzzle and wake-up verification progress
(consecutive correct answers / multi-step completion).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

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

    # ── Active puzzle ──
    answer = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False, default="")
    challenge_type = Column(String(50), nullable=False, default="math")
    difficulty = Column(String(50), nullable=False, default="medium")
    time_limit_seconds = Column(Integer, nullable=False, default=30)
    issued_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Wake-up verification progress (survives puzzle refresh) ──
    consecutive_correct = Column(Integer, nullable=False, default=0)
    required_correct = Column(Integer, nullable=False, default=1)
    total_failed_attempts = Column(Integer, nullable=False, default=0)
    escalation_level = Column(Integer, nullable=False, default=0)
    verification_token = Column(String(64), nullable=True)
    wake_confirmed = Column(Boolean, nullable=False, default=False)
    session_started_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
