"""
APScheduler-based notification scheduler.

Runs periodic background jobs for:
- Ringing alarms whose trigger time has arrived (configurable interval)
- Processing the pending notification queue (configurable interval)
- Retrying pushes that failed transiently (configurable interval)
- Scheduling bedtime + wake reminders for all relevant users (every 30 min)
- Scheduling daily motivational + habit alerts (once daily at ~05:30 UTC)
- Purging device tokens retired long ago (once daily at ~05:30 UTC)

Also exposes ``refresh_user_notifications`` for immediate re-scheduling
when alarms are created / updated / toggled / deleted / dismissed / snoozed.

The scheduler uses APScheduler's ``BackgroundScheduler`` which runs in a
daemon thread — it shuts down automatically when the process exits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Return the singleton scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            },
            timezone="UTC",
        )
    return _scheduler


def start_notification_scheduler() -> None:
    """Register all notification jobs and start the scheduler.

    Safe to call multiple times — jobs are only added once.
    """
    from app.core.config import settings

    scheduler = get_scheduler()

    if scheduler.running:
        logger.debug("Notification scheduler already running.")
        return

    interval = max(15, int(settings.NOTIFICATION_PROCESSING_INTERVAL_SECONDS or 60))
    retry_interval = max(
        30, int(settings.NOTIFICATION_RETRY_INTERVAL_SECONDS or 300)
    )
    alarm_interval = max(5, int(settings.ALARM_DISPATCH_INTERVAL_SECONDS or 20))

    # Job 0: Ring due alarms. Runs on its own tight cadence and owns the
    # ALARM_TRIGGER slice of the queue exclusively, so a wake-up is never
    # stuck behind the slower general queue nor double-sent alongside it.
    if settings.ALARM_DISPATCH_ENABLED:
        scheduler.add_job(
            _alarm_dispatch_job,
            trigger=IntervalTrigger(seconds=alarm_interval),
            id="alarm_dispatch_due",
            name="Ring due alarms",
            replace_existing=True,
        )

    # Job 1: Process pending notification queue
    scheduler.add_job(
        _process_queue_job,
        trigger=IntervalTrigger(seconds=interval),
        id="notification_process_queue",
        name="Process pending notification queue",
        replace_existing=True,
    )

    # Job 1b: Re-attempt pushes that failed for transient reasons
    scheduler.add_job(
        _retry_failed_job,
        trigger=IntervalTrigger(seconds=retry_interval),
        id="notification_retry_failed",
        name="Retry failed push deliveries",
        replace_existing=True,
    )

    # Job 2: Refresh bedtime + wake reminders every 30 minutes
    scheduler.add_job(
        _refresh_reminders_job,
        trigger=IntervalTrigger(minutes=30),
        id="notification_refresh_reminders",
        name="Refresh bedtime & wake reminders",
        replace_existing=True,
    )

    # Job 3: Daily motivational + habit alerts at 05:30 UTC
    scheduler.add_job(
        _daily_scheduling_job,
        trigger=CronTrigger(hour=5, minute=30),
        id="notification_daily_scheduling",
        name="Daily motivational & habit alert scheduling",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Notification scheduler started with %d jobs "
        "(alarms every %ds, queue every %ds, retries every %ds).",
        len(scheduler.get_jobs()),
        alarm_interval,
        interval,
        retry_interval,
    )


def shutdown_notification_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Notification scheduler shut down.")
    _scheduler = None


# ── On-demand refresh (called from alarm CRUD / lifecycle endpoints) ─

def refresh_user_notifications(user_id: int) -> None:
    """Immediately re-schedule bedtime + wake reminders for a user.

    Cancels orphaned wake reminders first so deleted / disabled / one-shot
    alarms never leave stray pending notifications.
    """
    from app.db.session import SessionLocal
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        NotificationService.cancel_orphaned_wake_reminders(db, user_id)
        NotificationService.schedule_bedtime_reminder(db, user_id)
        NotificationService.schedule_wake_reminders(db, user_id)
    except Exception as exc:
        logger.error(
            "Failed to refresh notifications for user %d: %s",
            user_id, exc,
            exc_info=True,
        )
    finally:
        db.close()


# ── Internal job functions ───────────────────────────────────────

def _alarm_dispatch_job() -> None:
    """APScheduler job: ring due alarms without needing an open browser tab."""
    from app.db.session import SessionLocal
    from app.models.notification import NotificationType
    from app.services.alarm_dispatch_service import AlarmDispatchService
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        AlarmDispatchService.run_once(db)
        NotificationService.process_pending_notifications(
            db, only_types=[NotificationType.ALARM_TRIGGER]
        )
    except Exception as exc:
        logger.error("Alarm dispatch sweep failed: %s", exc, exc_info=True)
    finally:
        db.close()


def _process_queue_job() -> None:
    """APScheduler job: process the pending notification queue."""
    from app.db.session import SessionLocal
    from app.models.notification import NotificationType
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        # Alarm rings are owned by _alarm_dispatch_job.
        result = NotificationService.process_pending_notifications(
            db, exclude_types=[NotificationType.ALARM_TRIGGER]
        )
        sent = result.get("sent", 0)
        if sent:
            logger.info("Queue job dispatched %d notifications.", sent)
    except Exception as exc:
        logger.error(
            "Notification queue processing failed: %s", exc, exc_info=True
        )
    finally:
        db.close()


def _retry_failed_job() -> None:
    """APScheduler job: re-attempt pushes that failed for transient reasons."""
    from app.db.session import SessionLocal
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        NotificationService.retry_failed_deliveries(db)
    except Exception as exc:
        logger.error(
            "Push retry sweep failed: %s", exc, exc_info=True
        )
    finally:
        db.close()


def _refresh_reminders_job() -> None:
    """APScheduler job: refresh bedtime + wake reminders for all users.

    Includes:
    - Users with at least one active alarm (wake + bedtime)
    - Users with a sleep profile but no alarms (bedtime only)
    """
    from app.db.session import SessionLocal
    from app.models.alarm import Alarm
    from app.models.profile import UserProfile
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        alarm_user_ids = {
            uid
            for (uid,) in db.query(Alarm.user_id)
            .filter(Alarm.is_active.is_(True))
            .distinct()
            .all()
        }
        profile_user_ids = {
            uid
            for (uid,) in db.query(UserProfile.user_id)
            .filter(UserProfile.preferred_wake_time.isnot(None))
            .all()
        }
        user_ids = sorted(alarm_user_ids | profile_user_ids)

        for uid in user_ids:
            try:
                NotificationService.cancel_orphaned_wake_reminders(db, uid)
                NotificationService.schedule_bedtime_reminder(db, uid)
                if uid in alarm_user_ids:
                    NotificationService.schedule_wake_reminders(db, uid)
            except Exception as exc:
                logger.warning(
                    "Reminder refresh failed for user %d: %s", uid, exc
                )
    except Exception as exc:
        logger.error("Reminder refresh job failed: %s", exc)
    finally:
        db.close()


def _daily_scheduling_job() -> None:
    """APScheduler job: daily motivational + habit alerts, then token purge."""
    from app.db.session import SessionLocal
    from app.models.user import User
    from app.services.fcm_service import FCMService
    from app.services.notification_service import NotificationService

    db = SessionLocal()
    try:
        user_ids = (
            db.query(User.id)
            .filter(User.is_active.is_(True))
            .all()
        )
        scheduled = 0
        for (uid,) in user_ids:
            try:
                m = NotificationService.schedule_motivational(db, uid)
                h = NotificationService.schedule_habit_alert(db, uid)
                if m or h:
                    scheduled += 1
            except Exception as exc:
                logger.warning(
                    "Daily scheduling failed for user %d: %s", uid, exc
                )
        logger.info(
            "Daily scheduling complete: %d users received notifications.",
            scheduled,
        )

        try:
            FCMService.cleanup_invalid_tokens(db)
        except Exception as exc:
            logger.warning(
                "Stale device-token purge failed: %s", exc, exc_info=True
            )
    except Exception as exc:
        logger.error("Daily scheduling job failed: %s", exc, exc_info=True)
    finally:
        db.close()
