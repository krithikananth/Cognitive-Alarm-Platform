"""
Alarm scheduling API endpoints.

Provides full CRUD for alarms, plus toggle, snooze, dismiss, and upcoming
alarm retrieval for the authenticated user.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.alarm import Alarm, AlarmType, ChallengeType, AlarmChallengeLog
from app.services.challenge_service import ChallengeService
from app.schemas.alarm import (
    AlarmCreate,
    AlarmUpdate,
    AlarmResponse,
    AlarmListResponse,
    AlarmToggle,
)
from app.api.deps import get_current_user

router = APIRouter(prefix="/alarms", tags=["Alarm Scheduling"])


@router.post(
    "/",
    response_model=AlarmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new alarm",
)
def create_alarm(
    alarm_data: AlarmCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new alarm for the authenticated user.

    Automatically calculates the next trigger datetime based on the
    alarm type and configured days of the week.
    """
    alarm = Alarm(
        user_id=current_user.id,
        title=alarm_data.title,
        description=alarm_data.description,
        alarm_time=alarm_data.alarm_time,
        alarm_type=alarm_data.alarm_type,
        days_of_week=alarm_data.days_of_week,
        snooze_limit=alarm_data.snooze_limit,
        snooze_interval_minutes=alarm_data.snooze_interval_minutes,
        challenge_type=alarm_data.challenge_type,
        challenge_count=alarm_data.challenge_count,
        volume=alarm_data.volume,
        vibrate=alarm_data.vibrate,
        label=alarm_data.label,
        is_active=True,
    )

    # Calculate next trigger time
    alarm.next_trigger_at = _calculate_next_trigger(alarm)

    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    return alarm


@router.get(
    "/",
    response_model=AlarmListResponse,
    summary="List user's alarms",
)
def list_alarms(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all alarms for the authenticated user with pagination and filtering."""
    query = db.query(Alarm).filter(Alarm.user_id == current_user.id)

    if is_active is not None:
        query = query.filter(Alarm.is_active == is_active)

    total = query.count()
    alarms = (
        query.order_by(Alarm.alarm_time)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return AlarmListResponse(
        alarms=alarms,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/upcoming",
    response_model=list[AlarmResponse],
    summary="Get upcoming alarms",
)
def get_upcoming_alarms(
    hours_ahead: int = Query(24, ge=1, le=168, description="Hours to look ahead"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get upcoming active alarms within the specified time window."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(hours=hours_ahead)

    alarms = (
        db.query(Alarm)
        .filter(
            Alarm.user_id == current_user.id,
            Alarm.is_active == True,
            Alarm.next_trigger_at != None,
            Alarm.next_trigger_at >= now,
            Alarm.next_trigger_at <= cutoff,
        )
        .order_by(Alarm.next_trigger_at)
        .all()
    )
    return alarms


@router.get(
    "/{alarm_id}",
    response_model=AlarmResponse,
    summary="Get alarm by ID",
)
def get_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific alarm by ID. Only the alarm owner can access it."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )
    return alarm


@router.put(
    "/{alarm_id}",
    response_model=AlarmResponse,
    summary="Update alarm",
)
def update_alarm(
    alarm_id: int,
    alarm_data: AlarmUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing alarm's settings."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )

    update_data = alarm_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(alarm, field, value)

    # Recalculate next trigger if time or type changed
    if "alarm_time" in update_data or "alarm_type" in update_data:
        alarm.next_trigger_at = _calculate_next_trigger(alarm)

    db.commit()
    db.refresh(alarm)
    return alarm


@router.delete(
    "/{alarm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete alarm",
)
def delete_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete an alarm."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )
    db.delete(alarm)
    db.commit()
    return None


@router.patch(
    "/{alarm_id}/toggle",
    response_model=AlarmResponse,
    summary="Toggle alarm active state",
)
def toggle_alarm(
    alarm_id: int,
    toggle_data: AlarmToggle,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle an alarm on or off."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )

    alarm.is_active = toggle_data.is_active
    if toggle_data.is_active:
        alarm.next_trigger_at = _calculate_next_trigger(alarm)

    db.commit()
    db.refresh(alarm)
    return alarm


@router.post(
    "/{alarm_id}/snooze",
    response_model=AlarmResponse,
    summary="Snooze alarm",
)
def snooze_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Snooze an alarm. Increments snooze count and postpones trigger time.

    Raises 400 if the maximum snooze limit has been reached.
    """
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )

    if alarm.total_snoozes >= alarm.snooze_limit:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum snooze limit reached. Solve the challenge to dismiss.",
        )

    alarm.total_snoozes += 1
    alarm.next_trigger_at = datetime.now(timezone.utc) + timedelta(
        minutes=alarm.snooze_interval_minutes
    )

    db.commit()
    db.refresh(alarm)
    return alarm


