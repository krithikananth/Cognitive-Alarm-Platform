"""
Measured recommendation relevance.

Relevance here is what users reported, not what the engine asserted::

    relevance_rate = helpful / (helpful + not_helpful) * 100

Dismissals are recorded but kept out of that ratio: "not now" is a weaker
signal than "this advice was wrong for me". The engine's own ``confidence`` is
stored alongside each verdict so the two can be compared — a large
``confidence_gap`` means the hard-coded confidence values are miscalibrated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.recommendation_feedback import (
    RATING_DISMISSED,
    RATING_HELPFUL,
    RATING_NOT_HELPFUL,
    VERDICT_RATINGS,
    RecommendationFeedback,
)
from app.schemas.recommendation import RecommendationRating, RecommendationResponse

#: Explicit verdicts required before a relevance rate is reported.
MIN_RELEVANCE_RESPONSES = 3


def _percentage(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def _bucket(rows: Sequence[RecommendationFeedback]) -> Dict[str, Any]:
    helpful = sum(1 for r in rows if r.rating == RATING_HELPFUL)
    not_helpful = sum(1 for r in rows if r.rating == RATING_NOT_HELPFUL)
    dismissed = sum(1 for r in rows if r.rating == RATING_DISMISSED)
    rated = helpful + not_helpful

    confidences = [
        float(r.stated_confidence)
        for r in rows
        if r.rating in VERDICT_RATINGS and r.stated_confidence is not None
    ]
    avg_confidence = (
        round(sum(confidences) / len(confidences) * 100, 1) if confidences else None
    )
    relevance_rate = _percentage(helpful, rated)

    return {
        "responses": len(rows),
        "rated": rated,
        "helpful": helpful,
        "not_helpful": not_helpful,
        "dismissed": dismissed,
        "relevance_rate": relevance_rate,
        "avg_stated_confidence": avg_confidence,
        # Positive = users found the advice more useful than the engine claimed.
        "confidence_gap": (
            round(relevance_rate - avg_confidence, 1)
            if avg_confidence is not None and rated
            else None
        ),
    }


class RecommendationRelevanceService:
    """Record user verdicts and turn them into a relevance measurement."""

    @staticmethod
    def record(
        db: Session,
        *,
        user_id: int,
        recommendation_id: str,
        rating: str,
        category: str,
        priority: str,
        stated_confidence: Optional[float] = None,
        commit: bool = True,
    ) -> RecommendationFeedback:
        """Upsert this user's verdict on one recommendation."""
        row = (
            db.query(RecommendationFeedback)
            .filter(
                RecommendationFeedback.user_id == user_id,
                RecommendationFeedback.recommendation_id == recommendation_id,
            )
            .first()
        )
        if row is None:
            row = RecommendationFeedback(
                user_id=user_id, recommendation_id=recommendation_id
            )
            db.add(row)

        row.rating = rating
        row.category = category
        row.priority = priority
        row.stated_confidence = stated_confidence
        db.flush()
        if commit:
            db.commit()
            db.refresh(row)
        return row

    @staticmethod
    def clear(
        db: Session, *, user_id: int, recommendation_id: str, commit: bool = True
    ) -> bool:
        """Remove a verdict. Returns whether anything was stored."""
        deleted = (
            db.query(RecommendationFeedback)
            .filter(
                RecommendationFeedback.user_id == user_id,
                RecommendationFeedback.recommendation_id == recommendation_id,
            )
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()
        return bool(deleted)

    @staticmethod
    def ratings_for(db: Session, user_id: int) -> Dict[str, str]:
        """Map of recommendation id -> this user's current rating."""
        return {
            row.recommendation_id: row.rating
            for row in db.query(RecommendationFeedback).filter(
                RecommendationFeedback.user_id == user_id
            )
        }

    @staticmethod
    def rating_of(
        ratings: Dict[str, str], recommendation_id: str
    ) -> Optional[RecommendationRating]:
        """Stored rating as the schema enum. Assignment is not validated by
        pydantic, so an unknown value must be dropped rather than stored raw."""
        raw = ratings.get(recommendation_id)
        if raw is None:
            return None
        try:
            return RecommendationRating(raw)
        except ValueError:
            return None

    @classmethod
    def annotate(
        cls, response: RecommendationResponse, ratings: Dict[str, str]
    ) -> RecommendationResponse:
        """Attach each item's stored verdict without reordering the feed.

        Ranking deliberately stays untouched — this only tells the UI what the
        user already said about each card.
        """
        if not ratings:
            return response
        for item in response.recommendations:
            item.feedback = cls.rating_of(ratings, item.id)
        for items in (response.by_category or {}).values():
            for item in items:
                item.feedback = cls.rating_of(ratings, item.id)
        return response

    @classmethod
    def compute_relevance(
        cls,
        db: Session,
        user_id: int,
        *,
        days: Optional[int] = None,
        window_end: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Relevance measured from this user's verdicts.

        ``days=None`` reports over all recorded feedback.
        """
        query = db.query(RecommendationFeedback).filter(
            RecommendationFeedback.user_id == user_id
        )
        if days is not None:
            now = window_end or datetime.now(timezone.utc)
            query = query.filter(
                RecommendationFeedback.updated_at
                >= _naive_utc(now - timedelta(days=max(1, int(days))))
            )

        rows: List[RecommendationFeedback] = query.all()
        report = _bucket(rows)

        if not rows:
            status = "no_data"
        elif report["rated"] < MIN_RELEVANCE_RESPONSES:
            status = "insufficient_data"
        else:
            status = "ok"

        by_category: Dict[str, Any] = {}
        for row in rows:
            by_category.setdefault(row.category or "unknown", []).append(row)
        by_priority: Dict[str, Any] = {}
        for row in rows:
            by_priority.setdefault(row.priority or "unknown", []).append(row)

        moments = [r.updated_at for r in rows if r.updated_at is not None]
        report.update(
            {
                "days": days,
                "status": status,
                "min_responses": MIN_RELEVANCE_RESPONSES,
                "by_category": {k: _bucket(v) for k, v in by_category.items()},
                "by_priority": {k: _bucket(v) for k, v in by_priority.items()},
                "last_feedback_at": (
                    max(moments).replace(tzinfo=timezone.utc).isoformat()
                    if moments
                    else None
                ),
            }
        )
        return report
