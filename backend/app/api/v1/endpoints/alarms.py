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
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.challenge_session import ChallengeSession
from app.services.challenge_service import ChallengeService, VERIFY_TIME_GRACE_SECONDS
from app.services.attempt_log_service import AttemptLogService
from app.services.analytics_ingestion_service import AnalyticsIngestionService
from app.services.recommendation_cache import RecommendationCache
from app.services.profile_service import ProfileService
from app.services.adaptive_scheduling_service import AdaptiveSchedulingService
from app.services.day_streak import DayStreakService
from app.schemas.alarm import (
    AlarmCreate,
    AlarmUpdate,
    AlarmResponse,
    AlarmListResponse,
    AlarmToggle,
    SnoozeInfoResponse,
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


def _utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a stored (UTC-naive) datetime with an explicit UTC offset.

    Without the offset, clients parsing the ISO string (e.g. ``new Date(...)``
    in JS) treat it as local time instead of UTC, shifting displayed times by
    the browser's UTC offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()

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

    # Seed baseline from profile preference when the client omits difficulty.
    # Explicit per-alarm values are preserved for storage / UI compatibility.
    if alarm_data.challenge_difficulty is not None:
        challenge_difficulty = alarm_data.challenge_difficulty
    else:
        challenge_difficulty = ChallengeService.resolve_baseline_difficulty(
            getattr(current_user, "profile", None),
            None,
        )

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
        challenge_difficulty=challenge_difficulty,
        volume=alarm_data.volume,
        vibrate=alarm_data.vibrate,
        label=alarm_data.label,
        is_active=True,
    )

    user_tz = _user_timezone(db, current_user.id)
    alarm.next_trigger_at = _calculate_next_trigger(
        alarm,
        user_tz=user_tz,
        one_time_date=alarm_data.one_time_date,
        db=db,
        user_id=current_user.id,
    )

    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    RecommendationCache.invalidate_user(current_user.id)
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
    "/wake-confirmations",
    summary="List wake-up confirmation events",
)
def list_wake_confirmations(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent verified wake-up events for the current user."""
    events = (
        db.query(AlarmWakeEvent)
        .filter(AlarmWakeEvent.user_id == current_user.id)
        .order_by(AlarmWakeEvent.dismissed_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": len(events),
        "events": [
            {
                "id": e.id,
                "alarm_id": e.alarm_id,
                "triggered_at": e.triggered_at,
                "dismissed_at": e.dismissed_at,
                "dismiss_method": e.dismiss_method,
                "challenges_required": e.challenges_required,
                "challenges_completed": e.challenges_completed,
                "consecutive_correct": e.consecutive_correct,
                "failed_attempts": e.failed_attempts,
                "snooze_count_at_dismiss": e.snooze_count_at_dismiss,
                "time_to_dismiss_seconds": e.time_to_dismiss_seconds,
                "wakefulness_score": e.wakefulness_score,
                "wakefulness_level": e.wakefulness_level,
                "verified": e.verified,
            }
            for e in events
        ],
    }


@router.get(
    "/snooze-history",
    summary="List snooze audit events for the current user",
)
def list_snooze_history(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent per-snooze audit rows (Week-2 logging completeness)."""
    events = (
        db.query(AlarmSnoozeEvent)
        .filter(AlarmSnoozeEvent.user_id == current_user.id)
        .order_by(AlarmSnoozeEvent.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "total": len(events),
        "events": [
            {
                "id": e.id,
                "alarm_id": e.alarm_id,
                "snooze_number": e.snooze_number,
                "snooze_limit_at_event": e.snooze_limit_at_event,
                "next_trigger_at": _utc_isoformat(e.next_trigger_at)
                if e.next_trigger_at
                else None,
                "created_at": _utc_isoformat(e.created_at),
            }
            for e in events
        ],
    }


@router.get(
    "/wakefulness",
    summary="Assess current wakefulness from recent performance",
)
def get_wakefulness_assessment(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cognitive wakefulness assessment from recent challenge + wake events."""
    recent_logs = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .order_by(AlarmChallengeLog.created_at.desc())
        .limit(20)
        .all()
    )
    recent_events = (
        db.query(AlarmWakeEvent)
        .filter(
            AlarmWakeEvent.user_id == current_user.id,
            AlarmWakeEvent.verified.is_(True),
        )
        .order_by(AlarmWakeEvent.dismissed_at.desc())
        .limit(10)
        .all()
    )

    if not recent_logs and not recent_events:
        return {
            "score": 0.0,
            "level": "unknown",
            "message": "Complete a wake-up challenge to assess wakefulness.",
            "recent_wake_events": 0,
            "factors": {},
        }

    accuracy = None
    avg_time = 30
    failed = 0
    if recent_logs:
        accuracy = (
            sum(1 for l in recent_logs if l.is_correct) / len(recent_logs)
        ) * 100.0
        times = [l.time_taken_seconds for l in recent_logs if l.is_correct]
        avg_time = int(sum(times) / len(times)) if times else 30
        failed = sum(1 for l in recent_logs if not l.is_correct)

    if recent_events:
        avg_wake = sum(e.wakefulness_score or 0 for e in recent_events) / len(
            recent_events
        )
        last = recent_events[0]
        assessment = ChallengeService.assess_wakefulness(
            consecutive_correct=last.consecutive_correct or 1,
            required_correct=last.challenges_required or 1,
            failed_attempts=failed,
            time_taken_seconds=avg_time,
            time_limit_seconds=max(avg_time, 30),
            recent_accuracy=accuracy,
        )
        assessment["score"] = round((assessment["score"] + avg_wake) / 2, 1)
        if assessment["score"] >= 80:
            assessment["level"] = "sharp"
        elif assessment["score"] >= 55:
            assessment["level"] = "alert"
        elif assessment["score"] >= 30:
            assessment["level"] = "groggy"
        else:
            assessment["level"] = "drowsy"
    else:
        assessment = ChallengeService.assess_wakefulness(
            consecutive_correct=1,
            required_correct=1,
            failed_attempts=failed,
            time_taken_seconds=avg_time,
            time_limit_seconds=max(avg_time, 30),
            recent_accuracy=accuracy,
        )

    assessment["recent_wake_events"] = len(recent_events)
    assessment["recent_accuracy"] = (
        round(accuracy, 1) if accuracy is not None else None
    )
    return assessment


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
            alarm,
            user_tz=user_tz,
            one_time_date=one_time_date,
            db=db,
            user_id=current_user.id,
        )

    db.commit()
    db.refresh(alarm)
    RecommendationCache.invalidate_user(current_user.id)
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
    """Permanently delete an alarm and its related challenge/wake records."""
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

    # Clear dependents first so FK constraints (Postgres / SQLite with FKs on)
    # cannot block the alarm row delete.
    db.query(ChallengeSession).filter(ChallengeSession.alarm_id == alarm_id).delete(
        synchronize_session=False
    )
    db.query(AlarmWakeEvent).filter(AlarmWakeEvent.alarm_id == alarm_id).delete(
        synchronize_session=False
    )
    db.query(AlarmChallengeLog).filter(AlarmChallengeLog.alarm_id == alarm_id).delete(
        synchronize_session=False
    )

    db.delete(alarm)
    db.commit()
    RecommendationCache.invalidate_user(current_user.id)
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
        alarm.next_trigger_at = _calculate_next_trigger(
            alarm, user_tz=user_tz, db=db, user_id=current_user.id
        )

    db.commit()
    db.refresh(alarm)
    RecommendationCache.invalidate_user(current_user.id)
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

    Day Streak is intentionally NOT updated here — snooze is not a final
    wake outcome. Streak changes only after verified challenge dismiss
    (or an explicit final failure) via ``DayStreakService.record_wake_outcome``.
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
    # Anti-snooze: wipe verification progress; next challenge will escalate
    ChallengeService.clear_challenge_session(current_user.id, alarm.id, db)

    # Persist a dedicated snooze audit row (does not change FE contract)
    AttemptLogService.record_snooze(
        db,
        alarm_id=alarm.id,
        user_id=current_user.id,
        snooze_number=alarm.total_snoozes,
        snooze_limit_at_event=alarm.snooze_limit,
        next_trigger_at=alarm.next_trigger_at,
        commit=False,
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

    Personalization pipeline:
      1. Preferred challenge types (for RANDOM alarms)
      2. Profile adapted difficulty as the initial baseline
         (anchored to user preference; preference itself is never auto-changed)
      3. Strict consecutive-streak adaptive difficulty (±1 around the baseline)
      4. Anti-snooze difficulty escalation (applied after adaptive)
      5. Time-of-day softening (easier when groggiest)
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

    # ── Initial difficulty from adapted level (preference as fallback) ──
    profile = ProfileService.get_or_create_profile(db, current_user.id)
    baseline = ChallengeService.resolve_baseline_difficulty(
        profile,
        getattr(alarm, "challenge_difficulty", None),
    )
    user_tz_name = profile.timezone or "UTC"
    habits = profile.habit_preferences or {}
    preferred_types = habits.get("preferred_challenge_types")
    success_streak = int(profile.consecutive_success_streak or 0)
    failure_streak = int(profile.consecutive_failure_streak or 0)

    # Adapt around the working adapted baseline (not snooze-escalated level),
    # then apply anti-snooze escalation on top of the adapted level.
    adaptation = ChallengeService.adapt_difficulty(
        baseline,
        success_streak=success_streak,
        failure_streak=failure_streak,
        last_adapted_success_streak=int(
            getattr(profile, "last_adapted_success_streak", 0) or 0
        ),
        last_adapted_failure_streak=int(
            getattr(profile, "last_adapted_failure_streak", 0) or 0
        ),
    )
    difficulty = adaptation["difficulty"]
    escalation = int(alarm.total_snoozes or 0)
    difficulty = ChallengeService.escalate_difficulty(difficulty, escalation)

    # ── Recent performance logs (newest first; type weighting / anti-repeat) ──
    recent_logs = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .order_by(AlarmChallengeLog.created_at.desc())
        .limit(25)
        .all()
    )

    current_hour = datetime.now(_resolve_timezone(user_tz_name)).hour

    # Avoid repeating the prompt still active in this alarm's session
    active_session = ChallengeService.get_challenge_session(
        current_user.id, alarm.id, db
    )
    exclude_prompts = []
    if active_session and active_session.get("prompt"):
        exclude_prompts.append(active_session["prompt"])

    challenge = ChallengeService.generate_challenge(
        challenge_type=alarm.challenge_type,
        difficulty=difficulty,
        current_hour=current_hour,
        preferred_types=preferred_types,
        recent_logs=recent_logs,
        exclude_prompts=exclude_prompts or None,
        # Already adapted above from stored counters; avoid double-adapt.
        apply_adaptive_difficulty=False,
    )
    challenge["adaptive_difficulty"] = adaptation
    # Persist ±1 into adapted_difficulty only — never difficulty_preference.
    ProfileService.persist_adaptive_difficulty_if_needed(
        db,
        profile,
        recent_logs,
        alarm_difficulty=getattr(alarm, "challenge_difficulty", None),
    )
    # Persist answer + progress server-side (preserve consecutive streak)
    session = ChallengeService.store_challenge_session(
        current_user.id,
        alarm.id,
        challenge,
        db,
        required_correct=alarm.challenge_count,
        escalation_level=escalation,
    )
    return ChallengeService.public_challenge_payload(
        challenge,
        consecutive_correct=session["consecutive_correct"],
        required_correct=session["required_correct"],
        escalation_level=session["escalation_level"],
    )


from pydantic import BaseModel, Field


class VerifyAnswerRequest(BaseModel):
    """Payload for verifying a challenge answer."""

    user_answer: str
    # Deprecated: ignored when a server session exists. Kept for older clients.
    expected_answer: Optional[str] = None
    time_taken_seconds: int = 0
    failed_attempts: int = 0
    challenge_prompt: str = ""
    challenge_difficulty: str = "medium"
    # Deprecated: server tracks progress — client values are ignored
    challenge_step: int = 1
    challenge_total_steps: int = 1


class DismissRequest(BaseModel):
    """Optional verification token for challenge-gated dismissal."""

    verification_token: Optional[str] = Field(
        None, description="Token issued after consecutive challenges are solved"
    )


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
        - Verifies against the **server-stored** challenge session.
        - Logs **every** attempt for analytics.
        - Enforces **time limits** using server-side issuance time.
        - **Multi-step + consecutive correct**: progress is server-tracked;
          a wrong/timeout answer resets the consecutive streak.
        - On full completion, records a wake confirmation and dismisses.
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

    if not session or not session.get("answer"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active challenge. Request a new one first.",
        )

    expected = session["answer"]
    difficulty = session["difficulty"]
    prompt = session["prompt"] or data.challenge_prompt
    resolved_type = session.get("challenge_type") or alarm.challenge_type.value
    max_time = int(session["time_limit_seconds"])
    issued_at = session["issued_at"]
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - issued_at).total_seconds()
    client_time = max(0, int(data.time_taken_seconds or 0))
    time_taken = max(int(round(elapsed)), client_time)
    timed_out = time_taken > (max_time + VERIFY_TIME_GRACE_SECONDS)

    log_type = AttemptLogService.normalize_challenge_type(resolved_type)
    difficulty = AttemptLogService.normalize_difficulty(difficulty)

    is_correct = ChallengeService.verify_answer(expected, data.user_answer)
    actually_correct = is_correct and not timed_out
    score = ChallengeService.calculate_score(
        challenge_type=log_type,
        difficulty=difficulty,
        time_taken_seconds=time_taken,
        is_correct=actually_correct,
    )

    # Every attempt (correct or incorrect) is persisted through one write path
    # so adaptive difficulty / analytics always see clean, queryable rows.
    AttemptLogService.record_attempt(
        db,
        alarm_id=alarm.id,
        user_id=current_user.id,
        challenge_type=log_type,
        difficulty=difficulty,
        challenge_prompt=prompt,
        is_correct=actually_correct,
        time_taken_seconds=time_taken,
        failed_attempts=data.failed_attempts,
        points_earned=score["total_points"],
        commit=True,
    )

    required_steps = max(1, int(session.get("required_correct") or alarm.challenge_count or 1))
    profile = ProfileService.get_or_create_profile(db, current_user.id)

    def _apply_adaptive_outcome(*, completed_wake: bool) -> dict:
        """
        Success Streak updates only on a *final* wake outcome:
        - successful wake completion → +1
        - failed wake completion → reset to 0

        Mid-cycle wrong/timeout, ring, and snooze must not call this.
        Intermediate correct steps also must not. Adaptive difficulty may
        read the counters afterward but never mutates them.

        Returns the post-update streak counters so the verify toast can
        report the Success Streak achieved on this outcome.
        """
        ProfileService.update_adaptive_streaks(
            db,
            profile,
            is_correct=completed_wake,
            commit=True,
        )
        outcome = {
            "success_streak": int(profile.consecutive_success_streak or 0),
            "failure_streak": int(profile.consecutive_failure_streak or 0),
        }
        ProfileService.persist_adaptive_difficulty_if_needed(
            db,
            profile,
            alarm_difficulty=getattr(alarm, "challenge_difficulty", None),
        )
        return outcome

    # ── Timeout / wrong answer → reset in-session consecutive challenge ──
    # Success Streak and Day Streak are NOT updated here: mid-cycle
    # wrong/timeout is not a final wake outcome. Streaks wait for verified
    # dismiss (or ``POST /fail-wake`` for an explicit final failure).
    if timed_out or not is_correct:
        progress = ChallengeService.record_failed_attempt(
            current_user.id, alarm_id, db, reset_streak=True
        )
        wakefulness = ChallengeService.assess_wakefulness(
            consecutive_correct=progress.get("consecutive_correct", 0),
            required_correct=required_steps,
            failed_attempts=progress.get("total_failed_attempts", 0),
            time_taken_seconds=time_taken,
            time_limit_seconds=max_time,
        )
        # Report current Success Streak SSOT without mutating it.
        current_success = int(profile.consecutive_success_streak or 0)
        current_failure = int(profile.consecutive_failure_streak or 0)
        if timed_out:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Time's up! You took {time_taken}s but the "
                    f"limit is {max_time}s for {difficulty} difficulty. "
                    f"Consecutive streak reset — start again."
                ),
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": (
                    "Incorrect answer. Consecutive streak reset — "
                    f"need {required_steps} in a row."
                ),
                "score": score,
                "consecutive_correct": 0,
                "required_correct": required_steps,
                "streak_reset": True,
                "wakefulness": wakefulness,
                "success_streak": current_success,
                "failure_streak": current_failure,
            },
        )

    # ── Correct — advance server-tracked consecutive progress ──
    progress = ChallengeService.record_correct_step(
        current_user.id, alarm_id, db
    )
    consecutive = progress["consecutive_correct"]
    required_steps = progress["required_correct"]

    recent_logs = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .order_by(AlarmChallengeLog.created_at.desc())
        .limit(20)
        .all()
    )
    recent_accuracy = None
    if recent_logs:
        recent_accuracy = (
            sum(1 for l in recent_logs if l.is_correct) / len(recent_logs)
        ) * 100.0

    wakefulness = ChallengeService.assess_wakefulness(
        consecutive_correct=consecutive,
        required_correct=required_steps,
        failed_attempts=progress.get("total_failed_attempts", 0),
        time_taken_seconds=time_taken,
        time_limit_seconds=max_time,
        recent_accuracy=recent_accuracy,
    )

    if consecutive < required_steps:
        # Mid multi-step progress: not a wake completion — no adaptive update.
        return {
            "status": "step_complete",
            "message": (
                f"Correct! {consecutive} of {required_steps} consecutive "
                f"challenges complete."
            ),
            "current_step": consecutive,
            "total_steps": required_steps,
            "next_step": consecutive + 1,
            "consecutive_correct": consecutive,
            "required_correct": required_steps,
            "is_dismissed": False,
            "score": score,
            "wakefulness": wakefulness,
        }

    # ── All consecutive challenges solved — confirm wake & dismiss ──
    # Full wake dismissal counts as one adaptive success.
    adaptive_outcome = _apply_adaptive_outcome(completed_wake=True)
    success_streak = adaptive_outcome["success_streak"]
    alarm_word = "alarm" if success_streak == 1 else "alarms"
    # Anti-snooze audit: mark when the user only woke after exhausting snoozes
    dismiss_method = (
        "snooze_exhausted"
        if (
            alarm.snooze_limit > 0
            and alarm.total_snoozes >= alarm.snooze_limit
        )
        else "challenge"
    )
    result = _dismiss_alarm_internal(
        alarm,
        current_user,
        db,
        dismiss_method=dismiss_method,
        verification=progress,
        wakefulness=wakefulness,
    )
    return {
        "status": "dismissed",
        "message": (
            f"Wake-up verified! {success_streak} consecutive "
            f"{alarm_word} solved. Alarm dismissed."
        ),
        "current_step": consecutive,
        "total_steps": required_steps,
        "consecutive_correct": consecutive,
        "required_correct": required_steps,
        "is_dismissed": True,
        "verification_token": progress.get("verification_token"),
        "alarm": AlarmResponse.model_validate(result).model_dump(mode="json"),
        "score": score,
        "wakefulness": wakefulness,
        "wake_confirmed": True,
        # Adaptive consecutive wake streak (keeps climbing across adapts).
        "success_streak": success_streak,
        "failure_streak": adaptive_outcome["failure_streak"],
    }


@router.post(
    "/{alarm_id}/dismiss",
    response_model=AlarmResponse,
    summary="Dismiss alarm (verification required)",
)
def dismiss_alarm(
    alarm_id: int,
    body: DismissRequest = DismissRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Dismiss only after wake-up verification completes.

    Prefer ``POST /verify`` which auto-dismisses on full consecutive
    completion. This endpoint accepts an optional ``verification_token``
    issued by a completed verify session.
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
    token = body.verification_token
    wake_ok = bool(
        session
        and session.get("wake_confirmed")
        and session.get("verification_token")
        and (not token or token == session["verification_token"])
    )
    if not wake_ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Wake-up verification required. Solve the cognitive "
                "challenge(s) via POST /verify before dismissing."
            ),
        )

    dismiss_method = (
        "snooze_exhausted"
        if (
            alarm.snooze_limit > 0
            and alarm.total_snoozes >= alarm.snooze_limit
        )
        else "challenge"
    )
    return _dismiss_alarm_internal(
        alarm,
        current_user,
        db,
        dismiss_method=dismiss_method,
        verification=session,
    )


@router.post(
    "/{alarm_id}/fail-wake",
    summary="Record a final failed wake (abandon active cycle)",
)
def fail_wake(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """End an active wake cycle as a final failure.

    This is the only production path that increments Failure Streak.
    Mid-cycle wrong answers, timeouts, ringing, and snoozes must never
    call this — those are not final wake outcomes.

    Requires an active challenge session that has not already been
    wake-confirmed. Applies:

    - Failure Streak +1, Success Streak → 0
    - Day Streak failure (no-op if already succeeded today)
    - Adaptive difficulty persist when the failure threshold is met
    - Unverified ``AlarmWakeEvent`` with ``dismiss_method="abandoned"``
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
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No active wake cycle to fail. Open the challenge first, "
                "or the cycle was already closed."
            ),
        )
    if session.get("wake_confirmed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wake already verified for this cycle. Use dismiss instead "
                "of fail-wake."
            ),
        )

    return _fail_wake_internal(alarm, current_user, db, session=session)


