"""
Server-side alarm dispatch.

The frontend rings alarms while a tab is open (``AlarmWatcher`` →
``activeAlarmStore``). This service is the server-side safety net so a closed
or sleeping browser cannot cause a missed wake-up: it sweeps armed alarms whose
``next_trigger_at`` has arrived and queues a high-priority ``ALARM_TRIGGER``
push notification for each one.

It deliberately does **not** run the wake cycle. Challenges, adaptive
difficulty, snooze and wake verification all stay in the existing endpoints —
opening the notification hands the user to exactly the same flow they get today.

Two independent sweeps run per pass:

``_dispatch_due``
    Queue one ring notification per (alarm, trigger instant). Dedup is by
    ``Alarm.last_notified_trigger_at``, so a restart, a slow queue, or two
    overlapping passes can never double-ring the same instant. Alarms later
    than ``ALARM_DISPATCH_MAX_LATENESS_MINUTES`` are skipped rather than pushed,
    so a server that was down overnight does not ring at lunchtime.

``_roll_over_missed``
    Advance alarms nobody attended to. Without this a single missed morning
    parks ``next_trigger_at`` in the past forever and a daily alarm never rings
    again. Recurrence is recomputed with the very same
    ``_calculate_next_trigger`` the alarm endpoints use, so one-time, recurring
    and smart-adaptive alarms keep identical scheduling semantics.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alarm import Alarm, AlarmType
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

logger = logging.getLogger(__name__)

#: Cap on alarms handled per sweep so one pass can never monopolise the worker.
_MAX_PER_SWEEP = 200


def _utc_naive_now() -> datetime:
    """Current UTC time as a naive datetime (matches stored column values)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AlarmDispatchService:
    """Queue ring notifications for due alarms and rescue missed ones."""

    # ── Tunables ─────────────────────────────────────────────────

    @staticmethod
    def _max_lateness() -> timedelta:
        minutes = max(1, int(settings.ALARM_DISPATCH_MAX_LATENESS_MINUTES or 15))
        return timedelta(minutes=minutes)

    @staticmethod
    def _rollover_age() -> timedelta:
        minutes = max(5, int(settings.ALARM_MISSED_ROLLOVER_MINUTES or 60))
        return timedelta(minutes=minutes)

    # ── Public entry point ───────────────────────────────────────

    @classmethod
    def run_once(cls, db: Session) -> Dict[str, int]:
        """Perform one full dispatch pass.

        Returns counters for ``dispatched``, ``rolled_over`` and ``retired``.
        """
        now = _utc_naive_now()
        dispatched = cls._dispatch_due(db, now)
        rolled_over, retired = cls._roll_over_missed(db, now)
        return {
            "dispatched": dispatched,
            "rolled_over": rolled_over,
            "retired": retired,
        }

    # ── Ring dispatch ────────────────────────────────────────────

    @classmethod
    def _dispatch_due(cls, db: Session, now: datetime) -> int:
        """Queue an ``ALARM_TRIGGER`` notification for every newly due alarm."""
        earliest = now - cls._max_lateness()

        due: List[Alarm] = (
            db.query(Alarm)
            .filter(
                Alarm.is_active.is_(True),
                Alarm.next_trigger_at.isnot(None),
                Alarm.next_trigger_at <= now,
                Alarm.next_trigger_at >= earliest,
            )
            .order_by(Alarm.next_trigger_at)
            .limit(_MAX_PER_SWEEP)
            .all()
        )

        created = 0
        for alarm in due:
            if alarm.last_notified_trigger_at == alarm.next_trigger_at:
                continue

            db.add(cls._build_notification(alarm))
            alarm.last_notified_trigger_at = alarm.next_trigger_at
            created += 1

        if created:
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.error(
                    "Failed to queue %d alarm ring notification(s); the next "
                    "sweep will retry.",
                    created,
                    exc_info=True,
                )
                return 0
            logger.info("Queued %d alarm ring notification(s).", created)
        return created

    @staticmethod
    def _build_notification(alarm: Alarm) -> Notification:
        """Build the ring notification for ``alarm``'s current trigger instant."""
        alarm_time_str = alarm.alarm_time.strftime("%I:%M %p").lstrip("0")
        trigger_iso = (
            alarm.next_trigger_at.replace(tzinfo=timezone.utc).isoformat()
            if alarm.next_trigger_at is not None
            else None
        )
        return Notification(
            user_id=alarm.user_id,
            notification_type=NotificationType.ALARM_TRIGGER,
            title=f"⏰ {alarm.title or 'Alarm'}",
            body=(
                f"It's {alarm_time_str}. Open the app and solve your "
                f"challenge to turn the alarm off."
            ),
            data={
                "alarm_id": alarm.id,
                "alarm_title": alarm.title,
                "alarm_time": alarm.alarm_time.isoformat(),
                "trigger_at": trigger_iso,
                # Consumed by the service worker / foreground handler to open
                # the ringing modal instead of just focusing the app.
                "action": "ring_alarm",
                "requires_interaction": True,
                "url": (
                    f"{str(settings.FRONTEND_URL).rstrip('/')}"
                    f"/alarms?ring={alarm.id}"
                ),
            },
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=alarm.next_trigger_at,
            related_alarm_id=alarm.id,
        )

    # ── Missed-alarm rollover ────────────────────────────────────

    @classmethod
    def _roll_over_missed(cls, db: Session, now: datetime) -> tuple[int, int]:
        """Advance (or retire) alarms whose trigger passed unattended.

        Returns ``(rolled_over, retired)``.
        """
        # Imported lazily: the endpoint module imports the notification
        # scheduler, which imports this service.
        from app.api.v1.endpoints.alarms import (
            _calculate_next_trigger,
            _user_timezone,
        )

        cutoff = now - cls._rollover_age()

        stale: List[Alarm] = (
            db.query(Alarm)
            .filter(
                Alarm.is_active.is_(True),
                Alarm.next_trigger_at.isnot(None),
                Alarm.next_trigger_at < cutoff,
            )
            .order_by(Alarm.next_trigger_at)
            .limit(_MAX_PER_SWEEP)
            .all()
        )
        if not stale:
            return 0, 0

        rolled_over = 0
        retired = 0
        tz_cache: Dict[int, str] = {}

        for alarm in stale:
            if alarm.alarm_type == AlarmType.ONE_TIME:
                alarm.is_active = False
                alarm.next_trigger_at = None
                retired += 1
                continue

            user_tz = tz_cache.get(alarm.user_id)
            if user_tz is None:
                user_tz = _user_timezone(db, alarm.user_id)
                tz_cache[alarm.user_id] = user_tz

            try:
                next_trigger = _calculate_next_trigger(
                    alarm, user_tz=user_tz, db=db, user_id=alarm.user_id
                )
            except Exception:
                logger.warning(
                    "Could not recompute next trigger for alarm %d; leaving "
                    "it untouched.",
                    alarm.id,
                    exc_info=True,
                )
                continue

            # A recomputation that stays in the past would re-enter this sweep
            # forever; leave the alarm alone so the state stays inspectable.
            if next_trigger is None or next_trigger <= now:
                continue

            alarm.next_trigger_at = next_trigger
            rolled_over += 1

        if not (rolled_over or retired):
            return 0, 0

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error(
                "Failed to roll over missed alarms; the next sweep will retry.",
                exc_info=True,
            )
            return 0, 0

        logger.info(
            "Missed-alarm sweep: %d rescheduled, %d one-time alarms retired.",
            rolled_over,
            retired,
        )
        return rolled_over, retired
