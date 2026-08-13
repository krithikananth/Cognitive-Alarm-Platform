"""
Core notification orchestration.

Handles creation, scheduling, dispatch, and querying of notifications.
Computes bedtime/wake reminders from the existing alarm scheduler and
profile sleep data.  Generates motivational content via Gemini AI with
static fallback.

Guarantees:
- Zero duplicate pending notifications per logical event
- Timezone-aware scheduling via UserProfile.timezone
- Preference / quiet-hours / push_enabled enforcement at dispatch
- Orphaned wake reminders cancelled when alarms are deleted or disabled
- Every dispatch records its delivery outcome (status, timestamps, attempt
  counters, failure reason) so nothing fails silently
- Transient push failures are retried with exponential backoff; permanently
  invalid device tokens are retired instead of retried
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alarm import Alarm
from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationPreference,
    NotificationStatus,
    NotificationType,
    UserDeviceToken,
)
from app.models.profile import UserProfile
from app.services.fcm_service import FCMService

logger = logging.getLogger(__name__)


# ── Static motivational messages (fallback when Gemini unavailable) ──

_MOTIVATIONAL_MESSAGES: List[Dict[str, str]] = [
    {
        "title": "Rise & Shine! ☀️",
        "body": "Every morning is a fresh start. Your consistency is building real habits — keep it going!",
    },
    {
        "title": "You're Building Something Great 💪",
        "body": "Each alarm you conquer strengthens your discipline. Small wins compound into major life changes.",
    },
    {
        "title": "Your Brain Thanks You 🧠",
        "body": "Consistent wake-up times improve cognitive function. You're literally getting smarter every day.",
    },
    {
        "title": "Streak Power! 🔥",
        "body": "Maintaining your wake-up streak isn't just a number — it's proof you can commit to yourself.",
    },
    {
        "title": "Champion Mindset 🏆",
        "body": "The hardest part is leaving the bed. Once you're up, the day is yours to own.",
    },
    {
        "title": "Morning Energy Boost ⚡",
        "body": "Your body's cortisol peaks in the morning. Wake on time to ride that natural energy wave.",
    },
    {
        "title": "Progress, Not Perfection 🌱",
        "body": "Even on tough mornings, showing up matters. Every challenge completed is a step forward.",
    },
    {
        "title": "Sleep Scientist 🌙",
        "body": "Sticking to your sleep schedule regulates your circadian rhythm. Tonight's rest fuels tomorrow's wins.",
    },
    {
        "title": "The 1% Edge 📈",
        "body": "Waking up on time gives you an extra hour of focus. Over a year, that's 365 hours of advantage.",
    },
    {
        "title": "Your Future Self Says Thanks 🙏",
        "body": "The habits you build today shape who you become. Keep showing up — you're doing amazing.",
    },
    {
        "title": "Mindful Morning 🧘",
        "body": "A consistent wake routine reduces stress hormones. Your calm mornings create calmer days.",
    },
    {
        "title": "Unlock Your Potential 🔓",
        "body": "Studies show early risers report higher productivity and well-being. You're on the right path.",
    },
]

_TYPE_PREF_FIELD = {
    NotificationType.BEDTIME_REMINDER: "bedtime_reminder_enabled",
    NotificationType.WAKE_REMINDER: "wake_reminder_enabled",
    NotificationType.HABIT_ALERT: "habit_alerts_enabled",
    NotificationType.CHALLENGE_REMINDER: "challenge_reminders_enabled",
    NotificationType.PROGRESS_UPDATE: "progress_updates_enabled",
    NotificationType.MOTIVATIONAL: "motivational_enabled",
}

# Frequency filters which types may fire even when their individual toggles are on.
_FREQUENCY_ALLOWED = {
    "all": {
        NotificationType.BEDTIME_REMINDER,
        NotificationType.WAKE_REMINDER,
        NotificationType.HABIT_ALERT,
        NotificationType.CHALLENGE_REMINDER,
        NotificationType.PROGRESS_UPDATE,
        NotificationType.MOTIVATIONAL,
    },
    "essential": {
        NotificationType.BEDTIME_REMINDER,
        NotificationType.WAKE_REMINDER,
    },
    "minimal": {
        NotificationType.WAKE_REMINDER,
    },
}

#: Types that bypass preferences, quiet hours and the per-user push toggle.
#: An alarm ringing is the product's core promise, and an admin announcement is
#: a platform broadcast — neither is a discretionary reminder.
_ALWAYS_DELIVER_TYPES = frozenset(
    {NotificationType.ANNOUNCEMENT, NotificationType.ALARM_TRIGGER}
)

_ALL_NOTIFICATION_TYPES = list(NotificationType)
#: Types the master notification toggle may cancel wholesale. An alarm ring is
#: the alarm itself, not a reminder about it, so it is never silenced here.
_USER_CANCELLABLE_TYPES = [
    t for t in _ALL_NOTIFICATION_TYPES if t != NotificationType.ALARM_TRIGGER
]
_VALID_SOUNDS = {"default", "gentle", "chime", "silent"}
_VALID_FREQUENCIES = set(_FREQUENCY_ALLOWED.keys())

#: ``Notification.last_error`` column width.
_MAX_ERROR_LEN = 500
#: Ceiling on exponential retry backoff so a retry is never parked for a day.
_MAX_RETRY_DELAY_SECONDS = 6 * 60 * 60

#: A challenge reminder is a practice nudge, so it only fires once the user has
#: gone this long without attempting a challenge.
CHALLENGE_IDLE_DAYS = 2
#: Minimum gap between two challenge reminders. Wider than the daily scheduling
#: sweep so a user who stays idle is nudged periodically, never nagged daily.
CHALLENGE_REMINDER_COOLDOWN_HOURS = 72
#: Local hour the practice nudge is delivered at (evening prep for tomorrow).
CHALLENGE_REMINDER_LOCAL_HOUR = 19

#: Progress recaps summarise a rolling week and are sent at most once per week.
PROGRESS_PERIOD_DAYS = 7
#: Local hour the weekly recap is delivered at.
PROGRESS_LOCAL_HOUR = 9
#: Streak lengths worth calling out explicitly in a progress recap.
STREAK_MILESTONES = (3, 7, 14, 30, 60, 100, 180, 365)

#: Statuses that mean a notification of this type already exists for a period.
#: ``FAILED`` is excluded so a cancelled row never blocks a fresh schedule.
_LIVE_STATUSES = (
    NotificationStatus.PENDING,
    NotificationStatus.SENT,
    NotificationStatus.DELIVERED,
    NotificationStatus.READ,
)


def _truncate_error(message: Any) -> str:
    """Collapse an error to a single line that fits ``last_error``."""
    return " ".join(str(message).split())[:_MAX_ERROR_LEN]


def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    """Return a ZoneInfo, falling back to UTC on unknown names."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def _utc_naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _next_local_hour_utc(
    profile: Optional[UserProfile], hour: int
) -> datetime:
    """Return the next occurrence of ``hour`` in the user's tz, as naive UTC."""
    tz = _resolve_tz(profile.timezone if profile else None)
    now_local = datetime.now(tz)
    target = datetime.combine(now_local.date(), time(hour, 0), tzinfo=tz)
    if target < now_local:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc).replace(tzinfo=None)