def _fail_wake_internal(
    alarm: Alarm,
    current_user: User,
    db: Session,
    *,
    session: dict,
):
    """Shared final-failure logic for an active (unverified) wake cycle."""
    now = datetime.now(timezone.utc)
    user_tz = _user_timezone(db, current_user.id)
    profile = ProfileService.get_or_create_profile(db, current_user.id)

    consecutive = int(session.get("consecutive_correct") or 0)
    required = int(
        session.get("required_correct") or alarm.challenge_count or 1
    )
    failed = int(session.get("total_failed_attempts") or 0)
    started = session.get("session_started_at")
    time_to_fail = None
    if started is not None:
        if getattr(started, "tzinfo", None) is None:
            started = started.replace(tzinfo=timezone.utc)
        time_to_fail = max(0, int((now - started).total_seconds()))

    # Schedule the next ring the same way a completed cycle would.
    if alarm.alarm_type == AlarmType.ONE_TIME:
        alarm.is_active = False
        alarm.next_trigger_at = None
    else:
        alarm.next_trigger_at = _calculate_next_trigger(
            alarm, user_tz=user_tz, db=db, user_id=current_user.id
        )
    alarm.last_triggered_at = now

    wake_event = AlarmWakeEvent(
        user_id=current_user.id,
        alarm_id=alarm.id,
        triggered_at=started or now,
        dismissed_at=now,
        dismiss_method="abandoned",
        challenges_required=required,
        challenges_completed=consecutive,
        consecutive_correct=consecutive,
        failed_attempts=failed,
        snooze_count_at_dismiss=alarm.total_snoozes,
        time_to_dismiss_seconds=time_to_fail,
        wakefulness_score=None,
        wakefulness_level=None,
        verified=False,
    )
    db.add(wake_event)
    db.flush()

    AnalyticsIngestionService.emit_alarm_abandoned(
        db,
        user_id=current_user.id,
        alarm_id=alarm.id,
        wake_event_id=wake_event.id,
        dismiss_method="abandoned",
        snooze_count=alarm.total_snoozes,
        consecutive_correct=consecutive,
        challenges_required=required,
        failed_attempts=failed,
        time_to_fail_seconds=time_to_fail,
        commit=False,
    )

    # Final wake outcome — Failure Streak +1, Success Streak → 0.
    # Mid-cycle wrong/timeout / snooze / ring must never reach here.
    ProfileService.update_adaptive_streaks(
        db,
        profile,
        is_correct=False,
        commit=False,
    )
    DayStreakService.record_wake_outcome(
        profile,
        outcome="failure",
        at=now,
        timezone_name=user_tz,
    )

    # Mild consistency penalty for abandoning an active cycle.
    profile.wake_up_consistency_score = max(
        0.0, float(profile.wake_up_consistency_score or 0.0) - 5.0
    )
    profile.total_snoozes += alarm.total_snoozes

    # Persist adaptive ±1 when failure threshold is newly met.
    ProfileService.persist_adaptive_difficulty_if_needed(
        db,
        profile,
        alarm_difficulty=getattr(alarm, "challenge_difficulty", None),
        commit=False,
    )

    alarm.total_snoozes = 0
    ChallengeService.clear_challenge_session(current_user.id, alarm.id, db)

    db.commit()
    db.refresh(alarm)
    db.refresh(profile)
    RecommendationCache.invalidate_user(current_user.id)

    failure_streak = int(profile.consecutive_failure_streak or 0)
    success_streak = int(profile.consecutive_success_streak or 0)
    adapted = (
        profile.adapted_difficulty.value
        if getattr(profile, "adapted_difficulty", None)
        else None
    )
    return {
        "status": "failed",
        "message": (
            f"Wake cycle abandoned. Failure streak is now {failure_streak}."
        ),
        "wake_confirmed": False,
        "is_dismissed": False,
        "dismiss_method": "abandoned",
        "success_streak": success_streak,
        "failure_streak": failure_streak,
        "adapted_difficulty": adapted,
        "day_streak": int(profile.streak_days or 0),
        "alarm": AlarmResponse.model_validate(alarm).model_dump(mode="json"),
    }


