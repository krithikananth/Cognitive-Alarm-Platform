"""
Challenge delivery lifecycle and the completion-rate metric.

Completion rate answers a question accuracy cannot: *of the challenges we put
in front of the user, how many did they actually finish in time?* An unanswered
challenge never reaches ``alarm_challenge_logs``, so it is invisible to every
accuracy figure — it is only visible here.

Outcome rules (one classification, used at write time and at read time):

- answered inside the limit                     -> ``completed``
- answered after the limit, or deadline passed  -> ``timed_out``
- unanswered while still in time, and the cycle
  moved on (new challenge issued, alarm
  dismissed, wake abandoned)                    -> ``abandoned``
- unanswered and still inside the limit         -> ``pending`` (in flight)

``pending`` rows are excluded from the rate: a challenge currently on screen is
neither a completion nor a failure yet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.challenge_delivery import (
    OUTCOME_ABANDONED,
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_TIMED_OUT,
    ChallengeDelivery,
)
from app.services.challenge_service import VERIFY_TIME_GRACE_SECONDS


def _naive_utc(value: datetime) -> datetime:
    """Match the naive-UTC convention the rest of the domain tables use."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def _percentage(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


class ChallengeDeliveryService:
    """Record challenges as they are served and settle how they ended."""

    @staticmethod
    def deadline(delivery: ChallengeDelivery) -> datetime:
        """Last instant an answer still counts as completed (naive UTC)."""
        issued = delivery.issued_at
        if issued.tzinfo is not None:
            issued = _naive_utc(issued)
        limit = int(delivery.time_limit_seconds or 0)
        return issued + timedelta(seconds=limit + VERIFY_TIME_GRACE_SECONDS)

    @classmethod
    def record_delivery(
        cls,
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        challenge: Dict[str, Any],
        issued_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> ChallengeDelivery:
        """Log a challenge as served, settling whatever it replaces."""
        now = _naive_utc(issued_at or datetime.now(timezone.utc))
        cls.release_pending(db, user_id=user_id, alarm_id=alarm_id, now=now, commit=False)

        delivery = ChallengeDelivery(
            user_id=user_id,
            alarm_id=alarm_id,
            challenge_type=str(
                challenge.get("type") or challenge.get("challenge_type") or "math"
            ).lower(),
            difficulty=str(challenge.get("difficulty") or "medium"),
            challenge_prompt=str(challenge.get("prompt") or ""),
            time_limit_seconds=int(challenge.get("time_limit_seconds") or 30),
            issued_at=now,
            outcome=OUTCOME_PENDING,
        )
        db.add(delivery)
        db.flush()
        if commit:
            db.commit()
        return delivery

    @classmethod
    def resolve_delivery(
        cls,
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        is_correct: bool,
        time_taken_seconds: int,
        timed_out: bool,
        answered_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> Optional[ChallengeDelivery]:
        """Settle the challenge the user just answered.

        Returns ``None`` when no delivery is open — older sessions predate this
        table, and they must not fabricate a row.
        """
        delivery = cls._open_delivery(db, user_id=user_id, alarm_id=alarm_id)
        if delivery is None:
            return None

        delivery.outcome = OUTCOME_TIMED_OUT if timed_out else OUTCOME_COMPLETED
        delivery.resolved_at = _naive_utc(answered_at or datetime.now(timezone.utc))
        delivery.time_taken_seconds = max(0, int(time_taken_seconds or 0))
        # Only a completed delivery carries a correctness verdict, so an
        # unanswered challenge is never counted as a wrong answer.
        delivery.is_correct = bool(is_correct) if not timed_out else None
        db.flush()
        if commit:
            db.commit()
        return delivery

    @classmethod
    def release_pending(
        cls,
        db: Session,
        *,
        user_id: int,
        alarm_id: Optional[int] = None,
        now: Optional[datetime] = None,
        commit: bool = True,
    ) -> int:
        """Settle deliveries left open because the cycle moved on."""
        moment = _naive_utc(now or datetime.now(timezone.utc))
        query = db.query(ChallengeDelivery).filter(
            ChallengeDelivery.user_id == user_id,
            ChallengeDelivery.outcome == OUTCOME_PENDING,
        )
        if alarm_id is not None:
            query = query.filter(ChallengeDelivery.alarm_id == alarm_id)

        settled = 0
        for delivery in query.all():
            expired = moment > cls.deadline(delivery)
            delivery.outcome = OUTCOME_TIMED_OUT if expired else OUTCOME_ABANDONED
            delivery.resolved_at = moment
            settled += 1

        if settled:
            db.flush()
            if commit:
                db.commit()
        return settled

    @classmethod
    def compute_completion_stats(
        cls,
        db: Session,
        user_id: int,
        days: int,
        *,
        cutoff: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Completion rate over challenges served in the window.

        ``completion_rate = completed / (completed + timed_out + abandoned)``.
        Stale ``pending`` rows past their deadline are read as timeouts here
        rather than rewritten, so a crashed session cannot inflate the rate.
        """
        now = window_end or datetime.now(timezone.utc)
        if cutoff is None:
            cutoff = now - timedelta(days=max(1, int(days or 1)))

        query = db.query(ChallengeDelivery).filter(
            ChallengeDelivery.user_id == user_id,
            ChallengeDelivery.issued_at >= _naive_utc(cutoff),
        )
        if window_end is not None:
            query = query.filter(ChallengeDelivery.issued_at <= _naive_utc(window_end))

        moment = _naive_utc(now)
        counts = {
            OUTCOME_COMPLETED: 0,
            OUTCOME_TIMED_OUT: 0,
            OUTCOME_ABANDONED: 0,
        }
        in_flight = 0
        for delivery in query.all():
            outcome = delivery.outcome
            if outcome == OUTCOME_PENDING:
                if moment > cls.deadline(delivery):
                    outcome = OUTCOME_TIMED_OUT
                else:
                    in_flight += 1
                    continue
            if outcome in counts:
                counts[outcome] += 1

        served = sum(counts.values())
        completed = counts[OUTCOME_COMPLETED]
        return {
            "days": days,
            "served": served,
            "completed": completed,
            "timed_out": counts[OUTCOME_TIMED_OUT],
            "abandoned": counts[OUTCOME_ABANDONED],
            "in_flight": in_flight,
            "completion_rate": _percentage(completed, served),
            "timeout_rate": _percentage(counts[OUTCOME_TIMED_OUT], served),
            "abandonment_rate": _percentage(counts[OUTCOME_ABANDONED], served),
            "status": "ok" if served else "no_data",
        }

    @staticmethod
    def _open_delivery(
        db: Session, *, user_id: int, alarm_id: int
    ) -> Optional[ChallengeDelivery]:
        return (
            db.query(ChallengeDelivery)
            .filter(
                ChallengeDelivery.user_id == user_id,
                ChallengeDelivery.alarm_id == alarm_id,
                ChallengeDelivery.outcome == OUTCOME_PENDING,
            )
            .order_by(ChallengeDelivery.issued_at.desc(), ChallengeDelivery.id.desc())
            .first()
        )
