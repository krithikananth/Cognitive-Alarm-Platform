"""
HabitScore SQLAlchemy model — weighted scoring model.
Compatible with both PostgreSQL and SQLite.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, Integer, DateTime, UniqueConstraint, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class HabitScore(Base):
    """
    Daily habit score calculated using the weighted model:
      Overall = WakeUp Consistency (35%) + Challenge Completion (25%)
              + Snooze Reduction (20%) + Sleep Adherence (20%)
    """
    __tablename__ = "habit_scores"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date = Column(String(10), nullable=False)  # "YYYY-MM-DD"
    wakeup_consistency_score = Column(Float, default=0.0)
    challenge_completion_score = Column(Float, default=0.0)
    snooze_reduction_score = Column(Float, default=0.0)
    sleep_adherence_score = Column(Float, default=0.0)
    overall_habit_score = Column(Float, default=0.0)
    streak_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_user_date_score"),
    )

    user = relationship("User", back_populates="habit_scores",
                        foreign_keys=[user_id],
                        primaryjoin="HabitScore.user_id == User.id")

    def calculate_overall(self):
        self.overall_habit_score = (
            self.wakeup_consistency_score * 0.35
            + self.challenge_completion_score * 0.25
            + self.snooze_reduction_score * 0.20
            + self.sleep_adherence_score * 0.20
        )
        return self.overall_habit_score