def _dismiss_alarm_internal(
    alarm: Alarm,
    current_user: User,
    db: Session,
    *,
    dismiss_method: str = "challenge",
    verification: Optional[dict] = None,
    wakefulness: Optional[dict] = None,
):
    """Shared dismissal logic used by verify (auto-dismiss) and gated dismiss."""
    now = datetime.now(timezone.utc)
    alarm.total_dismissals += 1
    alarm.last_triggered_at = now
    user_tz = _user_timezone(db, current_user.id)
    if alarm.alarm_type == AlarmType.ONE_TIME:
        alarm.is_active = False
        alarm.next_trigger_at = None
    else:
        alarm.next_trigger_at = _calculate_next_trigger(
            alarm, user_tz=user_tz, db=db, user_id=current_user.id
        )

    consecutive = int((verification or {}).get("consecutive_correct") or alarm.challenge_count or 1)
    required = int((verification or {}).get("required_correct") or alarm.challenge_count or 1)
    failed = int((verification or {}).get("total_failed_attempts") or 0)
    started = (verification or {}).get("session_started_at")
    time_to_dismiss = None
    if started is not None:
        if getattr(started, "tzinfo", None) is None:
            started = started.replace(tzinfo=timezone.utc)
        time_to_dismiss = max(0, int((now - started).total_seconds()))

    if wakefulness is None:
        wakefulness = ChallengeService.assess_wakefulness(
            consecutive_correct=consecutive,
            required_correct=required,
            failed_attempts=failed,
            time_taken_seconds=time_to_dismiss or 0,
            time_limit_seconds=max(30, (time_to_dismiss or 30)),
        )

    # Wake-up confirmation tracking
    wake_event = AlarmWakeEvent(
        user_id=current_user.id,
        alarm_id=alarm.id,
        triggered_at=started or now,
        dismissed_at=now,
        dismiss_method=dismiss_method,
        challenges_required=required,
        challenges_completed=consecutive,
        consecutive_correct=consecutive,
        failed_attempts=failed,
        snooze_count_at_dismiss=alarm.total_snoozes,
        time_to_dismiss_seconds=time_to_dismiss,
        wakefulness_score=wakefulness.get("score"),
        wakefulness_level=wakefulness.get("level"),
        verified=True,
    )
    db.add(wake_event)
    db.flush()
    # Additive analytics fan-out — wake event table remains SSOT.
    AnalyticsIngestionService.emit_alarm_dismissed(
        db,
        user_id=current_user.id,
        alarm_id=alarm.id,
        wake_event_id=wake_event.id,
        dismiss_method=dismiss_method,
        snooze_count=alarm.total_snoozes,
        wakefulness_score=wakefulness.get("score"),
        wakefulness_level=wakefulness.get("level"),
        time_to_dismiss_seconds=time_to_dismiss,
        commit=False,
    )

    if current_user.profile:
        current_user.profile.total_alarms_dismissed += 1

        # Final wake outcome only — Day Streak updates exactly once here.
        # Ring / snooze / mid-cycle wrong+timeout must never call this.
        # Same calendar day: at most one increment (record_wake_outcome no-op).
        DayStreakService.record_wake_outcome(
            current_user.profile,
            outcome="success",
            at=now,
            timezone_name=user_tz,
        )

        if alarm.total_snoozes == 0:
            current_user.profile.wake_up_consistency_score = min(
                100.0, current_user.profile.wake_up_consistency_score + 5.0
            )
        elif (
            alarm.snooze_limit > 0
            and alarm.total_snoozes >= alarm.snooze_limit
        ):
            # Hit the snooze ceiling this cycle.
            current_user.profile.wake_up_consistency_score = max(
                0.0, current_user.profile.wake_up_consistency_score - 10.0
            )
        elif alarm.total_snoozes > 0:
            # Mid-cycle snoozes (1..limit-1): milder consistency penalty.
            current_user.profile.wake_up_consistency_score = max(
                0.0, current_user.profile.wake_up_consistency_score - 5.0
            )

        current_user.profile.total_snoozes += alarm.total_snoozes

    alarm.total_snoozes = 0
    ChallengeService.clear_challenge_session(current_user.id, alarm.id, db)

    db.commit()
    db.refresh(alarm)
    RecommendationCache.invalidate_user(current_user.id)
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
                "created_at": _utc_isoformat(log.created_at),
            }
            for log in logs
        ],
    }