@router.get(
    "/{alarm_id}/challenge",
    summary="Get cognitive challenge for alarm",
)
def get_alarm_challenge(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the challenge for the specified alarm."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )
        
    return ChallengeService.generate_challenge(alarm.challenge_type)


from pydantic import BaseModel
class VerifyAnswerRequest(BaseModel):
    expected_answer: str
    user_answer: str
    time_taken_seconds: int = 0
    failed_attempts: int = 0

@router.post(
    "/{alarm_id}/verify",
    summary="Verify challenge answer",
)
def verify_alarm_challenge(
    alarm_id: int,
    data: VerifyAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify the user's answer to a cognitive challenge."""
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )
        
    is_correct = ChallengeService.verify_answer(data.expected_answer, data.user_answer)
    if not is_correct:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect answer. Try again."
        )
        
    # Log the analytics
    log = AlarmChallengeLog(
        alarm_id=alarm.id,
        user_id=current_user.id,
        challenge_type=alarm.challenge_type.value,
        time_taken_seconds=data.time_taken_seconds,
        failed_attempts=data.failed_attempts
    )
    db.add(log)
        
    # Automatically dismiss alarm on success
    return dismiss_alarm(alarm_id, db, current_user)


@router.post(
    "/{alarm_id}/dismiss",
    response_model=AlarmResponse,
    summary="Dismiss alarm",
)
def dismiss_alarm(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dismiss an alarm after completing the cognitive challenge.

    Records the dismissal event and calculates the next trigger time.
    """
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alarm not found",
        )

    alarm.total_dismissals += 1
    alarm.last_triggered_at = datetime.now(timezone.utc)
    alarm.next_trigger_at = _calculate_next_trigger(alarm)

    # Update user profile stats (performance tracking)
    if current_user.profile:
        current_user.profile.total_alarms_dismissed += 1
        
        # Simple scoring logic: Snoozing too much breaks your streak
        if alarm.total_snoozes == 0:
            current_user.profile.streak_days += 1
            if current_user.profile.streak_days > current_user.profile.best_streak:
                current_user.profile.best_streak = current_user.profile.streak_days
            current_user.profile.wake_up_consistency_score = min(100.0, current_user.profile.wake_up_consistency_score + 5.0)
        elif alarm.total_snoozes >= alarm.snooze_limit:
            current_user.profile.streak_days = 0
            current_user.profile.wake_up_consistency_score = max(0.0, current_user.profile.wake_up_consistency_score - 10.0)
            
        current_user.profile.total_snoozes += alarm.total_snoozes
            
    # Reset alarm snooze counter for the next occurrence
    alarm.total_snoozes = 0

    db.commit()
    db.refresh(alarm)
    return alarm


def _calculate_next_trigger(alarm: Alarm) -> Optional[datetime]:
    """Calculate the next trigger datetime for an alarm.

    Takes into account alarm type and configured days of the week.

    Args:
        alarm: The alarm instance to calculate for.

    Returns:
        Next trigger datetime (UTC) or None for one-time past alarms.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    alarm_dt = datetime.combine(today, alarm.alarm_time, tzinfo=timezone.utc)

    if alarm.alarm_type == AlarmType.ONE_TIME:
        if alarm_dt > now:
            return alarm_dt
        return alarm_dt + timedelta(days=1)

    if alarm.alarm_type == AlarmType.DAILY:
        if alarm_dt > now:
            return alarm_dt
        return alarm_dt + timedelta(days=1)

    if alarm.alarm_type == AlarmType.WEEKDAY:
        # Monday=0 through Friday=4
        for offset in range(7):
            candidate = alarm_dt + timedelta(days=offset)
            if candidate > now and candidate.weekday() < 5:
                return candidate
        return alarm_dt + timedelta(days=1)

    if alarm.alarm_type == AlarmType.WEEKEND:
        # Saturday=5, Sunday=6
        for offset in range(7):
            candidate = alarm_dt + timedelta(days=offset)
            if candidate > now and candidate.weekday() >= 5:
                return candidate
        return alarm_dt + timedelta(days=1)

    if alarm.alarm_type == AlarmType.SMART_ADAPTIVE:
        # Default to next occurrence; adaptive logic in future milestones
        if alarm_dt > now:
            return alarm_dt
        return alarm_dt + timedelta(days=1)

    return alarm_dt + timedelta(days=1)
