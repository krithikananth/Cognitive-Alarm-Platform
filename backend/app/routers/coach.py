"""
Wellness Coach API endpoints.

Provides coach-specific operations for monitoring users, viewing
habit scores, and providing recommendations. Requires wellness_coach or admin role.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User, UserProfile
from app.models.alarm import Alarm, AlarmEvent
from app.models.habit import HabitScore
from app.schemas.user_schema import UserResponse, ProfileResponse
from app.middleware.auth_middleware import require_role


router = APIRouter(prefix="/coach", tags=["Wellness Coach"])


@router.get(
    "/users",
    summary="List assigned users (Coach/Admin)",
)
async def list_coached_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role(["wellness_coach", "admin"])),
    db: AsyncSession = Depends(get_db),
):
    """List all users visible to the wellness coach with their latest habit scores."""
    query = select(User).where(User.role == "user", User.is_active == True)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    users_result = await db.execute(
        query.order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    users = users_result.scalars().all()

    user_data = []
    for u in users:
        # Get latest habit score
        score_result = await db.execute(
            select(HabitScore).where(HabitScore.user_id == u.id)
            .order_by(HabitScore.date.desc()).limit(1)
        )
        score = score_result.scalar_one_or_none()

        user_data.append({
            "user": UserResponse.model_validate(u),
            "latest_habit_score": score.overall_habit_score if score else 0,
            "current_streak": score.streak_days if score else 0,
        })

    return {
        "users": user_data,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get(
    "/users/{user_id}/progress",
    summary="View user progress (Coach/Admin)",
)
async def view_user_progress(
    user_id: str,
    current_user: User = Depends(require_role(["wellness_coach", "admin"])),
    db: AsyncSession = Depends(get_db),
):
    """View detailed progress for a specific user including habit scores over time."""
    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get recent habit scores (last 30 days)
    scores_result = await db.execute(
        select(HabitScore).where(HabitScore.user_id == user_id)
        .order_by(HabitScore.date.desc()).limit(30)
    )
    scores = scores_result.scalars().all()

    # Get alarm stats
    alarm_count = (await db.execute(
        select(func.count(Alarm.id)).where(Alarm.user_id == user_id)
    )).scalar() or 0

    event_count = (await db.execute(
        select(func.count(AlarmEvent.id)).where(AlarmEvent.user_id == user_id)
    )).scalar() or 0

    success_count = (await db.execute(
        select(func.count(AlarmEvent.id)).where(
            AlarmEvent.user_id == user_id,
            AlarmEvent.status == "dismissed",
            AlarmEvent.challenge_completed == True,
        )
    )).scalar() or 0

    return {
        "user": UserResponse.model_validate(user),
        "total_alarms": alarm_count,
        "total_events": event_count,
        "successful_wakeups": success_count,
        "success_rate": round(success_count / event_count * 100, 1) if event_count > 0 else 0,
        "habit_scores": [
            {
                "date": s.date,
                "overall": s.overall_habit_score,
                "wakeup_consistency": s.wakeup_consistency_score,
                "challenge_completion": s.challenge_completion_score,
                "snooze_reduction": s.snooze_reduction_score,
                "sleep_adherence": s.sleep_adherence_score,
                "streak": s.streak_days,
            }
            for s in scores
        ],
    }
