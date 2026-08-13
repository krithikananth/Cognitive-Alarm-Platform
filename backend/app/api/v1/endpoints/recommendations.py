"""
Recommendation Engine API endpoints.

Exposes personalized sleep, wake-habit, productivity, and challenge coaching.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.recommendation import (
    CategoryRecommendationResponse,
    RecommendationCategory,
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationRelevanceResponse,
    RecommendationResponse,
)
from app.services.recommendation_relevance_service import (
    RecommendationRelevanceService,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


def _with_feedback(
    db: Session, user_id: int, response: RecommendationResponse
) -> RecommendationResponse:
    """Attach stored verdicts. Ranking is untouched."""
    return RecommendationRelevanceService.annotate(
        response, RecommendationRelevanceService.ratings_for(db, user_id)
    )


def _category_response(
    db: Session,
    user_id: int,
    category: RecommendationCategory,
    full: RecommendationResponse,
    insights: List[str],
) -> CategoryRecommendationResponse:
    ratings = RecommendationRelevanceService.ratings_for(db, user_id)
    for item in full.recommendations:
        item.feedback = RecommendationRelevanceService.rating_of(ratings, item.id)
    return CategoryRecommendationResponse(
        category=category,
        generated_at=full.generated_at,
        summary=full.summary,
        insights=insights,
        recommendations=full.recommendations,
        daily_plan=full.daily_plan,
    )


@router.get(
    "",
    response_model=RecommendationResponse,
    summary="Get personalized recommendations",
)
def get_recommendations(
    category: Optional[List[RecommendationCategory]] = Query(
        None,
        description="Optional category filter (repeatable): sleep, wake, habit, productivity, challenge",
    ),
    limit: Optional[int] = Query(
        None, ge=1, le=50, description="Optional cap on returned recommendations"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Full recommendation feed covering sleep schedule, wake habits,
    productivity goals, habit score, and challenge performance.
    """
    return _with_feedback(
        db,
        current_user.id,
        RecommendationService.generate_recommendations(
            current_user,
            db,
            categories=category,
            limit=limit,
        ),
    )


@router.get(
    "/relevance",
    response_model=RecommendationRelevanceResponse,
    summary="Measured relevance of past recommendations",
)
def get_recommendation_relevance(
    days: Optional[int] = Query(
        None,
        ge=1,
        le=365,
        description="Limit to feedback given in the last N days (default: all time)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """How useful this user actually found past advice.

    ``relevance_rate = helpful / (helpful + not_helpful)``. ``confidence_gap``
    contrasts that with the confidence the engine asserted on the same cards.
    """
    return RecommendationRelevanceService.compute_relevance(
        db, current_user.id, days=days
    )


@router.put(
    "/{recommendation_id}/feedback",
    response_model=RecommendationFeedbackResponse,
    summary="Rate a recommendation",
)
def set_recommendation_feedback(
    payload: RecommendationFeedbackRequest,
    recommendation_id: str = Path(..., min_length=1, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record this user's verdict on one recommendation.

    The card must exist in the caller's current feed, so category, priority and
    the engine's stated confidence are taken from the engine rather than
    trusted from the client.
    """
    feed = RecommendationService.generate_recommendations(current_user, db)
    item = next(
        (r for r in feed.recommendations if r.id == recommendation_id), None
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That recommendation is not in your current feed.",
        )

    row = RecommendationRelevanceService.record(
        db,
        user_id=current_user.id,
        recommendation_id=item.id,
        rating=payload.rating.value,
        category=item.category.value,
        priority=item.priority.value,
        stated_confidence=item.confidence,
    )
    return RecommendationFeedbackResponse(
        recommendation_id=row.recommendation_id,
        rating=row.rating,
        category=row.category,
        priority=row.priority,
        stated_confidence=row.stated_confidence,
        updated_at=row.updated_at,
    )


@router.delete(
    "/{recommendation_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear a recommendation rating",
)
def clear_recommendation_feedback(
    recommendation_id: str = Path(..., min_length=1, max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove this user's verdict so the card counts as unrated again."""
    RecommendationRelevanceService.clear(
        db, user_id=current_user.id, recommendation_id=recommendation_id
    )
    return None


@router.get(
    "/daily",
    response_model=RecommendationResponse,
    summary="Get daily recommendation digest",
)
def get_daily_digest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top priority coaching items for today plus a suggested daily plan."""
    return _with_feedback(
        db,
        current_user.id,
        RecommendationService.generate_daily_digest(current_user, db),
    )


@router.get(
    "/sleep",
    response_model=CategoryRecommendationResponse,
    summary="Sleep schedule recommendations",
)
def get_sleep_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bedtime, duration, and alarm-alignment sleep advice."""
    full = RecommendationService.generate_recommendations(
        current_user,
        db,
        categories=[RecommendationCategory.SLEEP],
    )
    return _category_response(
        db,
        current_user.id,
        RecommendationCategory.SLEEP,
        full,
        [i for i in full.insights if "Sleep" in i or "sleep" in i or "lights-out" in i],
    )


@router.get(
    "/wake",
    response_model=CategoryRecommendationResponse,
    summary="Wake habit coaching tips",
)
def get_wake_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snooze discipline, consistency, streak, and alertness coaching."""
    full = RecommendationService.generate_recommendations(
        current_user,
        db,
        categories=[RecommendationCategory.WAKE, RecommendationCategory.HABIT],
    )
    return _category_response(
        db, current_user.id, RecommendationCategory.WAKE, full, full.insights
    )


@router.get(
    "/productivity",
    response_model=CategoryRecommendationResponse,
    summary="Productivity suggestions",
)
def get_productivity_recommendations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Goal-aware productivity suggestions tied to wake habits and scores."""
    full = RecommendationService.generate_recommendations(
        current_user,
        db,
        categories=[RecommendationCategory.PRODUCTIVITY],
    )
    return _category_response(
        db,
        current_user.id,
        RecommendationCategory.PRODUCTIVITY,
        full,
        [i for i in full.insights if "goal" in i.lower()],
    )
