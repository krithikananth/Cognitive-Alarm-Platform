"""
Challenges served at a ringing alarm, and how each one ended.

``alarm_challenge_logs`` only records *submitted* answers, so a challenge the
user never answered leaves no trace anywhere. This table records the other half
of the lifecycle — the moment a challenge is put in front of the user — which
is what makes a completion rate (finished in time / served) measurable at all.

Accuracy keeps using ``alarm_challenge_logs`` untouched; this table is additive.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from app.db.base import Base

#: Served, not yet answered and still inside its time limit.
OUTCOME_PENDING = "pending"
#: Answered within the time limit — correct or not.
OUTCOME_COMPLETED = "completed"
#: Answered after the limit, or the limit expired with no answer.
OUTCOME_TIMED_OUT = "timed_out"
#: Left unanswered while still in time (new challenge requested, cycle ended).
OUTCOME_ABANDONED = "abandoned"

RESOLVED_OUTCOMES = (OUTCOME_COMPLETED, OUTCOME_TIMED_OUT, OUTCOME_ABANDONED)


class ChallengeDelivery(Base):
    """One cognitive challenge served to a user for a specific alarm.

    Attributes:
        outcome: One of ``pending`` / ``completed`` / ``timed_out`` /
            ``abandoned``. Rows stay ``pending`` until the user answers or the
            wake cycle moves on; a stale ``pending`` row past its deadline is
            read as a timeout without being rewritten.
        is_correct: Only set for a ``completed`` delivery; ``None`` otherwise,
            so an unanswered challenge is never mistaken for a wrong answer.
    """

    __tablename__ = "challenge_deliveries"
    __table_args__ = (
        Index("ix_challenge_deliveries_user_issued", "user_id", "issued_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    alarm_id = Column(
        Integer, ForeignKey("alarms.id"), nullable=False, index=True
    )
    challenge_type = Column(String(50), nullable=False)
    difficulty = Column(String(50), nullable=False, default="medium")
    challenge_prompt = Column(Text, nullable=False, default="")
    time_limit_seconds = Column(Integer, nullable=False, default=30)
    issued_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    resolved_at = Column(DateTime, nullable=True)
    outcome = Column(String(20), nullable=False, default=OUTCOME_PENDING)
    is_correct = Column(Boolean, nullable=True)
    time_taken_seconds = Column(Integer, nullable=True)
