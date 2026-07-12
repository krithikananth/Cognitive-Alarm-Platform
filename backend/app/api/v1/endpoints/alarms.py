"""
Alarm scheduling API endpoints.

Provides full CRUD for alarms, plus toggle, snooze, dismiss, and upcoming
alarm retrieval for the authenticated user.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.models.user import User
from app.models.profile import UserProfile
from app.models.alarm import Alarm, AlarmType, ChallengeType, AlarmChallengeLog
from app.services.challenge_service import ChallengeService, VERIFY_TIME_GRACE_SECONDS
from app.schemas.alarm import (
    AlarmCreate,
    AlarmUpdate,
    AlarmResponse,
    AlarmListResponse,
    AlarmToggle,
)
from app.api.deps import get_current_user


def _resolve_timezone(tz_name: Optional[str]) -> ZoneInfo:
    """Return a ZoneInfo, falling back to UTC on unknown names."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _user_timezone(db: Session, user_id: int) -> str:
    """Load the user's IANA timezone from their profile."""
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    return (profile.timezone if profile and profile.timezone else "UTC") or "UTC"


def _to_utc_naive(dt: datetime) -> datetime:
    """Normalize an aware datetime to UTC naive for SQLite storage."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)

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
    # Map frontend "word" alias to backend enum value
    challenge_type = alarm_data.challenge_type
    if challenge_type == ChallengeType.WORD:
        challenge_type = ChallengeType.WORD_GAME

    title = alarm_data.title
    if alarm_data.label and (not title or title == "Alarm"):
        title = alarm_data.label

    alarm = Alarm(
        user_id=current_user.id,
        title=title,
        description=alarm_data.description,
        alarm_time=alarm_data.alarm_time,
        alarm_type=alarm_data.alarm_type,
        days_of_week=alarm_data.days_of_week,
        snooze_limit=alarm_data.snooze_limit,
        snooze_interval_minutes=alarm_data.snooze_interval_minutes,
        challenge_type=challenge_type,
        challenge_count=alarm_data.challenge_count,
        volume=alarm_data.volume,
        vibrate=alarm_data.vibrate,
        label=alarm_data.label,
        is_active=True,
    )

    user_tz = _user_timezone(db, current_user.id)
    alarm.next_trigger_at = _calculate_next_trigger(
        alarm, user_tz=user_tz, one_time_date=alarm_data.one_time_date
    )

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
    one_time_date = update_data.pop("one_time_date", None)
    if "challenge_type" in update_data and update_data["challenge_type"] == ChallengeType.WORD_GAME:
        pass
    elif "challenge_type" in update_data:
        ct = update_data["challenge_type"]
        if getattr(ct, "value", str(ct)) == "word":
            update_data["challenge_type"] = ChallengeType.WORD_GAME

    for field, value in update_data.items():
        setattr(alarm, field, value)

    # Recalculate next trigger if time or type changed
    if "alarm_time" in update_data or "alarm_type" in update_data or one_time_date is not None:
        user_tz = _user_timezone(db, current_user.id)
        alarm.next_trigger_at = _calculate_next_trigger(
            alarm, user_tz=user_tz, one_time_date=one_time_date
        )

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
        user_tz = _user_timezone(db, current_user.id)
        alarm.next_trigger_at = _calculate_next_trigger(alarm, user_tz=user_tz)

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
    """Fetch a personalized cognitive challenge for the specified alarm.

    The challenge difficulty is determined by the user's profile preference
    (beginner / easy / medium / hard / expert) and automatically adjusted
    based on the current time of day (easier challenges during very early
    morning hours when the user is groggiest).
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

    # ── Read the user's difficulty preference from their profile ──
    difficulty = "medium"  # default fallback
    user_tz_name = "UTC"
    if current_user.profile:
        if current_user.profile.difficulty_preference:
            difficulty = current_user.profile.difficulty_preference.value
        if current_user.profile.timezone:
            user_tz_name = current_user.profile.timezone

    # ── Get the current hour in the user's local timezone ──
    current_hour = datetime.now(_resolve_timezone(user_tz_name)).hour

    challenge = ChallengeService.generate_challenge(
        challenge_type=alarm.challenge_type,
        difficulty=difficulty,
        current_hour=current_hour,
    )
    # Persist answer server-side — clients must not be trusted for verification
    ChallengeService.store_challenge_session(
        current_user.id, alarm.id, challenge, db
    )
    return challenge