@router.get(
    "/challenge/log-health",
    summary="Audit attempt-log cleanliness and queryability",
)
def get_challenge_log_health(
    repair: bool = Query(
        False,
        description="If true, normalize dirty rows for the current user first",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify Week-2 attempt logs are clean and usable by ML / analytics.

    Checks required fields, allowed types/difficulties, non-negative metrics,
    orphan alarm references, and the user_id + created_at query path used by
    adaptive difficulty and stats endpoints.
    """
    if repair:
        AttemptLogService.repair_logs(db, user_id=current_user.id, commit=True)

    report = AttemptLogService.audit_logs(db, user_id=current_user.id)
    report["repaired"] = bool(repair)
    return report


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


@router.get(
    "/challenge/history",
    summary="Get all challenge attempt history for the current user",
)
def get_user_challenge_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated challenge attempt history across all of the user's alarms."""
    query = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .order_by(AlarmChallengeLog.created_at.desc())
    )
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()

    history = [
        {
            "id": log.id,
            "alarm_id": log.alarm_id,
            "challenge_type": log.challenge_type,
            "difficulty": log.difficulty,
            "challenge_prompt": log.challenge_prompt,
            "is_correct": log.is_correct,
            "time_taken_seconds": log.time_taken_seconds,
            "failed_attempts": log.failed_attempts,
            "points_earned": log.points_earned,
            "created_at": _utc_isoformat(log.created_at),
        }
        for log in rows
    ]
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "history": history,
    }


