"""
User verdicts on individual recommendations.

The engine ships a hard-coded ``confidence`` with every recommendation, which
is an assertion, not a measurement. This table stores what the user actually
said about each card, so relevance can be computed from real feedback and the
engine's stated confidence can be checked against it.

One row per (user, recommendation): re-rating updates the existing verdict
rather than stacking duplicates.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base

#: The advice was useful to this user.
RATING_HELPFUL = "helpful"
#: The advice was not useful — an explicit negative verdict.
RATING_NOT_HELPFUL = "not_helpful"
#: Waved away without judging it useful or useless.
RATING_DISMISSED = "dismissed"

RATINGS = (RATING_HELPFUL, RATING_NOT_HELPFUL, RATING_DISMISSED)
#: Only explicit verdicts count toward the relevance rate; a dismissal says
#: "not now", which is a weaker signal than "this advice was wrong for me".
VERDICT_RATINGS = (RATING_HELPFUL, RATING_NOT_HELPFUL)


class RecommendationFeedback(Base):
    """One user's current verdict on one recommendation.

    Attributes:
        stated_confidence: The engine's confidence for this card at the moment
            it was rated, kept so measured relevance can be compared against
            what the engine claimed.
    """

    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "recommendation_id", name="uq_recommendation_feedback_item"
        ),
        Index("ix_recommendation_feedback_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    recommendation_id = Column(String(120), nullable=False)
    category = Column(String(20), nullable=False)
    priority = Column(String(10), nullable=False)
    stated_confidence = Column(Float, nullable=True)
    rating = Column(String(20), nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