class NotificationService:
    """Create, schedule, dispatch, and query notifications."""

    # ── Cancellation / cleanup ───────────────────────────────────

    @staticmethod
    def cancel_pending_for_alarm(db: Session, alarm_id: int) -> int:
        """Cancel all pending wake reminders tied to an alarm.

        Called before alarm delete / disable so nothing duplicates or
        fires for a removed alarm.
        """
        count = (
            db.query(Notification)
            .filter(
                Notification.related_alarm_id == alarm_id,
                Notification.status == NotificationStatus.PENDING,
            )
            .update(
                {
                    Notification.status: NotificationStatus.FAILED,
                    Notification.last_error: "cancelled_alarm_removed_or_disabled",
                    Notification.next_retry_at: None,
                },
                synchronize_session="fetch",
            )
        )
        if count:
            db.commit()
        return count

    @classmethod
    def cancel_orphaned_wake_reminders(cls, db: Session, user_id: int) -> int:
        """Cancel pending wake reminders for missing or inactive alarms."""
        pending = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.WAKE_REMINDER,
                Notification.status == NotificationStatus.PENDING,
            )
            .all()
        )
        if not pending:
            return 0

        alarm_ids = {n.related_alarm_id for n in pending if n.related_alarm_id}
        active_ids: Set[int] = set()
        if alarm_ids:
            active_ids = {
                row[0]
                for row in db.query(Alarm.id)
                .filter(
                    Alarm.id.in_(alarm_ids),
                    Alarm.is_active.is_(True),
                )
                .all()
            }

        cancelled = 0
        for notif in pending:
            if notif.related_alarm_id is None or notif.related_alarm_id not in active_ids:
                notif.status = NotificationStatus.FAILED
                notif.last_error = "cancelled_orphaned_alarm"
                notif.next_retry_at = None
                cancelled += 1

        if cancelled:
            db.commit()
        return cancelled

    @staticmethod
    def cancel_pending_by_types(
        db: Session,
        user_id: int,
        types: List[NotificationType],
    ) -> int:
        """Cancel pending notifications of the given types for a user."""
        if not types:
            return 0
        count = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type.in_(types),
                Notification.status == NotificationStatus.PENDING,
            )
            .update(
                {
                    Notification.status: NotificationStatus.FAILED,
                    Notification.last_error: "cancelled_type_disabled",
                    Notification.next_retry_at: None,
                },
                synchronize_session="fetch",
            )
        )
        if count:
            db.commit()
        return count

    @staticmethod
    def _is_type_enabled(
        prefs: NotificationPreference,
        ntype: NotificationType,
    ) -> bool:
        """Respect master toggle, frequency filter, and per-type prefs.

        Admin announcements and alarm rings always pass — they are not
        discretionary reminders.
        """
        if ntype in _ALWAYS_DELIVER_TYPES:
            return True

        if not bool(getattr(prefs, "notifications_enabled", True)):
            return False

        freq = getattr(prefs, "notification_frequency", "all") or "all"
        allowed = _FREQUENCY_ALLOWED.get(freq, _FREQUENCY_ALLOWED["all"])
        if ntype not in allowed:
            return False

        field = _TYPE_PREF_FIELD.get(ntype)
        if not field:
            return True
        return bool(getattr(prefs, field, True))

    @staticmethod
    def _sound_payload(prefs: NotificationPreference) -> Dict[str, Any]:
        sound = getattr(prefs, "notification_sound", None) or "default"
        if sound not in _VALID_SOUNDS:
            sound = "default"
        return {
            "sound": sound,
            "silent": sound == "silent",
        }

    # ── Bedtime Reminders ────────────────────────────────────────

    @staticmethod
    def compute_bedtime(
        preferred_wake_time: Optional[time],
        sleep_duration_hours: float,
    ) -> Optional[time]:
        """Compute the target bedtime from wake preference and sleep goal.

        Returns ``None`` when wake time is unknown.
        """
        if preferred_wake_time is None:
            return None
        wake_minutes = preferred_wake_time.hour * 60 + preferred_wake_time.minute
        sleep_minutes = int(sleep_duration_hours * 60)
        bedtime_minutes = (wake_minutes - sleep_minutes) % (24 * 60)
        h, m = divmod(bedtime_minutes, 60)
        return time(hour=h, minute=m)

    @classmethod
    def schedule_bedtime_reminder(
        cls,
        db: Session,
        user_id: int,
    ) -> Optional[Notification]:
        """Create a bedtime reminder notification for tonight.

        Derives bedtime from the user's sleep profile and schedules the
        reminder ``bedtime_reminder_minutes_before`` minutes earlier.
        Returns ``None`` when data is insufficient or the feature is disabled.
        """
        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if not profile or not profile.preferred_wake_time:
            return None

        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.BEDTIME_REMINDER):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.BEDTIME_REMINDER]
            )
            return None

        bedtime = cls.compute_bedtime(
            profile.preferred_wake_time, profile.sleep_duration_hours
        )
        if bedtime is None:
            return None

        tz = _resolve_tz(profile.timezone)
        now_local = datetime.now(tz)

        bedtime_local = datetime.combine(now_local.date(), bedtime, tzinfo=tz)
        if bedtime_local < now_local:
            bedtime_local += timedelta(days=1)

        reminder_at = bedtime_local - timedelta(
            minutes=prefs.bedtime_reminder_minutes_before
        )
        reminder_utc = reminder_at.astimezone(timezone.utc).replace(tzinfo=None)

        bedtime_str = bedtime.strftime("%I:%M %p").lstrip("0")
        title = "Time to Wind Down 🌙"
        body = (
            f"Your target bedtime is {bedtime_str}. "
            f"Start winding down to get your {profile.sleep_duration_hours:.0f} hours of sleep!"
        )
        data = {
            "bedtime": bedtime.isoformat(),
            "wake_time": profile.preferred_wake_time.isoformat(),
            **cls._sound_payload(prefs),
        }

        # Dedup: reuse / resync the single pending bedtime reminder
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.BEDTIME_REMINDER,
                Notification.status == NotificationStatus.PENDING,
            )
            .order_by(Notification.scheduled_at.asc())
            .first()
        )
        if existing:
            existing.scheduled_at = reminder_utc
            existing.title = title
            existing.body = body
            existing.data = data
            # Collapse any accidental extra pending rows
            extras = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user_id,
                    Notification.notification_type == NotificationType.BEDTIME_REMINDER,
                    Notification.status == NotificationStatus.PENDING,
                    Notification.id != existing.id,
                )
                .all()
            )
            for extra in extras:
                extra.status = NotificationStatus.FAILED
            db.commit()
            db.refresh(existing)
            return existing

        notif = Notification(
            user_id=user_id,
            notification_type=NotificationType.BEDTIME_REMINDER,
            title=title,
            body=body,
            data=data,
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=reminder_utc,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    # ── Wake Reminders ───────────────────────────────────────────

    @classmethod
    def schedule_wake_reminders(
        cls,
        db: Session,
        user_id: int,
    ) -> List[Notification]:
        """Schedule wake reminders for all upcoming active alarms.

        Uses each alarm's ``next_trigger_at`` and the user's
        ``wake_reminder_minutes_before`` preference. Existing pending
        reminders are resynced (not duplicated) when trigger times change
        — required for recurring alarms.
        """
        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.WAKE_REMINDER):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.WAKE_REMINDER]
            )
            return []

        # Drop reminders for deleted / inactive alarms first
        cls.cancel_orphaned_wake_reminders(db, user_id)

        now_utc = _utc_naive_now()
        cutoff = now_utc + timedelta(hours=36)

        alarms = (
            db.query(Alarm)
            .filter(
                Alarm.user_id == user_id,
                Alarm.is_active.is_(True),
                Alarm.next_trigger_at.isnot(None),
                Alarm.next_trigger_at >= now_utc,
                Alarm.next_trigger_at <= cutoff,
            )
            .all()
        )

        created: List[Notification] = []
        dirty = False

        for alarm in alarms:
            reminder_at = alarm.next_trigger_at - timedelta(
                minutes=prefs.wake_reminder_minutes_before
            )
            if reminder_at <= now_utc:
                # Past — cancel any stale pending for this alarm
                cls.cancel_pending_for_alarm(db, alarm.id)
                continue

            alarm_time_str = alarm.alarm_time.strftime("%I:%M %p").lstrip("0")
            title = f"Alarm in {prefs.wake_reminder_minutes_before} min ⏰"
            body = (
                f"Your alarm \"{alarm.title}\" is set for {alarm_time_str}. "
                f"Get ready to rise and shine!"
            )
            data = {
                "alarm_id": alarm.id,
                "alarm_time": alarm.alarm_time.isoformat(),
                "alarm_title": alarm.title,
                **cls._sound_payload(prefs),
            }

            # Dedup: one pending wake reminder per alarm
            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user_id,
                    Notification.notification_type == NotificationType.WAKE_REMINDER,
                    Notification.related_alarm_id == alarm.id,
                    Notification.status == NotificationStatus.PENDING,
                )
                .order_by(Notification.id.asc())
                .first()
            )
            if existing:
                if (
                    existing.scheduled_at != reminder_at
                    or existing.title != title
                    or existing.body != body
                ):
                    existing.scheduled_at = reminder_at
                    existing.title = title
                    existing.body = body
                    existing.data = data
                    dirty = True
                # Collapse duplicates for the same alarm
                extras = (
                    db.query(Notification)
                    .filter(
                        Notification.user_id == user_id,
                        Notification.notification_type == NotificationType.WAKE_REMINDER,
                        Notification.related_alarm_id == alarm.id,
                        Notification.status == NotificationStatus.PENDING,
                        Notification.id != existing.id,
                    )
                    .all()
                )
                for extra in extras:
                    extra.status = NotificationStatus.FAILED
                    dirty = True
                continue

            notif = Notification(
                user_id=user_id,
                notification_type=NotificationType.WAKE_REMINDER,
                title=title,
                body=body,
                data=data,
                channel=NotificationChannel.PUSH,
                status=NotificationStatus.PENDING,
                scheduled_at=reminder_at,
                related_alarm_id=alarm.id,
            )
            db.add(notif)
            created.append(notif)
            dirty = True

        if dirty:
            db.commit()
            for n in created:
                db.refresh(n)
        return created

    # ── Habit Alerts ─────────────────────────────────────────────

    @classmethod
    def schedule_habit_alert(
        cls,
        db: Session,
        user_id: int,
    ) -> Optional[Notification]:
        """Create a habit alert when metrics are declining.

        Checks wake-up consistency and streak data to identify users
        who need a nudge. At most one habit alert per 24 hours.
        """
        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.HABIT_ALERT):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.HABIT_ALERT]
            )
            return None

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if not profile:
            return None

        # Dedup — at most one habit alert per 24h (pending or already sent)
        recent = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.HABIT_ALERT,
                Notification.created_at >= _utc_naive_now() - timedelta(hours=24),
            )
            .first()
        )
        if recent:
            return None

        from app.services.habit_score import calculate_habit_score_for_user, format_habit_score
        from app.services.system_settings_service import SystemSettingsService

        habit_data = calculate_habit_score_for_user(db, user_id, profile)
        habit_score = habit_data.get("habit_score", 50.0)
        breakdown = habit_data.get("breakdown", {})
        thresholds = SystemSettingsService.get_alert_thresholds(db)

        title: Optional[str] = None
        body: Optional[str] = None

        consistency = breakdown.get("wake_up_consistency", 50.0)
        snooze = breakdown.get("snooze_reduction", 50.0)
        streak_days = habit_data.get("streak_days", 0)

        if habit_score < thresholds["habit_score"]:
            title = "Your Habits Need Attention 📉"
            body = (
                f"Your habit score dropped to {format_habit_score(habit_score)}. "
                "Let's get back on track — try setting an earlier bedtime tonight."
            )
        elif consistency < thresholds["consistency"]:
            title = "Wake-Up Consistency Alert ⚠️"
            body = (
                "Your wake-up consistency has dropped. "
                "Try to wake up within 15 minutes of your alarm for the next 3 days."
            )
        elif snooze < thresholds["snooze"]:
            title = "Snooze Habits Creeping Up 😴"
            body = (
                "You've been snoozing more than usual. "
                "Challenge yourself: dismiss the alarm on the first ring tomorrow!"
            )
        elif streak_days == 0 and profile.total_alarms_dismissed > 5:
            title = "Streak Lost — Start Fresh! 🔄"
            body = (
                "Your wake-up streak was reset. "
                "That's okay! Every champion has setbacks. Start a new streak today."
            )

        if title is None:
            return None

        notif = Notification(
            user_id=user_id,
            notification_type=NotificationType.HABIT_ALERT,
            title=title,
            body=body,
            data={
                "habit_score": habit_score,
                "consistency": consistency,
                "streak_days": streak_days,
                **cls._sound_payload(prefs),
            },
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=_utc_naive_now(),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    # ── Challenge Practice Reminders ─────────────────────────────

    @classmethod
    def schedule_challenge_reminder(
        cls,
        db: Session,
        user_id: int,
    ) -> Optional[Notification]:
        """Nudge a user who has stopped practising cognitive challenges.

        Fires only after ``CHALLENGE_IDLE_DAYS`` without an attempt, and only
        for users who actually use the product (an active alarm or a prior
        attempt). At most one per ``CHALLENGE_REMINDER_COOLDOWN_HOURS``.
        """
        from app.models.alarm import AlarmChallengeLog

        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.CHALLENGE_REMINDER):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.CHALLENGE_REMINDER]
            )
            return None

        now = _utc_naive_now()
        recent = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type
                == NotificationType.CHALLENGE_REMINDER,
                Notification.status.in_(_LIVE_STATUSES),
                Notification.created_at
                >= now - timedelta(hours=CHALLENGE_REMINDER_COOLDOWN_HOURS),
            )
            .first()
        )
        if recent:
            return recent if recent.status == NotificationStatus.PENDING else None

        last_attempt = (
            db.query(func.max(AlarmChallengeLog.created_at))
            .filter(AlarmChallengeLog.user_id == user_id)
            .scalar()
        )
        if last_attempt is not None and last_attempt.tzinfo is not None:
            last_attempt = last_attempt.astimezone(timezone.utc).replace(
                tzinfo=None
            )

        # Still practising — a reminder would be noise.
        if last_attempt is not None and last_attempt >= now - timedelta(
            days=CHALLENGE_IDLE_DAYS
        ):
            return None

        if last_attempt is None:
            has_active_alarm = (
                db.query(Alarm.id)
                .filter(Alarm.user_id == user_id, Alarm.is_active.is_(True))
                .first()
                is not None
            )
            if not has_active_alarm:
                # No alarms and no history yet — nothing to remind about.
                return None
            days_idle: Optional[int] = None
            title = "Try Your First Challenge 🧩"
            body = (
                "Cognitive challenges are what make your alarm impossible to "
                "sleep through. Practise one now so tomorrow's wake-up is easy."
            )
        else:
            days_idle = max(1, (now - last_attempt).days)
            title = "Keep Your Edge Sharp 🧩"
            body = (
                f"It's been {days_idle} days since your last challenge. "
                "A quick practice round keeps your morning reflexes fast."
            )

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        # FCM stringifies every data value, so null keys are omitted entirely.
        data: Dict[str, Any] = {
            "url": "/practice",
            **cls._sound_payload(prefs),
        }
        if last_attempt is not None:
            data["days_since_last_attempt"] = days_idle
            data["last_attempt_at"] = last_attempt.isoformat()

        notif = Notification(
            user_id=user_id,
            notification_type=NotificationType.CHALLENGE_REMINDER,
            title=title,
            body=body,
            data=data,
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=_next_local_hour_utc(
                profile, CHALLENGE_REMINDER_LOCAL_HOUR
            ),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    # ── Weekly Progress Updates ──────────────────────────────────

    @classmethod
    def schedule_progress_update(
        cls,
        db: Session,
        user_id: int,
    ) -> Optional[Notification]:
        """Recap the user's real activity over the last week.

        Sent at most once per ``PROGRESS_PERIOD_DAYS`` and only when the window
        contains verified wake-ups or challenge attempts — an empty recap is
        not progress. Streak milestones and personal bests are called out.
        """
        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.PROGRESS_UPDATE):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.PROGRESS_UPDATE]
            )
            return None

        now = _utc_naive_now()
        recent = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type
                == NotificationType.PROGRESS_UPDATE,
                Notification.status.in_(_LIVE_STATUSES),
                Notification.created_at
                >= now - timedelta(days=PROGRESS_PERIOD_DAYS),
            )
            .first()
        )
        if recent:
            return recent if recent.status == NotificationStatus.PENDING else None

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if not profile:
            return None

        from app.services.dashboard_aggregations import (
            compute_challenge_performance,
            compute_wake_stats,
        )
        from app.services.habit_score import (
            calculate_habit_score_for_user,
            format_habit_score,
        )

        wake = compute_wake_stats(db, user_id, PROGRESS_PERIOD_DAYS)
        challenge = compute_challenge_performance(
            db, user_id, PROGRESS_PERIOD_DAYS
        )
        verified = int(wake.get("verified_wakes") or 0)
        attempts = int(challenge.get("total_attempts") or 0)
        if verified == 0 and attempts == 0:
            return None

        habit = calculate_habit_score_for_user(db, user_id, profile)
        habit_score = habit.get("habit_score", 0.0)
        streak_days = int(habit.get("streak_days", 0) or 0)
        best_streak = int(profile.best_streak or 0)
        accuracy = float(challenge.get("accuracy") or 0.0)

        milestone = streak_days if streak_days in STREAK_MILESTONES else None
        if milestone:
            title = f"{milestone}-Day Streak Unlocked 🏆"
        elif streak_days > 1 and streak_days >= best_streak:
            title = "New Personal Best 🥇"
        else:
            title = "Your Weekly Progress 📊"

        parts: List[str] = []
        if verified:
            parts.append(
                f"{verified} verified wake-up{'' if verified == 1 else 's'}"
            )
        if attempts:
            parts.append(
                f"{attempts} challenge{'' if attempts == 1 else 's'} "
                f"at {accuracy:.0f}% accuracy"
            )
        streak_note = f" · {streak_days}-day streak" if streak_days else ""
        body = (
            f"Last {PROGRESS_PERIOD_DAYS} days: {', '.join(parts)}. "
            f"Habit score {format_habit_score(habit_score)}{streak_note}."
        )

        data: Dict[str, Any] = {
            "period_days": PROGRESS_PERIOD_DAYS,
            "verified_wakes": verified,
            "challenge_attempts": attempts,
            "challenge_accuracy": accuracy,
            "habit_score": habit_score,
            "streak_days": streak_days,
            "best_streak": best_streak,
            "url": "/analytics",
            **cls._sound_payload(prefs),
        }
        if milestone:
            data["milestone"] = milestone

        notif = Notification(
            user_id=user_id,
            notification_type=NotificationType.PROGRESS_UPDATE,
            title=title,
            body=body,
            data=data,
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=_next_local_hour_utc(profile, PROGRESS_LOCAL_HOUR),
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    # ── Motivational Notifications ───────────────────────────────

    @classmethod
    def schedule_motivational(
        cls,
        db: Session,
        user_id: int,
    ) -> Optional[Notification]:
        """Schedule a daily motivational notification.

        Uses Gemini AI for personalized content when available, otherwise
        falls back to curated static messages. At most one per ~20 hours.
        """
        prefs = cls._get_or_create_preferences(db, user_id)
        if not cls._is_type_enabled(prefs, NotificationType.MOTIVATIONAL):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.MOTIVATIONAL]
            )
            return None

        # Dedup — pending or recently delivered (ignore FAILED cancels)
        recent = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.MOTIVATIONAL,
                Notification.status.in_([
                    NotificationStatus.PENDING,
                    NotificationStatus.SENT,
                    NotificationStatus.DELIVERED,
                    NotificationStatus.READ,
                ]),
                Notification.created_at >= _utc_naive_now() - timedelta(hours=20),
            )
            .first()
        )
        if recent:
            return recent if recent.status == NotificationStatus.PENDING else None

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )

        tz = _resolve_tz(profile.timezone if profile else None)
        now_local = datetime.now(tz)

        if prefs.motivational_time:
            sched_local = datetime.combine(
                now_local.date(), prefs.motivational_time, tzinfo=tz
            )
            if sched_local < now_local:
                sched_local += timedelta(days=1)
        else:
            sched_local = datetime.combine(
                now_local.date(), time(8, 0), tzinfo=tz
            )
            if sched_local < now_local:
                sched_local += timedelta(days=1)

        sched_utc = sched_local.astimezone(timezone.utc).replace(tzinfo=None)

        title, body = cls._generate_motivational_content(db, user_id, profile)

        notif = Notification(
            user_id=user_id,
            notification_type=NotificationType.MOTIVATIONAL,
            title=title,
            body=body,
            data={
                "source": "ai" if cls._gemini_available() else "static",
                **cls._sound_payload(prefs),
            },
            channel=NotificationChannel.PUSH,
            status=NotificationStatus.PENDING,
            scheduled_at=sched_utc,
        )
        db.add(notif)
        db.commit()
        db.refresh(notif)
        return notif

    @classmethod
    def _generate_motivational_content(
        cls,
        db: Session,
        user_id: int,
        profile: Optional[UserProfile],
    ) -> Tuple[str, str]:
        """Generate motivational title + body.

        Tries Gemini AI first; falls back to static messages.
        """
        if cls._gemini_available() and profile:
            try:
                return cls._gemini_motivational(db, user_id, profile)
            except Exception as exc:
                logger.warning(
                    "Gemini motivational generation failed for user %d: %s",
                    user_id, exc,
                )

        msg = random.choice(_MOTIVATIONAL_MESSAGES)
        return msg["title"], msg["body"]

    @staticmethod
    def _gemini_available() -> bool:
        """Check if Gemini AI is configured."""
        from app.core.config import settings
        return bool(settings.GEMINI_API_KEY)

    @classmethod
    def _gemini_motivational(
        cls,
        db: Session,
        user_id: int,
        profile: UserProfile,
    ) -> Tuple[str, str]:
        """Generate a personalised motivational message via Gemini AI."""
        from app.core.config import settings
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)

        from app.services.habit_score import calculate_habit_score_for_user, format_habit_score

        habit_data = calculate_habit_score_for_user(db, user_id, profile)
        habit_score = habit_data.get("habit_score", 50.0)
        streak_days = habit_data.get("streak_days", 0)
        breakdown = habit_data.get("breakdown", {})

        prompt = (
            "You are a friendly wellness coach for a wake-up habit app. "
            "Generate a short motivational notification for the user.\n\n"
            f"User stats:\n"
            f"- Habit score: {format_habit_score(habit_score)}\n"
            f"- Wake-up streak: {streak_days} days\n"
            f"- Wake consistency: {breakdown.get('wake_up_consistency', 50):.0f}%\n"
            f"- Snooze reduction: {breakdown.get('snooze_reduction', 50):.0f}%\n"
            f"- Sleep adherence: {breakdown.get('sleep_adherence', 50):.0f}%\n\n"
            "Respond with ONLY a JSON object: {\"title\": \"...\", \"body\": \"...\"}\n"
            "Title should be ≤ 50 chars with one emoji. Body should be ≤ 160 chars.\n"
            "Be encouraging and specific to their stats."
        )

        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()

        import json
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        data = json.loads(text)
        title = str(data.get("title", "Keep Going! 💪"))[:60]
        body = str(data.get("body", "Your habits are shaping a better you."))[:200]
        return title, body

    # ── Delivery helpers ─────────────────────────────────────────

    @staticmethod
    def _max_push_attempts() -> int:
        return max(1, int(settings.NOTIFICATION_MAX_PUSH_ATTEMPTS or 1))

    @classmethod
    def _schedule_retry(
        cls,
        notif: Notification,
        now_utc: datetime,
        attempts: int,
    ) -> bool:
        """Arm the next delivery retry after ``attempts`` failed tries.

        Returns ``False`` when the attempt budget is spent, in which case the
        notification is left with its failure reason and no further retries.
        """
        if attempts >= cls._max_push_attempts():
            notif.next_retry_at = None
            return False

        base = max(30, int(settings.NOTIFICATION_RETRY_BACKOFF_SECONDS or 300))
        delay = min(base * (2 ** max(0, attempts - 1)), _MAX_RETRY_DELAY_SECONDS)
        notif.next_retry_at = now_utc + timedelta(seconds=delay)
        return True

    @classmethod
    def _attempt_push(
        cls,
        db: Session,
        notif: Notification,
        payload_data: Dict[str, Any],
        now_utc: datetime,
    ) -> Dict[str, Any]:
        """Push ``notif`` via FCM and fold the outcome into its delivery fields."""
        notif.push_attempts = int(notif.push_attempts or 0) + 1

        result = FCMService.send_to_user_devices(
            db, notif.user_id, notif.title, notif.body, payload_data
        )
        delivered = result.get("success_count", 0) > 0

        if delivered:
            notif.delivered_at = now_utc
            notif.next_retry_at = None
            notif.last_error = None
        elif result.get("no_devices"):
            # Nothing to deliver to yet — the in-app feed still carries it and
            # a future token registration does not resurrect an old push.
            notif.next_retry_at = None
            notif.last_error = None
            payload_data["push_skipped_reason"] = "no_registered_devices"
        else:
            errors = result.get("errors") or []
            notif.last_error = _truncate_error(
                "; ".join(errors) or "push delivery failed"
            )
            if result.get("retryable") and cls._schedule_retry(
                notif, now_utc, notif.push_attempts
            ):
                logger.warning(
                    "Push for notification %s failed (attempt %d/%d); "
                    "retrying at %s: %s",
                    notif.id,
                    notif.push_attempts,
                    cls._max_push_attempts(),
                    notif.next_retry_at,
                    notif.last_error,
                )
            else:
                notif.next_retry_at = None
                logger.error(
                    "Push for notification %s permanently failed after %d "
                    "attempt(s): %s",
                    notif.id,
                    notif.push_attempts,
                    notif.last_error,
                )

        payload_data["push_delivered"] = delivered
        if result.get("invalid_tokens"):
            payload_data["invalid_tokens_retired"] = len(
                result["invalid_tokens"]
            )
        return result

    @staticmethod
    def _recipient_email(db: Session, user_id: int) -> Optional[str]:
        """Return the deliverable email address for a user, if any."""
        from app.models.user import User

        row = (
            db.query(User.email, User.is_active)
            .filter(User.id == user_id)
            .first()
        )
        if not row or not row[0] or not row[1]:
            return None
        return str(row[0])

    @staticmethod
    def _email_bodies(notif: Notification) -> Tuple[str, str]:
        """Render plain-text and HTML bodies for an emailed notification."""
        text = (
            f"{notif.title}\n\n"
            f"{notif.body}\n\n"
            "— Intelligent Cognitive Alarm\n"
            "Manage these emails under Profile → Notification preferences."
        )
        html = (
            f"<h2 style=\"margin:0 0 12px\">{notif.title}</h2>"
            f"<p style=\"margin:0 0 16px;font-size:15px\">{notif.body}</p>"
            "<hr style=\"border:none;border-top:1px solid #ddd\">"
            "<p style=\"font-size:12px;color:#666\">Intelligent Cognitive Alarm"
            " — manage these emails under Profile → Notification preferences."
            "</p>"
        )
        return text, html

    @classmethod
    def _deliver_email(
        cls,
        db: Session,
        notif: Notification,
        now_utc: datetime,
    ) -> Dict[str, Any]:
        """Send ``notif`` over SMTP.

        Returns ``{"delivered": bool, "reason": str | None,
        "retryable": bool}``. Never raises — SMTP transport errors are logged
        and reported so the caller decides the notification's fate.
        """
        from app.services.email_service import EmailService

        if not EmailService.is_configured():
            return {
                "delivered": False,
                "reason": "email_not_configured",
                "retryable": False,
            }

        to_email = cls._recipient_email(db, notif.user_id)
        if not to_email:
            return {
                "delivered": False,
                "reason": "no_recipient_address",
                "retryable": False,
            }

        notif.email_attempts = int(notif.email_attempts or 0) + 1
        text_body, html_body = cls._email_bodies(notif)
        try:
            accepted = EmailService.send_email(
                to_email=to_email,
                subject=notif.title,
                text_body=text_body,
                html_body=html_body,
            )
        except Exception as exc:
            logger.error(
                "Email delivery failed for notification %s (user %d): %s",
                notif.id,
                notif.user_id,
                exc,
                exc_info=True,
            )
            return {
                "delivered": False,
                "reason": _truncate_error(f"smtp_error: {exc}"),
                "retryable": True,
            }

        if accepted:
            notif.delivered_at = notif.delivered_at or now_utc
            return {"delivered": True, "reason": None, "retryable": False}
        return {
            "delivered": False,
            "reason": "smtp_rejected",
            "retryable": True,
        }

    # ── Notification Queue Processing ────────────────────────────

    @classmethod
    def process_pending_notifications(
        cls,
        db: Session,
        *,
        only_types: Optional[Sequence[NotificationType]] = None,
        exclude_types: Optional[Sequence[NotificationType]] = None,
    ) -> Dict[str, int]:
        """Process all pending notifications whose scheduled_at has passed.

        Enforces preferences, quiet hours, push_enabled, and cancels
        orphaned wake reminders before dispatch.

        ``only_types`` / ``exclude_types`` let independent scheduler jobs own
        disjoint slices of the queue so two jobs can never dispatch the same
        row concurrently.
        """
        now_utc = _utc_naive_now()

        query = db.query(Notification).filter(
            Notification.status == NotificationStatus.PENDING,
            Notification.scheduled_at <= now_utc,
            # A row awaiting a backoff window is not due yet.
            or_(
                Notification.next_retry_at.is_(None),
                Notification.next_retry_at <= now_utc,
            ),
        )
        if only_types:
            query = query.filter(
                Notification.notification_type.in_(list(only_types))
            )
        if exclude_types:
            query = query.filter(
                Notification.notification_type.notin_(list(exclude_types))
            )

        pending = query.order_by(Notification.scheduled_at).limit(100).all()

        sent_count = 0
        failed_count = 0
        skipped_quiet = 0
        delivered_count = 0
        emailed_count = 0
        retry_count = 0

        # Prefetch prefs per user to avoid N+1
        prefs_cache: Dict[int, NotificationPreference] = {}

        from app.services.system_settings_service import SystemSettingsService

        global_push = SystemSettingsService.is_push_globally_enabled(db)
        global_email = SystemSettingsService.is_email_globally_enabled(db)

        for notif in pending:
            prefs = prefs_cache.get(notif.user_id)
            if prefs is None:
                prefs = cls._get_or_create_preferences(db, notif.user_id)
                prefs_cache[notif.user_id] = prefs

            # Disabled type → cancel (never send)
            if not cls._is_type_enabled(prefs, notif.notification_type):
                notif.status = NotificationStatus.FAILED
                notif.last_error = "type_disabled_by_user_preference"
                notif.next_retry_at = None
                failed_count += 1
                continue

            # Global channel kill-switches
            if (
                notif.channel == NotificationChannel.PUSH
                and not global_push
            ):
                # Still deliver to in-app feed by marking sent without FCM
                notif.status = NotificationStatus.SENT
                notif.sent_at = now_utc
                notif.next_retry_at = None
                payload = dict(notif.data or {})
                payload["push_delivered"] = False
                payload["push_skipped_reason"] = "global_push_disabled"
                notif.data = payload
                sent_count += 1
                continue

            if (
                notif.channel == NotificationChannel.EMAIL
                and not global_email
            ):
                notif.status = NotificationStatus.FAILED
                notif.last_error = "global_email_disabled"
                notif.next_retry_at = None
                failed_count += 1
                continue

            # Orphaned / inactive alarm reminder or ring → cancel
            if (
                notif.notification_type
                in (
                    NotificationType.WAKE_REMINDER,
                    NotificationType.ALARM_TRIGGER,
                )
                and notif.related_alarm_id is not None
            ):
                alarm = (
                    db.query(Alarm)
                    .filter(Alarm.id == notif.related_alarm_id)
                    .first()
                )
                if alarm is None or not alarm.is_active:
                    notif.status = NotificationStatus.FAILED
                    notif.last_error = "alarm_deleted_or_inactive"
                    notif.next_retry_at = None
                    failed_count += 1
                    continue

                # The alarm already moved on (dismissed, snoozed, rescheduled)
                # — ringing for a superseded instant would be a phantom alarm.
                if (
                    notif.notification_type == NotificationType.ALARM_TRIGGER
                    and alarm.next_trigger_at != notif.scheduled_at
                ):
                    notif.status = NotificationStatus.FAILED
                    notif.last_error = "alarm_trigger_superseded"
                    notif.next_retry_at = None
                    failed_count += 1
                    continue

            # Quiet hours — leave PENDING for later (rings & announcements
            # are never silenced)
            if (
                notif.notification_type not in _ALWAYS_DELIVER_TYPES
                and cls._is_in_quiet_hours(db, notif.user_id, prefs=prefs)
            ):
                skipped_quiet += 1
                continue

            # Build payload with stable id for client-side dedup tags
            payload_data = dict(notif.data or {})
            payload_data["notification_id"] = str(notif.id)
            payload_data["notification_type"] = notif.notification_type.value
            payload_data.update(cls._sound_payload(prefs))

            push_ok = False
            always_deliver = notif.notification_type in _ALWAYS_DELIVER_TYPES
            user_push_ok = (
                prefs.push_enabled
                and bool(getattr(prefs, "notifications_enabled", True))
            ) or always_deliver

            # ── Email-channel notifications are delivered by SMTP only ──
            if notif.channel == NotificationChannel.EMAIL:
                outcome = cls._deliver_email(db, notif, now_utc)
                if outcome["delivered"]:
                    payload_data["email_delivered"] = True
                    notif.data = payload_data
                    notif.status = NotificationStatus.DELIVERED
                    notif.sent_at = now_utc
                    notif.last_error = None
                    sent_count += 1
                    delivered_count += 1
                    emailed_count += 1
                    continue

                payload_data["email_delivered"] = False
                notif.data = payload_data
                notif.last_error = _truncate_error(outcome["reason"])
                if outcome["retryable"] and cls._schedule_retry(
                    notif, now_utc, notif.email_attempts
                ):
                    # Stays PENDING; the queue honours next_retry_at on re-read.
                    retry_count += 1
                else:
                    notif.next_retry_at = None
                    notif.status = NotificationStatus.FAILED
                    failed_count += 1
                    logger.error(
                        "Email notification %s for user %d could not be "
                        "delivered: %s",
                        notif.id,
                        notif.user_id,
                        notif.last_error,
                    )
                continue

            if (
                notif.channel == NotificationChannel.PUSH
                and global_push
                and user_push_ok
            ):
                result = cls._attempt_push(db, notif, payload_data, now_utc)
                push_ok = result.get("success_count", 0) > 0
                if notif.next_retry_at is not None:
                    retry_count += 1

            payload_data.setdefault("push_delivered", push_ok)

            # Mirror to email for users who opted the channel in.
            if (
                global_email
                and bool(getattr(prefs, "email_notifications_enabled", False))
                and bool(getattr(prefs, "notifications_enabled", True))
            ):
                mirror = cls._deliver_email(db, notif, now_utc)
                payload_data["email_delivered"] = mirror["delivered"]
                if mirror["delivered"]:
                    emailed_count += 1
                elif mirror["reason"] != "email_not_configured":
                    logger.warning(
                        "Email copy of notification %s for user %d was not "
                        "delivered: %s",
                        notif.id,
                        notif.user_id,
                        mirror["reason"],
                    )

            # Always promote for the in-app feed (local / FCM / both). Push
            # success upgrades the row to DELIVERED so history distinguishes
            # "queued and shown" from "accepted by Firebase".
            notif.data = payload_data
            notif.status = (
                NotificationStatus.DELIVERED if push_ok else NotificationStatus.SENT
            )
            notif.sent_at = now_utc
            sent_count += 1
            if push_ok:
                delivered_count += 1

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error(
                "Failed to commit notification status updates for %d "
                "notification(s); they stay PENDING and will be retried.",
                len(pending),
                exc_info=True,
            )
            return {
                "sent": 0,
                "failed": 0,
                "quiet_hours_skipped": 0,
                "delivered": 0,
                "emailed": 0,
                "retry_scheduled": 0,
                "commit_failed": True,
            }

        if sent_count or failed_count or skipped_quiet:
            logger.info(
                "Notification queue: %d dispatched (%d push/email delivered, "
                "%d emailed), %d cancelled, %d quiet-hours, %d retry-scheduled",
                sent_count,
                delivered_count,
                emailed_count,
                failed_count,
                skipped_quiet,
                retry_count,
            )

        return {
            "sent": sent_count,
            "failed": failed_count,
            "quiet_hours_skipped": skipped_quiet,
            "delivered": delivered_count,
            "emailed": emailed_count,
            "retry_scheduled": retry_count,
        }

    # ── Failed-delivery Retry Sweep ──────────────────────────────

    @classmethod
    def retry_failed_deliveries(cls, db: Session) -> Dict[str, int]:
        """Re-attempt pushes that failed transiently.

        Only notifications already dispatched to the in-app feed are touched,
        so a retry can upgrade ``SENT`` to ``DELIVERED`` but can never hide a
        notification the user has already seen. Notifications still ``PENDING``
        (for example an email awaiting its next try) are left to the main queue.
        """
        now_utc = _utc_naive_now()
        max_attempts = cls._max_push_attempts()

        due = (
            db.query(Notification)
            .filter(
                Notification.next_retry_at.isnot(None),
                Notification.next_retry_at <= now_utc,
                Notification.channel == NotificationChannel.PUSH,
                Notification.status.in_(
                    [NotificationStatus.SENT, NotificationStatus.READ]
                ),
                Notification.push_attempts < max_attempts,
            )
            .order_by(Notification.next_retry_at)
            .limit(100)
            .all()
        )

        if not due:
            return {"attempted": 0, "delivered": 0, "gave_up": 0}

        from app.services.system_settings_service import SystemSettingsService

        global_push = SystemSettingsService.is_push_globally_enabled(db)
        prefs_cache: Dict[int, NotificationPreference] = {}

        attempted = 0
        delivered = 0
        gave_up = 0

        for notif in due:
            prefs = prefs_cache.get(notif.user_id)
            if prefs is None:
                prefs = cls._get_or_create_preferences(db, notif.user_id)
                prefs_cache[notif.user_id] = prefs

            always_deliver = notif.notification_type in _ALWAYS_DELIVER_TYPES
            user_push_ok = (
                prefs.push_enabled
                and bool(getattr(prefs, "notifications_enabled", True))
            ) or always_deliver

            # Preferences may have changed since the first attempt — abandon
            # the retry rather than pushing something now opted out of.
            if not global_push or not user_push_ok:
                notif.next_retry_at = None
                notif.last_error = "retry_abandoned_push_disabled"
                gave_up += 1
                continue

            payload_data = dict(notif.data or {})
            payload_data["notification_id"] = str(notif.id)
            payload_data["notification_type"] = notif.notification_type.value
            payload_data["retry_attempt"] = int(notif.push_attempts or 0) + 1
            payload_data.update(cls._sound_payload(prefs))

            attempted += 1
            result = cls._attempt_push(db, notif, payload_data, now_utc)
            notif.data = payload_data

            if result.get("success_count", 0) > 0:
                delivered += 1
                if notif.status == NotificationStatus.SENT:
                    notif.status = NotificationStatus.DELIVERED
            elif notif.next_retry_at is None:
                gave_up += 1

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error(
                "Failed to commit push retry results for %d notification(s).",
                len(due),
                exc_info=True,
            )
            return {"attempted": 0, "delivered": 0, "gave_up": 0}

        logger.info(
            "Push retry sweep: %d attempted, %d delivered, %d gave up.",
            attempted,
            delivered,
            gave_up,
        )
        return {
            "attempted": attempted,
            "delivered": delivered,
            "gave_up": gave_up,
        }

    # ── Upcoming pending (local client scheduling) ───────────────

    @staticmethod
    def get_upcoming_pending(
        db: Session,
        user_id: int,
        within_hours: int = 24,
    ) -> List[Notification]:
        """Return pending notifications due within the next N hours.

        Used by web/PWA clients to schedule local notifications when
        FCM background delivery is unavailable.
        """
        now_utc = _utc_naive_now()
        cutoff = now_utc + timedelta(hours=within_hours)
        return (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.status == NotificationStatus.PENDING,
                Notification.scheduled_at.isnot(None),
                Notification.scheduled_at <= cutoff,
            )
            .order_by(Notification.scheduled_at.asc())
            .all()
        )

    # ── In-App Feed / Queries ────────────────────────────────────

    @staticmethod
    def get_user_notifications(
        db: Session,
        user_id: int,
        page: int = 1,
        per_page: int = 20,
        notification_type: Optional[NotificationType] = None,
        unread_only: bool = False,
    ) -> Dict[str, Any]:
        """Return paginated notification feed for a user."""
        query = db.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.status.in_([
                NotificationStatus.SENT,
                NotificationStatus.DELIVERED,
                NotificationStatus.READ,
            ]),
        )

        if notification_type:
            query = query.filter(
                Notification.notification_type == notification_type
            )

        if unread_only:
            query = query.filter(Notification.read_at.is_(None))

        total = query.count()
        unread_count = (
            db.query(func.count(Notification.id))
            .filter(
                Notification.user_id == user_id,
                Notification.status.in_([
                    NotificationStatus.SENT,
                    NotificationStatus.DELIVERED,
                ]),
                Notification.read_at.is_(None),
            )
            .scalar()
        ) or 0

        notifications = (
            query.order_by(Notification.scheduled_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return {
            "notifications": notifications,
            "total": total,
            "unread_count": unread_count,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_unread_count(db: Session, user_id: int) -> int:
        """Return the number of unread notifications."""
        return (
            db.query(func.count(Notification.id))
            .filter(
                Notification.user_id == user_id,
                Notification.status.in_([
                    NotificationStatus.SENT,
                    NotificationStatus.DELIVERED,
                ]),
                Notification.read_at.is_(None),
            )
            .scalar()
        ) or 0

    @staticmethod
    def mark_read(
        db: Session,
        user_id: int,
        notification_ids: List[int],
    ) -> int:
        """Mark notifications as read. Returns count of updated rows."""
        now_utc = _utc_naive_now()
        count = (
            db.query(Notification)
            .filter(
                Notification.id.in_(notification_ids),
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .update(
                {
                    Notification.status: NotificationStatus.READ,
                    Notification.read_at: now_utc,
                },
                synchronize_session="fetch",
            )
        )
        db.commit()
        return count

    # ── Preferences ──────────────────────────────────────────────

    @staticmethod
    def _get_or_create_preferences(
        db: Session, user_id: int
    ) -> NotificationPreference:
        """Get or lazily create default notification preferences."""
        prefs = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .first()
        )
        if prefs is None:
            prefs = NotificationPreference(user_id=user_id)
            db.add(prefs)
            db.commit()
            db.refresh(prefs)
        return prefs

    @staticmethod
    def get_preferences(
        db: Session, user_id: int
    ) -> NotificationPreference:
        """Get notification preferences, creating defaults if needed."""
        return NotificationService._get_or_create_preferences(db, user_id)

    @classmethod
    def update_preferences(
        cls,
        db: Session,
        user_id: int,
        updates: Dict[str, Any],
    ) -> NotificationPreference:
        """Apply partial updates to notification preferences.

        Disabling a type / master toggle / frequency filter cancels affected
        pending notifications immediately. Changing reminder lead times or
        re-enabling types triggers an immediate reschedule.
        """
        prefs = cls._get_or_create_preferences(db, user_id)

        # Normalize enum-like values to plain strings for ORM storage.
        # Explicit null is allowed only for nullable time fields (quiet hours).
        _NULLABLE_CLEAR_FIELDS = {
            "quiet_hours_start",
            "quiet_hours_end",
            "motivational_time",
        }
        normalized: Dict[str, Any] = {}
        for field, value in updates.items():
            if value is None:
                if field in _NULLABLE_CLEAR_FIELDS:
                    normalized[field] = None
                continue
            if hasattr(value, "value"):
                value = value.value
            if field == "notification_sound":
                value = str(value).lower()
                if value not in _VALID_SOUNDS:
                    continue
            if field == "notification_frequency":
                value = str(value).lower()
                if value not in _VALID_FREQUENCIES:
                    continue
            normalized[field] = value

        disabled_types: List[NotificationType] = []
        reschedule_wake = False
        reschedule_bedtime = False
        reschedule_motivational = False
        master_disabled = False
        master_enabled = False
        frequency_changed = False

        for field, value in normalized.items():
            if not hasattr(prefs, field):
                continue
            old = getattr(prefs, field)
            setattr(prefs, field, value)

            if field == "notifications_enabled":
                if value is False:
                    master_disabled = True
                elif value is True and old is False:
                    master_enabled = True
            elif field == "notification_frequency" and value != old:
                frequency_changed = True
            elif field == "bedtime_reminder_enabled" and value is False:
                disabled_types.append(NotificationType.BEDTIME_REMINDER)
            elif field == "wake_reminder_enabled" and value is False:
                disabled_types.append(NotificationType.WAKE_REMINDER)
            elif field == "habit_alerts_enabled" and value is False:
                disabled_types.append(NotificationType.HABIT_ALERT)
            elif field == "challenge_reminders_enabled" and value is False:
                disabled_types.append(NotificationType.CHALLENGE_REMINDER)
            elif field == "progress_updates_enabled" and value is False:
                disabled_types.append(NotificationType.PROGRESS_UPDATE)
            elif field == "motivational_enabled" and value is False:
                disabled_types.append(NotificationType.MOTIVATIONAL)
            elif field == "wake_reminder_minutes_before" and value != old:
                reschedule_wake = True
            elif field == "bedtime_reminder_minutes_before" and value != old:
                reschedule_bedtime = True
            elif field == "motivational_time" and value != old:
                # Cancel pending so next schedule rebuilds at new time
                disabled_types.append(NotificationType.MOTIVATIONAL)
                reschedule_motivational = True
            elif field == "notification_sound" and value != old:
                # Sound is applied at dispatch / next schedule — resync pending
                # payloads by forcing a wake/bedtime rebuild when those are on.
                if cls._is_type_enabled(prefs, NotificationType.WAKE_REMINDER):
                    reschedule_wake = True
                if cls._is_type_enabled(prefs, NotificationType.BEDTIME_REMINDER):
                    reschedule_bedtime = True
                if cls._is_type_enabled(prefs, NotificationType.MOTIVATIONAL):
                    reschedule_motivational = True

        db.commit()
        db.refresh(prefs)

        if master_disabled:
            cls.cancel_pending_by_types(db, user_id, _USER_CANCELLABLE_TYPES)
            return prefs

        if frequency_changed:
            # Cancel types no longer allowed under the new frequency filter
            for ntype in _ALL_NOTIFICATION_TYPES:
                if not cls._is_type_enabled(prefs, ntype):
                    disabled_types.append(ntype)
            # Rebuild allowed reminders immediately
            if cls._is_type_enabled(prefs, NotificationType.WAKE_REMINDER):
                reschedule_wake = True
            if cls._is_type_enabled(prefs, NotificationType.BEDTIME_REMINDER):
                reschedule_bedtime = True
            if cls._is_type_enabled(prefs, NotificationType.MOTIVATIONAL):
                reschedule_motivational = True

        if master_enabled:
            reschedule_wake = True
            reschedule_bedtime = True
            reschedule_motivational = True

        if disabled_types:
            unique_types = list(dict.fromkeys(disabled_types))
            cls.cancel_pending_by_types(db, user_id, unique_types)

        if reschedule_wake and cls._is_type_enabled(
            prefs, NotificationType.WAKE_REMINDER
        ):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.WAKE_REMINDER]
            )
            cls.schedule_wake_reminders(db, user_id)

        if reschedule_bedtime and cls._is_type_enabled(
            prefs, NotificationType.BEDTIME_REMINDER
        ):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.BEDTIME_REMINDER]
            )
            cls.schedule_bedtime_reminder(db, user_id)

        if reschedule_motivational and cls._is_type_enabled(
            prefs, NotificationType.MOTIVATIONAL
        ):
            cls.cancel_pending_by_types(
                db, user_id, [NotificationType.MOTIVATIONAL]
            )
            cls.schedule_motivational(db, user_id)

        # Re-enable path for individual type toggles that flipped True
        if (
            normalized.get("bedtime_reminder_enabled") is True
            and not reschedule_bedtime
            and cls._is_type_enabled(prefs, NotificationType.BEDTIME_REMINDER)
        ):
            cls.schedule_bedtime_reminder(db, user_id)
        if (
            normalized.get("wake_reminder_enabled") is True
            and not reschedule_wake
            and cls._is_type_enabled(prefs, NotificationType.WAKE_REMINDER)
        ):
            cls.schedule_wake_reminders(db, user_id)
        if (
            normalized.get("habit_alerts_enabled") is True
            and cls._is_type_enabled(prefs, NotificationType.HABIT_ALERT)
        ):
            cls.schedule_habit_alert(db, user_id)
        if (
            normalized.get("challenge_reminders_enabled") is True
            and cls._is_type_enabled(prefs, NotificationType.CHALLENGE_REMINDER)
        ):
            cls.schedule_challenge_reminder(db, user_id)
        if (
            normalized.get("progress_updates_enabled") is True
            and cls._is_type_enabled(prefs, NotificationType.PROGRESS_UPDATE)
        ):
            cls.schedule_progress_update(db, user_id)
        if (
            normalized.get("motivational_enabled") is True
            and not reschedule_motivational
            and cls._is_type_enabled(prefs, NotificationType.MOTIVATIONAL)
        ):
            cls.schedule_motivational(db, user_id)

        return prefs

    # ── Device Tokens ────────────────────────────────────────────

    @staticmethod
    def register_device_token(
        db: Session,
        user_id: int,
        fcm_token: str,
        device_type: str = "web",
        device_name: Optional[str] = None,
    ) -> UserDeviceToken:
        """Register or reactivate an FCM device token."""
        existing = (
            db.query(UserDeviceToken)
            .filter(UserDeviceToken.fcm_token == fcm_token)
            .first()
        )

        if existing:
            existing.user_id = user_id
            existing.is_active = True
            existing.device_name = device_name or existing.device_name
            try:
                existing.device_type = device_type
            except Exception:
                pass
            db.commit()
            db.refresh(existing)
            return existing

        token = UserDeviceToken(
            user_id=user_id,
            fcm_token=fcm_token,
            device_type=device_type,
            device_name=device_name,
            is_active=True,
        )
        db.add(token)
        db.commit()
        db.refresh(token)
        return token

    @staticmethod
    def remove_device_token(db: Session, user_id: int, fcm_token: str) -> bool:
        """Deactivate a device token. Returns True if found."""
        token = (
            db.query(UserDeviceToken)
            .filter(
                UserDeviceToken.user_id == user_id,
                UserDeviceToken.fcm_token == fcm_token,
            )
            .first()
        )
        if token:
            token.is_active = False
            db.commit()
            return True
        return False

    # ── Quiet Hours ──────────────────────────────────────────────

    @classmethod
    def _is_in_quiet_hours(
        cls,
        db: Session,
        user_id: int,
        prefs: Optional[NotificationPreference] = None,
    ) -> bool:
        """Check if the current local time falls in quiet hours."""
        if prefs is None:
            prefs = (
                db.query(NotificationPreference)
                .filter(NotificationPreference.user_id == user_id)
                .first()
            )
        if not prefs or not prefs.quiet_hours_start or not prefs.quiet_hours_end:
            return False

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        tz = _resolve_tz(profile.timezone if profile else None)
        now_local = datetime.now(tz).time()

        start = prefs.quiet_hours_start
        end = prefs.quiet_hours_end

        if start <= end:
            return start <= now_local <= end
        # Wraps midnight (e.g. 22:00 – 07:00)
        return now_local >= start or now_local <= end