from pydantic import BaseModel


class VerifyAnswerRequest(BaseModel):
    """Payload for verifying a challenge answer."""

    user_answer: str
    # Deprecated: ignored when a server session exists. Kept for older clients.
    expected_answer: Optional[str] = None
    time_taken_seconds: int = 0
    failed_attempts: int = 0
    challenge_prompt: str = ""
    challenge_difficulty: str = "medium"
    challenge_step: int = 1          # which step in a multi-step sequence
    challenge_total_steps: int = 1   # total steps required


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
    """Verify the user's answer to a cognitive challenge.

    Features:
        - Verifies against the **server-stored** challenge session (not the
          client-supplied expected answer).
        - Logs **every** attempt (correct and incorrect) for analytics.
        - Enforces **time limits** using server-side issuance time.
        - Supports **multi-step challenges** — only dismisses the alarm
          when the user has completed all required steps.
        - Returns progress info so the frontend can show "Step 2 of 3".
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

    session = ChallengeService.get_challenge_session(
        current_user.id, alarm_id, db
    )

    if session:
        expected = session["answer"]
        difficulty = session["difficulty"]
        prompt = session["prompt"] or data.challenge_prompt
        max_time = int(session["time_limit_seconds"])
        issued_at = session["issued_at"]
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - issued_at).total_seconds()
        # Use the larger of server elapsed and client-reported time:
        # - server elapsed blocks under-reporting (spoofing a fast solve)
        # - client time honors device timer expiry (e.g. time_taken_seconds: 999)
        client_time = max(0, int(data.time_taken_seconds or 0))
        time_taken = max(int(round(elapsed)), client_time)
        timed_out = time_taken > (max_time + VERIFY_TIME_GRACE_SECONDS)
    else:
        # Legacy fallback for clients that still send expected_answer
        if not data.expected_answer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active challenge. Request a new one first.",
            )
        expected = data.expected_answer
        difficulty = data.challenge_difficulty or "medium"
        prompt = data.challenge_prompt
        time_limits = {
            "beginner": 60, "easy": 45, "medium": 30, "hard": 20, "expert": 15,
        }
        max_time = time_limits.get(difficulty.lower(), 30)
        time_taken = data.time_taken_seconds
        timed_out = time_taken > (max_time + VERIFY_TIME_GRACE_SECONDS)

    # ── Check answer correctness ──
    is_correct = ChallengeService.verify_answer(expected, data.user_answer)

    # ── Compute score ──
    actually_correct = is_correct and not timed_out
    score = ChallengeService.calculate_score(
        challenge_type=alarm.challenge_type.value,
        difficulty=difficulty,
        time_taken_seconds=time_taken,
        is_correct=actually_correct,
    )

    # ── Log EVERY attempt (correct or incorrect) ──
    log = AlarmChallengeLog(
        alarm_id=alarm.id,
        user_id=current_user.id,
        challenge_type=alarm.challenge_type.value,
        difficulty=difficulty,
        challenge_prompt=prompt,
        is_correct=actually_correct,
        time_taken_seconds=time_taken,
        failed_attempts=data.failed_attempts,
        points_earned=score["total_points"],
    )
    db.add(log)
    db.commit()

    # ── Handle timeout ──
    if timed_out:
        # Invalidate the expired session so the client must fetch a fresh one
        ChallengeService.clear_challenge_session(current_user.id, alarm_id, db)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Time's up! You took {time_taken}s but the "
                   f"limit is {max_time}s for {difficulty} difficulty.",
        )

    # ── Handle wrong answer ──
    if not is_correct:
        # Clear so the next GET /challenge issues a fresh puzzle
        ChallengeService.clear_challenge_session(current_user.id, alarm_id, db)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": "Incorrect answer. Try again.",
                "score": score,
            },
        )

    # Correct — consume this session (next step / retry will issue a new one)
    ChallengeService.clear_challenge_session(current_user.id, alarm_id, db)

    # ── Multi-step: check if more challenges are needed ──
    required_steps = alarm.challenge_count
    current_step = data.challenge_step

    if current_step < required_steps:
        return {
            "status": "step_complete",
            "message": f"Correct! Step {current_step} of {required_steps} complete.",
            "current_step": current_step,
            "total_steps": required_steps,
            "next_step": current_step + 1,
            "is_dismissed": False,
            "score": score,
        }

    # ── All steps completed — dismiss the alarm ──
    result = _dismiss_alarm_internal(alarm, current_user, db)
    return {
        "status": "dismissed",
        "message": f"All {required_steps} challenges solved! Alarm dismissed.",
        "current_step": current_step,
        "total_steps": required_steps,
        "is_dismissed": True,
        "alarm": result,
        "score": score,
    }


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
    return _dismiss_alarm_internal(alarm, current_user, db)


def _dismiss_alarm_internal(alarm: Alarm, current_user: User, db: Session):
    """Shared dismissal logic used by both verify (auto-dismiss) and manual dismiss."""
    alarm.total_dismissals += 1
    alarm.last_triggered_at = datetime.now(timezone.utc)
    user_tz = _user_timezone(db, current_user.id)
    if alarm.alarm_type == AlarmType.ONE_TIME:
        alarm.is_active = False
        alarm.next_trigger_at = None
    else:
        alarm.next_trigger_at = _calculate_next_trigger(alarm, user_tz=user_tz)

    # Update user profile stats (performance tracking)
    if current_user.profile:
        current_user.profile.total_alarms_dismissed += 1

        # Simple scoring logic: Snoozing too much breaks your streak
        if alarm.total_snoozes == 0:
            current_user.profile.streak_days += 1
            if current_user.profile.streak_days > current_user.profile.best_streak:
                current_user.profile.best_streak = current_user.profile.streak_days
            current_user.profile.wake_up_consistency_score = min(
                100.0, current_user.profile.wake_up_consistency_score + 5.0
            )
        elif alarm.total_snoozes >= alarm.snooze_limit:
            current_user.profile.streak_days = 0
            current_user.profile.wake_up_consistency_score = max(
                0.0, current_user.profile.wake_up_consistency_score - 10.0
            )

        current_user.profile.total_snoozes += alarm.total_snoozes

    # Reset alarm snooze counter for the next occurrence
    alarm.total_snoozes = 0

    db.commit()
    db.refresh(alarm)
    return alarm


# ─────────────────────────────────────────────────────────────
# Challenge History & Analytics Endpoints
# ─────────────────────────────────────────────────────────────

@router.get(
    "/{alarm_id}/challenge/history",
    summary="Get challenge attempt history for an alarm",
)
def get_challenge_history(
    alarm_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve paginated challenge attempt history for a specific alarm.

    Includes every attempt (correct and incorrect) with time taken,
    difficulty, and the question that was asked.
    """
    # Verify ownership
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found"
        )

    query = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.alarm_id == alarm_id)
    )
    total = query.count()
    logs = (
        query.order_by(AlarmChallengeLog.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "alarm_id": alarm_id,
        "total": total,
        "page": page,
        "per_page": per_page,
        "history": [
            {
                "id": log.id,
                "challenge_type": log.challenge_type,
                "difficulty": log.difficulty,
                "challenge_prompt": log.challenge_prompt,
                "is_correct": log.is_correct,
                "time_taken_seconds": log.time_taken_seconds,
                "failed_attempts": log.failed_attempts,
                "points_earned": log.points_earned,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get(
    "/challenge/stats",
    summary="Get challenge performance statistics",
)
def get_challenge_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compute aggregate challenge performance stats for the current user.

    Returns:
        - Total attempts, correct count, accuracy percentage.
        - Average response time overall and per challenge type.
        - Breakdown by difficulty level.
    """
    from sqlalchemy import func

    logs = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .all()
    )

    if not logs:
        return {
            "total_attempts": 0,
            "correct_answers": 0,
            "accuracy_percentage": 0.0,
            "avg_response_time": 0.0,
            "by_type": {},
            "by_difficulty": {},
        }

    total = len(logs)
    correct = sum(1 for l in logs if l.is_correct)
    avg_time = sum(l.time_taken_seconds for l in logs) / total

    # Breakdown by challenge type
    by_type = {}
    for log in logs:
        ct = log.challenge_type or "unknown"
        if ct not in by_type:
            by_type[ct] = {"total": 0, "correct": 0, "total_time": 0}
        by_type[ct]["total"] += 1
        by_type[ct]["correct"] += 1 if log.is_correct else 0
        by_type[ct]["total_time"] += log.time_taken_seconds

    for ct, stats in by_type.items():
        stats["accuracy"] = round(
            (stats["correct"] / stats["total"]) * 100, 1
        ) if stats["total"] > 0 else 0.0
        stats["avg_time"] = round(
            stats["total_time"] / stats["total"], 1
        ) if stats["total"] > 0 else 0.0
        del stats["total_time"]

    # Breakdown by difficulty
    by_difficulty = {}
    for log in logs:
        diff = log.difficulty or "unknown"
        if diff not in by_difficulty:
            by_difficulty[diff] = {"total": 0, "correct": 0, "total_time": 0}
        by_difficulty[diff]["total"] += 1
        by_difficulty[diff]["correct"] += 1 if log.is_correct else 0
        by_difficulty[diff]["total_time"] += log.time_taken_seconds

    for diff, stats in by_difficulty.items():
        stats["accuracy"] = round(
            (stats["correct"] / stats["total"]) * 100, 1
        ) if stats["total"] > 0 else 0.0
        stats["avg_time"] = round(
            stats["total_time"] / stats["total"], 1
        ) if stats["total"] > 0 else 0.0
        del stats["total_time"]

    total_points = sum(l.points_earned for l in logs)

    return {
        "total_attempts": total,
        "correct_answers": correct,
        "accuracy_percentage": round((correct / total) * 100, 1),
        "avg_response_time": round(avg_time, 1),
        "total_points_earned": total_points,
        "by_type": by_type,
        "by_difficulty": by_difficulty,
    }


# ─────────────────────────────────────────────────────────────
# Snooze with difficulty escalation
# ─────────────────────────────────────────────────────────────

@router.get(
    "/{alarm_id}/snooze-info",
    summary="Get snooze status for an alarm",
)
def get_snooze_info(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current snooze count, limit, and whether snoozing is allowed.

    The frontend uses this to proactively disable the snooze button.
    """
    alarm = (
        db.query(Alarm)
        .filter(Alarm.id == alarm_id, Alarm.user_id == current_user.id)
        .first()
    )
    if not alarm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alarm not found"
        )

    return {
        "alarm_id": alarm.id,
        "snooze_count": alarm.total_snoozes,
        "snooze_limit": alarm.snooze_limit,
        "can_snooze": alarm.total_snoozes < alarm.snooze_limit,
        "snooze_interval_minutes": alarm.snooze_interval_minutes,
    }


def _calculate_next_trigger(
    alarm: Alarm,
    user_tz: str = "UTC",
    one_time_date: Optional[date] = None,
) -> Optional[datetime]:
    """Calculate the next trigger datetime for an alarm in UTC.

    ``alarm.alarm_time`` is interpreted as wall-clock time in the user's
    local timezone, then converted to UTC for storage/comparison.
    """
    tz = _resolve_timezone(user_tz)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)

    if alarm.alarm_type == AlarmType.ONE_TIME and one_time_date is not None:
        local_dt = datetime.combine(one_time_date, alarm.alarm_time, tzinfo=tz)
        if local_dt <= now_local:
            return None
        return _to_utc_naive(local_dt)

    local_dt = datetime.combine(now_local.date(), alarm.alarm_time, tzinfo=tz)

    if alarm.alarm_type == AlarmType.ONE_TIME:
        if local_dt > now_local:
            return _to_utc_naive(local_dt)
        # Past today's wall-clock time with no explicit date → tomorrow
        return _to_utc_naive(local_dt + timedelta(days=1))

    if alarm.alarm_type == AlarmType.DAILY:
        if local_dt > now_local:
            return _to_utc_naive(local_dt)
        return _to_utc_naive(local_dt + timedelta(days=1))

    if alarm.alarm_type == AlarmType.WEEKDAY:
        # Monday=0 through Friday=4
        for offset in range(7):
            candidate = local_dt + timedelta(days=offset)
            if candidate > now_local and candidate.weekday() < 5:
                return _to_utc_naive(candidate)
        return _to_utc_naive(local_dt + timedelta(days=1))

    if alarm.alarm_type == AlarmType.WEEKEND:
        # Saturday=5, Sunday=6
        for offset in range(7):
            candidate = local_dt + timedelta(days=offset)
            if candidate > now_local and candidate.weekday() >= 5:
                return _to_utc_naive(candidate)
        return _to_utc_naive(local_dt + timedelta(days=1))

    if alarm.alarm_type == AlarmType.SMART_ADAPTIVE:
        if local_dt > now_local:
            return _to_utc_naive(local_dt)
        return _to_utc_naive(local_dt + timedelta(days=1))

    return _to_utc_naive(local_dt + timedelta(days=1))

