"""
Recommendation Engine API endpoints.

Exposes personalized sleep, wake-habit, productivity, and challenge coaching.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.recommendation import (
    CategoryRecommendationResponse,
    RecommendationCategory,
    RecommendationResponse,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


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
    return RecommendationService.generate_recommendations(
        current_user,
        db,
        categories=category,
        limit=limit,
    )


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
    return RecommendationService.generate_daily_digest(current_user, db)


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
    return CategoryRecommendationResponse(
        category=RecommendationCategory.SLEEP,
        generated_at=full.generated_at,
        summary=full.summary,
        insights=[i for i in full.insights if "Sleep" in i or "sleep" in i or "lights-out" in i],
        recommendations=full.recommendations,
        daily_plan=full.daily_plan,
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
    return CategoryRecommendationResponse(
        category=RecommendationCategory.WAKE,
        generated_at=full.generated_at,
        summary=full.summary,
        insights=full.insights,
        recommendations=full.recommendations,
        daily_plan=full.daily_plan,
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
    return CategoryRecommendationResponse(
        category=RecommendationCategory.PRODUCTIVITY,
        generated_at=full.generated_at,
        summary=full.summary,
        insights=[i for i in full.insights if "goal" in i.lower()],
        recommendations=full.recommendations,
        daily_plan=full.daily_plan,
    )
