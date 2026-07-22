"""
Smart Adaptive Alarm scheduling.

Computes the next wall-clock ring time for ``AlarmType.SMART_ADAPTIVE`` from
existing behavioral signals (habit score, wake consistency, snooze history,
sleep schedule). Daily / weekday / weekend / one-time scheduling is unchanged.

Without enough wake history the adapted time falls back to the sleep-schedule
preferred wake (or the alarm's configured time).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from sqlalchemy.orm import Session

from app.models.alarm import Alarm
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.behavioral_analytics_service import BehavioralAnalyticsService
from app.services.habit_score import calculate_habit_score_for_user

# How far the adapted ring may move from the base target
MAX_EARLIER_MINUTES = 45
MAX_LATER_MINUTES = 15

# Need at least this many verified wakes before applying history-based offsets
MIN_VERIFIED_WAKES = 2

# Lookback window for snooze / wake analytics used in adaptation
LOOKBACK_DAYS = 30

# Fraction of average snooze delay to pull the ring earlier
SNOOZE_COMPENSATION_FACTOR = 0.6


class AdaptiveSchedulingService:
    """Derive the next local trigger datetime for a Smart Adaptive alarm."""

    @classmethod
    def compute_next_local_trigger(
        cls,
        db: Session,
        user_id: int,
        alarm: Alarm,
        now_local: datetime,
        tz: ZoneInfo,
    ) -> datetime:
        """Return the next aware local datetime when this adaptive alarm should ring."""
        adapted = cls.compute_adapted_alarm_time(db, user_id, alarm)
        local_dt = datetime.combine(now_local.date(), adapted, tzinfo=tz)
        if local_dt > now_local:
            return local_dt
        return local_dt + timedelta(days=1)

    @classmethod
    def compute_adapted_alarm_time(
        cls,
        db: Session,
        user_id: int,
        alarm: Alarm,
    ) -> time:
        """Return the adapted wall-clock time (HH:MM:SS) for the next ring."""
        profile = (
            db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        )
        base_minutes = cls._base_target_minutes(alarm, profile)
        signals = cls._gather_signals(db, user_id, alarm, profile, base_minutes)
        offset = cls._offset_from_signals(signals)
        adapted = (base_minutes + offset) % (24 * 60)
        return cls._minutes_to_time(adapted)

    @classmethod
    def explain_adaptation(
        cls,
        db: Session,
        user_id: int,
        alarm: Alarm,
    ) -> Dict[str, Any]:
        """Debug-friendly breakdown of the adaptation (for tests / introspection)."""
        profile = (
            db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        )
        base_minutes = cls._base_target_minutes(alarm, profile)
        signals = cls._gather_signals(db, user_id, alarm, profile, base_minutes)
        offset = cls._offset_from_signals(signals)
        adapted = (base_minutes + offset) % (24 * 60)
        return {
            "base_time": BehavioralAnalyticsService._minutes_to_hhmm(base_minutes),
            "adapted_time": BehavioralAnalyticsService._minutes_to_hhmm(adapted),
            "offset_minutes": offset,
            "signals": signals,
        }

    # ── Internals ─────────────────────────────────────────────────────

    @classmethod
    def _base_target_minutes(
        cls,
        alarm: Alarm,
        profile: Optional[UserProfile],
    ) -> float:
        """Prefer sleep-schedule wake goal; fall back to the alarm's set time."""
        preferred = BehavioralAnalyticsService._preferred_wake_minutes(profile)
        if preferred is not None:
            return float(preferred)
        t = alarm.alarm_time
        return float(t.hour * 60 + t.minute + (t.second or 0) / 60.0)

    @classmethod
    def _gather_signals(
        cls,
        db: Session,
        user_id: int,
        alarm: Alarm,
        profile: Optional[UserProfile],
        base_minutes: float,
    ) -> Dict[str, Any]:
        window_start = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        snooze_df = BehavioralAnalyticsService._load_snooze_df(
            db, user_id, window_start
        )
        wake_df = BehavioralAnalyticsService._load_wake_df(db, user_id, window_start)

        snooze = BehavioralAnalyticsService.analyze_snooze_pattern(snooze_df, wake_df)
        wake = BehavioralAnalyticsService.analyze_wake_consistency(
            wake_df, base_minutes, profile
        )
        sleep = BehavioralAnalyticsService.analyze_sleep_adherence(
            wake_df, base_minutes, profile
        )

        if profile is not None:
            habit = calculate_habit_score_for_user(db, user_id, profile)
            habit_score = float(habit.get("habit_score", 50.0))
            breakdown = habit.get("breakdown") or {}
        else:
            habit_score = 50.0
            breakdown = {}

        # Mean wake in the user's local timezone (analytics store UTC wall minutes)
        user_tz = cls._resolve_tz(
            getattr(profile, "timezone", None) if profile else None
        )
        local_wake_minutes = cls._local_verified_wake_minutes(
            db, user_id, window_start, user_tz
        )
        mean_minutes = (
            float(np.mean(local_wake_minutes)) if local_wake_minutes else None
        )
        verified_local = len(local_wake_minutes)

        return {
            "base_minutes": float(base_minutes),
            "habit_score": habit_score,
            "habit_breakdown": breakdown,
            "verified_wakes": max(int(wake.get("verified_wakes") or 0), verified_local),
            "consistency_score": float(wake.get("consistency_score") or 0.0),
            "on_time_rate": float(wake.get("on_time_rate") or 0.0),
            "mean_wake_minutes": mean_minutes,
            "avg_snoozes_per_wake": float(snooze.get("avg_snoozes_per_wake") or 0.0),
            "snooze_limit_hit_rate": float(snooze.get("limit_hit_rate") or 0.0),
            "sleep_adherence_rate": float(sleep.get("adherence_rate") or 0.0),
            "streak_days": int(getattr(profile, "streak_days", 0) or 0)
            if profile
            else 0,
            "snooze_interval_minutes": int(
                getattr(alarm, "snooze_interval_minutes", 5) or 5
            ),
        }

    @classmethod
    def _local_verified_wake_minutes(
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        user_tz: ZoneInfo,
    ) -> List[float]:
        """Wall-clock minutes-of-day for verified wakes in the user's timezone."""
        rows = (
            db.query(AlarmWakeEvent)
            .filter(
                AlarmWakeEvent.user_id == user_id,
                AlarmWakeEvent.verified.is_(True),
                AlarmWakeEvent.dismissed_at.isnot(None),
                AlarmWakeEvent.triggered_at >= window_start,
            )
            .all()
        )
        minutes: List[float] = []
        for row in rows:
            dismissed = row.dismissed_at
            if dismissed is None:
                continue
            if dismissed.tzinfo is None:
                dismissed = dismissed.replace(tzinfo=timezone.utc)
            local = dismissed.astimezone(user_tz)
            minutes.append(
                float(local.hour * 60 + local.minute + (local.second or 0) / 60.0)
            )
        return minutes

    @staticmethod
    def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
        try:
            return ZoneInfo(tz_name or "UTC")
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

    @classmethod
    def _offset_from_signals(cls, signals: Dict[str, Any]) -> int:
        """Combine signals into a signed minute offset (negative = earlier)."""
        if int(signals["verified_wakes"]) < MIN_VERIFIED_WAKES:
            return 0

        habit = float(signals["habit_score"])
        consistency = float(signals["consistency_score"])
        avg_snoozes = float(signals["avg_snoozes_per_wake"])
        limit_hit = float(signals["snooze_limit_hit_rate"])
        adherence = float(signals["sleep_adherence_rate"])
        streak = int(signals["streak_days"])
        interval = int(signals["snooze_interval_minutes"])
        mean_wake = signals["mean_wake_minutes"]
        base_minutes = float(signals["base_minutes"])

        # 1) Snooze compensation — ring earlier when the user habitually delays
        snooze_offset = -min(
            avg_snoozes * interval * SNOOZE_COMPENSATION_FACTOR,
            float(MAX_EARLIER_MINUTES),
        )
        if limit_hit >= 40.0:
            snooze_offset -= 5.0

        # 2) Habit dampening / amplification
        if habit >= 75.0:
            habit_scale = 0.5
        elif habit < 40.0:
            habit_scale = 1.25
        else:
            habit_scale = 1.0

        # 3) Sleep-schedule reinforcement
        sleep_offset = 0.0
        if streak >= 7 and adherence >= 70.0:
            # Strong schedule — keep closer to target (reduce other offsets)
            habit_scale *= 0.75
        elif adherence < 40.0 and streak == 0:
            # Struggling to stick — gentle earlier nudge
            sleep_offset = -5.0

        # 4) Late-wake nudge from mean verified wake time
        late_offset = 0.0
        if mean_wake is not None:
            delta = float(
                BehavioralAnalyticsService._circular_minute_delta(
                    np.asarray([float(mean_wake)]),
                    base_minutes,
                )[0]
            )
            if delta > 5.0:
                # Mean wake later than target → ring earlier; stronger if inconsistent
                inconsistency = max(0.0, (100.0 - consistency) / 100.0)
                late_offset = -min(delta * (0.25 + 0.5 * inconsistency), 20.0)
            elif delta < -10.0 and habit >= 70.0:
                # Consistently early with good habits → allow slight later ring
                late_offset = min(abs(delta) * 0.15, float(MAX_LATER_MINUTES))

        raw = (snooze_offset + late_offset + sleep_offset) * habit_scale
        clamped = max(
            -float(MAX_EARLIER_MINUTES),
            min(float(MAX_LATER_MINUTES), raw),
        )
        return int(round(clamped))

    @staticmethod
    def _minutes_to_time(minutes: float) -> time:
        total = int(round(float(minutes))) % (24 * 60)
        if total < 0:
            total += 24 * 60
        h, m = divmod(total, 60)
        return time(hour=h, minute=m, second=0)