@router.get(
    "/challenge/analysis",
    summary="Deep challenge completion analysis and recommendations",
)
def get_challenge_analysis(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze challenge completion patterns and return actionable insights.

    Includes strengths/weaknesses by type, performance trend, recommendations,
    and suggested preferred challenge types.
    """
    logs = (
        db.query(AlarmChallengeLog)
        .filter(AlarmChallengeLog.user_id == current_user.id)
        .order_by(AlarmChallengeLog.created_at.desc())
        .all()
    )
    analysis = ChallengeService.analyze_completion(logs)

    # Attach current personalization context
    preferred = []
    difficulty = "medium"
    if current_user.profile:
        habits = current_user.profile.habit_preferences or {}
        preferred = habits.get("preferred_challenge_types") or []
        if current_user.profile.difficulty_preference:
            difficulty = current_user.profile.difficulty_preference.value

    if current_user.profile:
        # Adapt around the working adapted level; preference stays separate.
        # Success Streak SSOT: stored consecutive_success_streak only.
        from app.services.success_streak import SuccessStreakService

        baseline = ChallengeService.resolve_baseline_difficulty(
            current_user.profile
        )
        adaptation = ChallengeService.adapt_difficulty(
            baseline,
            logs[:20],
            success_streak=SuccessStreakService.read_stored_streak(
                current_user.profile
            ),
            failure_streak=int(
                current_user.profile.consecutive_failure_streak or 0
            ),
            last_adapted_success_streak=int(
                getattr(
                    current_user.profile, "last_adapted_success_streak", 0
                )
                or 0
            ),
            last_adapted_failure_streak=int(
                getattr(
                    current_user.profile, "last_adapted_failure_streak", 0
                )
                or 0
            ),
        )
    else:
        adaptation = ChallengeService.adapt_difficulty(difficulty, logs[:20])
    analysis["personalization"] = {
        "preferred_challenge_types": preferred,
        "difficulty_preference": difficulty,
        "adaptive_difficulty": adaptation,
    }
    return analysis


# ─────────────────────────────────────────────────────────────
# Snooze status (anti-snooze escalation)
# ─────────────────────────────────────────────────────────────

@router.get(
    "/{alarm_id}/snooze-info",
    response_model=SnoozeInfoResponse,
    summary="Get snooze / anti-snooze status for an alarm",
)
def get_snooze_info(
    alarm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return snooze count, limit, and anti-snooze escalation preview.

    The frontend uses this to disable the snooze control and show how much
    harder the next challenge will be after prior snoozes.
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

    escalation = int(alarm.total_snoozes or 0)
    can_snooze = alarm.total_snoozes < alarm.snooze_limit
    base_diff = ChallengeService.resolve_baseline_difficulty(
        getattr(current_user, "profile", None),
        getattr(alarm, "challenge_difficulty", None),
    )

    return SnoozeInfoResponse(
        alarm_id=alarm.id,
        snooze_count=alarm.total_snoozes,
        snooze_limit=alarm.snooze_limit,
        can_snooze=can_snooze,
        snooze_interval_minutes=alarm.snooze_interval_minutes,
        escalation_level=escalation,
        next_challenge_difficulty=ChallengeService.escalate_difficulty(
            base_diff, escalation
        ),
        anti_snooze_enforced=not can_snooze,
    )


def _calculate_next_trigger(
    alarm: Alarm,
    user_tz: str = "UTC",
    one_time_date: Optional[date] = None,
    db: Optional[Session] = None,
    user_id: Optional[int] = None,
) -> Optional[datetime]:
    """Calculate the next trigger datetime for an alarm in UTC.

    ``alarm.alarm_time`` is interpreted as wall-clock time in the user's
    local timezone, then converted to UTC for storage/comparison.

    Smart Adaptive alarms optionally use ``db`` / ``user_id`` to shift the
    ring time from habit, snooze, wake-consistency, and sleep-schedule signals.
    Other alarm types ignore those arguments and keep fixed schedules.
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
        if db is not None and user_id is not None:
            adapted_local = AdaptiveSchedulingService.compute_next_local_trigger(
                db, user_id, alarm, now_local, tz
            )
            return _to_utc_naive(adapted_local)
        # Fallback when called without DB context — same as daily at alarm_time
        if local_dt > now_local:
            return _to_utc_naive(local_dt)
        return _to_utc_naive(local_dt + timedelta(days=1))

    return _to_utc_naive(local_dt + timedelta(days=1))

