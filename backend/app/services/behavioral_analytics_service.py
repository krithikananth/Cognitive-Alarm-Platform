"""
Behavioral Analytics Engine (pandas / numpy).

Aggregates domain SSOT tables (snooze events, wake events, challenge logs,
user profile) into behavioral insights:

- Snooze patterns
- Wake-up consistency
- Sleep schedule adherence
- Weekly trends
- Monthly trends
- Habit trends

Does not mutate existing dashboard contracts; read-only over domain data.
Habit score components reuse ``calculate_habit_score`` as SSOT.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.alarm import AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.habit_score import (
    calculate_habit_score,
    calculate_habit_score_for_user,
)

# Default lookback windows
DEFAULT_DAYS = 30
WEEKLY_DAYS = 7
MONTHLY_DAYS = 30

# Wake is "on time" if within this many minutes of preferred_wake_time
ON_TIME_TOLERANCE_MINUTES = 15

# Weekday labels (pandas dayofweek: Mon=0 … Sun=6)
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class BehavioralAnalyticsService:
    """Compute behavioral analytics with pandas/numpy."""

    @classmethod
    def get_overview(
        cls,
        db: Session,
        user_id: int,
        days: int = DEFAULT_DAYS,
    ) -> Dict[str, Any]:
        """Full behavioral analytics bundle for the authenticated user."""
        days = max(1, min(int(days or DEFAULT_DAYS), 365))
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=days)

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        snooze_df = cls._load_snooze_df(db, user_id, window_start)
        wake_df = cls._load_wake_df(db, user_id, window_start)
        challenge_df = cls._load_challenge_df(db, user_id, window_start)

        preferred = cls._preferred_wake_minutes(profile)

        snooze = cls.analyze_snooze_pattern(snooze_df, wake_df)
        wake = cls.analyze_wake_consistency(wake_df, preferred, profile)
        sleep = cls.analyze_sleep_adherence(wake_df, preferred, profile)
        weekly = cls.analyze_weekly_trends(snooze_df, wake_df, challenge_df, preferred)
        monthly = cls.analyze_monthly_trends(snooze_df, wake_df, challenge_df, preferred)
        habit = cls.analyze_habit_trends(
            snooze_df,
            wake_df,
            challenge_df,
            preferred,
            profile,
            db=db,
            user_id=user_id,
        )

        return {
            "generated_at": now.isoformat(),
            "window_days": days,
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
            "snooze_pattern": snooze,
            "wake_up_consistency": wake,
            "sleep_schedule_adherence": sleep,
            "weekly_trends": weekly,
            "monthly_trends": monthly,
            "habit_trends": habit,
            "insights": cls._build_insights(snooze, wake, sleep, habit),
        }

    # ── Public analyzers (also used by focused endpoints / tests) ───────

    @classmethod
    def analyze_snooze_pattern(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Snooze timing, volume, and limit-hit patterns."""
        empty = {
            "total_snoozes": 0,
            "avg_snoozes_per_wake": 0.0,
            "avg_snooze_number": 0.0,
            "limit_hit_count": 0,
            "limit_hit_rate": 0.0,
            "by_hour": [{"hour": h, "count": 0} for h in range(24)],
            "by_weekday": [
                {"weekday": WEEKDAY_LABELS[i], "weekday_index": i, "count": 0}
                for i in range(7)
            ],
            "peak_hour": None,
            "peak_weekday": None,
            "trend": "insufficient_data",
            "recent_7d_count": 0,
            "previous_7d_count": 0,
        }
        if snooze_df.empty and wake_df.empty:
            return empty

        total = int(len(snooze_df))
        avg_number = (
            float(np.round(snooze_df["snooze_number"].astype(float).mean(), 2))
            if not snooze_df.empty
            else 0.0
        )

        if not wake_df.empty and "snooze_count_at_dismiss" in wake_df.columns:
            verified = wake_df[wake_df["verified"] == True]  # noqa: E712
            if verified.empty:
                verified = wake_df
            avg_per_wake = float(
                np.round(verified["snooze_count_at_dismiss"].astype(float).mean(), 2)
            )
        else:
            avg_per_wake = 0.0

        if not snooze_df.empty:
            hit_mask = (
                snooze_df["snooze_limit_at_event"].astype(int) > 0
            ) & (
                snooze_df["snooze_number"].astype(int)
                >= snooze_df["snooze_limit_at_event"].astype(int)
            )
            limit_hit_count = int(hit_mask.sum())
            limit_hit_rate = float(
                np.round((limit_hit_count / total) * 100.0, 2)
            ) if total else 0.0

            hours = snooze_df["created_at"].dt.hour.to_numpy()
            hour_counts = np.bincount(hours, minlength=24)
            by_hour = [
                {"hour": int(h), "count": int(hour_counts[h])} for h in range(24)
            ]
            peak_hour = int(np.argmax(hour_counts)) if hour_counts.sum() else None

            dow = snooze_df["created_at"].dt.dayofweek.to_numpy()
            dow_counts = np.bincount(dow, minlength=7)
            by_weekday = [
                {
                    "weekday": WEEKDAY_LABELS[i],
                    "weekday_index": i,
                    "count": int(dow_counts[i]),
                }
                for i in range(7)
            ]
            peak_weekday = (
                WEEKDAY_LABELS[int(np.argmax(dow_counts))]
                if dow_counts.sum()
                else None
            )

            now = pd.Timestamp.now(tz="UTC")
            recent = snooze_df[snooze_df["created_at"] >= (now - pd.Timedelta(days=7))]
            previous = snooze_df[
                (snooze_df["created_at"] >= (now - pd.Timedelta(days=14)))
                & (snooze_df["created_at"] < (now - pd.Timedelta(days=7)))
            ]
            recent_n = int(len(recent))
            prev_n = int(len(previous))
            trend = cls._compare_trend(recent_n, prev_n, lower_is_better=True)
        else:
            limit_hit_count = 0
            limit_hit_rate = 0.0
            by_hour = empty["by_hour"]
            by_weekday = empty["by_weekday"]
            peak_hour = None
            peak_weekday = None
            recent_n = 0
            prev_n = 0
            trend = "insufficient_data"

        return {
            "total_snoozes": total,
            "avg_snoozes_per_wake": avg_per_wake,
            "avg_snooze_number": avg_number,
            "limit_hit_count": limit_hit_count,
            "limit_hit_rate": limit_hit_rate,
            "by_hour": by_hour,
            "by_weekday": by_weekday,
            "peak_hour": peak_hour,
            "peak_weekday": peak_weekday,
            "trend": trend,
            "recent_7d_count": recent_n,
            "previous_7d_count": prev_n,
        }

    @classmethod
    def analyze_wake_consistency(
        cls,
        wake_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        profile: Optional[UserProfile],
    ) -> Dict[str, Any]:
        """Wake-time mean/std, on-time rate, and consistency score."""
        rolling = float(
            getattr(profile, "wake_up_consistency_score", 0.0) or 0.0
        ) if profile is not None else 0.0

        base = {
            "verified_wakes": 0,
            "mean_wake_time": None,
            "std_wake_minutes": None,
            "consistency_score": 0.0,
            "rolling_profile_score": round(min(rolling, 100.0), 2),
            "on_time_count": 0,
            "on_time_rate": 0.0,
            "avg_deviation_minutes": None,
            "preferred_wake_time": cls._minutes_to_hhmm(preferred_minutes),
            "tolerance_minutes": ON_TIME_TOLERANCE_MINUTES,
            "trend": "insufficient_data",
        }

        verified = cls._verified_wakes(wake_df)
        if verified.empty:
            return base

        minutes = verified["wake_minutes"].to_numpy(dtype=float)
        mean_m = float(np.mean(minutes))
        # Round std once, then derive the score from that value so displayed
        # std_wake_minutes always reconstructs consistency_score exactly.
        std_m = float(
            np.round(float(np.std(minutes)) if len(minutes) > 1 else 0.0, 2)
        )

        # Consistency: lower std → higher score. 60+ min std ≈ 0.
        consistency = float(np.clip(100.0 - (std_m * (100.0 / 60.0)), 0.0, 100.0))

        if preferred_minutes is not None:
            deviations = cls._circular_minute_delta(minutes, preferred_minutes)
            on_time_mask = np.abs(deviations) <= ON_TIME_TOLERANCE_MINUTES
            on_time_count = int(on_time_mask.sum())
            on_time_rate = float(np.round((on_time_count / len(minutes)) * 100.0, 2))
            avg_dev = float(np.round(float(np.mean(np.abs(deviations))), 2))
        else:
            on_time_count = 0
            on_time_rate = 0.0
            avg_dev = None

        # Trend: compare std of last 7d vs previous 7d (lower std = improving)
        now = pd.Timestamp.now(tz="UTC")
        recent = verified[verified["dismissed_at"] >= (now - pd.Timedelta(days=7))]
        previous = verified[
            (verified["dismissed_at"] >= (now - pd.Timedelta(days=14)))
            & (verified["dismissed_at"] < (now - pd.Timedelta(days=7)))
        ]
        if len(recent) >= 2 and len(previous) >= 2:
            recent_std = float(np.std(recent["wake_minutes"].to_numpy(dtype=float)))
            prev_std = float(np.std(previous["wake_minutes"].to_numpy(dtype=float)))
            trend = cls._compare_trend(recent_std, prev_std, lower_is_better=True)
        else:
            trend = "insufficient_data"

        return {
            "verified_wakes": int(len(verified)),
            "mean_wake_time": cls._minutes_to_hhmm(mean_m),
            "std_wake_minutes": std_m,
            "consistency_score": float(np.round(consistency, 2)),
            "rolling_profile_score": round(min(rolling, 100.0), 2),
            "on_time_count": on_time_count,
            "on_time_rate": on_time_rate,
            "avg_deviation_minutes": avg_dev,
            "preferred_wake_time": cls._minutes_to_hhmm(preferred_minutes),
            "tolerance_minutes": ON_TIME_TOLERANCE_MINUTES,
            "trend": trend,
        }

    @classmethod
    def analyze_sleep_adherence(
        cls,
        wake_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        profile: Optional[UserProfile],
    ) -> Dict[str, Any]:
        """Schedule adherence vs preferred wake + target sleep duration."""
        sleep_hours = float(
            getattr(profile, "sleep_duration_hours", 8.0) or 8.0
        ) if profile is not None else 8.0
        streak = int(getattr(profile, "streak_days", 0) or 0) if profile else 0

        habit = calculate_habit_score(
            profile
            if profile is not None
            else {
                "wake_up_consistency_score": 0.0,
                "total_alarms_dismissed": 0,
                "total_snoozes": 0,
                "streak_days": 0,
            }
        )
        profile_adherence = float(habit["breakdown"]["sleep_adherence"])

        base = {
            "preferred_wake_time": cls._minutes_to_hhmm(preferred_minutes),
            "target_sleep_hours": sleep_hours,
            "suggested_bedtime": cls._suggested_bedtime(preferred_minutes, sleep_hours),
            "adherence_rate": 0.0,
            "adherent_days": 0,
            "observed_days": 0,
            "avg_deviation_minutes": None,
            "profile_streak_days": streak,
            "profile_adherence_score": profile_adherence,
            "tolerance_minutes": ON_TIME_TOLERANCE_MINUTES,
            "trend": "insufficient_data",
        }

        verified = cls._verified_wakes(wake_df)
        if verified.empty or preferred_minutes is None:
            return base

        # One row per calendar day (latest wake that day)
        verified = verified.copy()
        verified["day"] = verified["dismissed_at"].dt.normalize()
        daily = (
            verified.sort_values("dismissed_at")
            .groupby("day", as_index=False)
            .last()
        )
        minutes = daily["wake_minutes"].to_numpy(dtype=float)
        deviations = cls._circular_minute_delta(minutes, preferred_minutes)
        adherent_mask = np.abs(deviations) <= ON_TIME_TOLERANCE_MINUTES
        adherent_days = int(adherent_mask.sum())
        observed = int(len(daily))
        adherence_rate = float(np.round((adherent_days / observed) * 100.0, 2))
        avg_dev = float(np.round(float(np.mean(np.abs(deviations))), 2))

        now = pd.Timestamp.now(tz="UTC").normalize()
        recent_days = daily[daily["day"] >= (now - pd.Timedelta(days=7))]
        prev_days = daily[
            (daily["day"] >= (now - pd.Timedelta(days=14)))
            & (daily["day"] < (now - pd.Timedelta(days=7)))
        ]
        if len(recent_days) and len(prev_days):
            r_rate = float(
                (
                    np.abs(
                        cls._circular_minute_delta(
                            recent_days["wake_minutes"].to_numpy(dtype=float),
                            preferred_minutes,
                        )
                    )
                    <= ON_TIME_TOLERANCE_MINUTES
                ).mean()
            )
            p_rate = float(
                (
                    np.abs(
                        cls._circular_minute_delta(
                            prev_days["wake_minutes"].to_numpy(dtype=float),
                            preferred_minutes,
                        )
                    )
                    <= ON_TIME_TOLERANCE_MINUTES
                ).mean()
            )
            trend = cls._compare_trend(r_rate, p_rate, lower_is_better=False)
        else:
            trend = "insufficient_data"

        return {
            **base,
            "adherence_rate": adherence_rate,
            "adherent_days": adherent_days,
            "observed_days": observed,
            "avg_deviation_minutes": avg_dev,
            "trend": trend,
        }

    @classmethod
    def analyze_weekly_trends(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
    ) -> Dict[str, Any]:
        """Last 7 calendar days of snooze / wake / challenge metrics."""
        return cls._period_trends(
            snooze_df,
            wake_df,
            challenge_df,
            preferred_minutes,
            days=WEEKLY_DAYS,
            period_label="week",
        )

    @classmethod
    def analyze_monthly_trends(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
    ) -> Dict[str, Any]:
        """Last 30 calendar days of snooze / wake / challenge metrics."""
        return cls._period_trends(
            snooze_df,
            wake_df,
            challenge_df,
            preferred_minutes,
            days=MONTHLY_DAYS,
            period_label="month",
        )

    @classmethod
    def analyze_habit_trends(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        profile: Optional[UserProfile],
        db: Optional[Session] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Daily habit-score proxies + current SSOT habit score.

        ``current_habit_score`` is recalculated from lifetime verified wake
        events when ``db``/``user_id`` are provided; otherwise profile
        counters (or empty defaults) are used.
        """
        if db is not None and user_id is not None:
            current = calculate_habit_score_for_user(db, user_id, profile)
        else:
            current = calculate_habit_score(
                profile
                if profile is not None
                else {
                    "wake_up_consistency_score": 0.0,
                    "total_alarms_dismissed": 0,
                    "total_snoozes": 0,
                    "streak_days": 0,
                }
            )

        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=MONTHLY_DAYS - 1)
        days = pd.date_range(start, end, freq="D", tz="UTC")

        verified = cls._verified_wakes(wake_df)
        series: List[Dict[str, Any]] = []
        scores: List[float] = []

        for day in days:
            day_end = day + pd.Timedelta(days=1)
            day_wakes = (
                verified[
                    (verified["dismissed_at"] >= day)
                    & (verified["dismissed_at"] < day_end)
                ]
                if not verified.empty
                else verified
            )
            day_snoozes = (
                snooze_df[
                    (snooze_df["created_at"] >= day)
                    & (snooze_df["created_at"] < day_end)
                ]
                if not snooze_df.empty
                else snooze_df
            )
            day_challenges = (
                challenge_df[
                    (challenge_df["created_at"] >= day)
                    & (challenge_df["created_at"] < day_end)
                ]
                if not challenge_df.empty
                else challenge_df
            )

            proxy = cls._daily_habit_proxy(
                day_wakes, day_snoozes, day_challenges, preferred_minutes
            )
            scores.append(proxy["habit_score"])
            series.append(
                {
                    "date": day.date().isoformat(),
                    "habit_score": proxy["habit_score"],
                    "breakdown": proxy["breakdown"],
                    "has_activity": proxy["has_activity"],
                }
            )

        active_scores = [s["habit_score"] for s in series if s["has_activity"]]
        if len(active_scores) >= 2:
            mid = len(active_scores) // 2
            first_avg = float(np.mean(active_scores[:mid])) if mid else 0.0
            second_avg = float(np.mean(active_scores[mid:]))
            trend = cls._compare_trend(second_avg, first_avg, lower_is_better=False)
            avg_score = float(np.round(float(np.mean(active_scores)), 2))
        elif len(active_scores) == 1:
            trend = "stable"
            avg_score = float(np.round(active_scores[0], 2))
        else:
            trend = "insufficient_data"
            avg_score = 0.0

        return {
            "current_habit_score": current["habit_score"],
            "current_breakdown": current["breakdown"],
            "weights": current["weights"],
            "avg_proxy_score": avg_score,
            "trend": trend,
            "series": series,
        }

    # ── Data loaders ────────────────────────────────────────────────────

    @classmethod
    def _load_snooze_df(
        cls, db: Session, user_id: int, window_start: datetime
    ) -> pd.DataFrame:
        rows = (
            db.query(AlarmSnoozeEvent)
            .filter(
                AlarmSnoozeEvent.user_id == user_id,
                AlarmSnoozeEvent.created_at >= window_start,
            )
            .all()
        )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "id",
                    "alarm_id",
                    "snooze_number",
                    "snooze_limit_at_event",
                    "created_at",
                ]
            )
        data = [
            {
                "id": r.id,
                "alarm_id": r.alarm_id,
                "snooze_number": r.snooze_number,
                "snooze_limit_at_event": r.snooze_limit_at_event,
                "created_at": cls._as_utc_ts(r.created_at),
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        return df

    @classmethod
    def _load_wake_df(
        cls, db: Session, user_id: int, window_start: datetime
    ) -> pd.DataFrame:
        rows = (
            db.query(AlarmWakeEvent)
            .filter(
                AlarmWakeEvent.user_id == user_id,
                AlarmWakeEvent.triggered_at >= window_start,
            )
            .all()
        )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "id",
                    "alarm_id",
                    "triggered_at",
                    "dismissed_at",
                    "dismiss_method",
                    "snooze_count_at_dismiss",
                    "time_to_dismiss_seconds",
                    "verified",
                    "wake_minutes",
                ]
            )
        data = []
        for r in rows:
            dismissed = cls._as_utc_ts(r.dismissed_at) if r.dismissed_at else None
            wake_minutes = None
            if dismissed is not None:
                wake_minutes = dismissed.hour * 60 + dismissed.minute + dismissed.second / 60.0
            data.append(
                {
                    "id": r.id,
                    "alarm_id": r.alarm_id,
                    "triggered_at": cls._as_utc_ts(r.triggered_at),
                    "dismissed_at": dismissed,
                    "dismiss_method": r.dismiss_method,
                    "snooze_count_at_dismiss": r.snooze_count_at_dismiss or 0,
                    "time_to_dismiss_seconds": r.time_to_dismiss_seconds,
                    "verified": bool(r.verified),
                    "wake_minutes": wake_minutes,
                }
            )
        df = pd.DataFrame(data)
        df["triggered_at"] = pd.to_datetime(df["triggered_at"], utc=True)
        df["dismissed_at"] = pd.to_datetime(df["dismissed_at"], utc=True)
        return df

    @classmethod
    def _load_challenge_df(
        cls, db: Session, user_id: int, window_start: datetime
    ) -> pd.DataFrame:
        rows = (
            db.query(AlarmChallengeLog)
            .filter(
                AlarmChallengeLog.user_id == user_id,
                AlarmChallengeLog.created_at >= window_start,
            )
            .all()
        )
        if not rows:
            return pd.DataFrame(
                columns=[
                    "id",
                    "is_correct",
                    "time_taken_seconds",
                    "points_earned",
                    "created_at",
                ]
            )
        data = [
            {
                "id": r.id,
                "is_correct": bool(r.is_correct),
                "time_taken_seconds": r.time_taken_seconds or 0,
                "points_earned": r.points_earned or 0,
                "created_at": cls._as_utc_ts(r.created_at),
            }
            for r in rows
        ]
        df = pd.DataFrame(data)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        return df

    # ── Internals ───────────────────────────────────────────────────────

    @classmethod
    def _period_trends(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        days: int,
        period_label: str,
    ) -> Dict[str, Any]:
        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=days - 1)
        index = pd.date_range(start, end, freq="D", tz="UTC")

        verified = cls._verified_wakes(wake_df)
        series: List[Dict[str, Any]] = []

        for day in index:
            day_end = day + pd.Timedelta(days=1)
            s_count = (
                int(
                    (
                        (snooze_df["created_at"] >= day)
                        & (snooze_df["created_at"] < day_end)
                    ).sum()
                )
                if not snooze_df.empty
                else 0
            )
            day_wakes = (
                verified[
                    (verified["dismissed_at"] >= day)
                    & (verified["dismissed_at"] < day_end)
                ]
                if not verified.empty
                else verified
            )
            wakes = int(len(day_wakes))
            on_time = 0
            avg_snoozes = 0.0
            avg_dismiss_s = None
            if wakes:
                avg_snoozes = float(
                    np.round(
                        day_wakes["snooze_count_at_dismiss"].astype(float).mean(), 2
                    )
                )
                ttd = day_wakes["time_to_dismiss_seconds"].dropna()
                if len(ttd):
                    avg_dismiss_s = float(np.round(float(ttd.mean()), 1))
                if preferred_minutes is not None:
                    devs = cls._circular_minute_delta(
                        day_wakes["wake_minutes"].to_numpy(dtype=float),
                        preferred_minutes,
                    )
                    on_time = int((np.abs(devs) <= ON_TIME_TOLERANCE_MINUTES).sum())

            c_day = (
                challenge_df[
                    (challenge_df["created_at"] >= day)
                    & (challenge_df["created_at"] < day_end)
                ]
                if not challenge_df.empty
                else challenge_df
            )
            attempts = int(len(c_day))
            accuracy = (
                float(np.round((c_day["is_correct"].sum() / attempts) * 100.0, 2))
                if attempts
                else None
            )

            series.append(
                {
                    "date": day.date().isoformat(),
                    "weekday": WEEKDAY_LABELS[int(day.dayofweek)],
                    "snoozes": s_count,
                    "verified_wakes": wakes,
                    "on_time_wakes": on_time,
                    "avg_snoozes_per_wake": avg_snoozes,
                    "avg_time_to_dismiss_seconds": avg_dismiss_s,
                    "challenge_attempts": attempts,
                    "challenge_accuracy": accuracy,
                }
            )

        totals = {
            "snoozes": int(sum(d["snoozes"] for d in series)),
            "verified_wakes": int(sum(d["verified_wakes"] for d in series)),
            "on_time_wakes": int(sum(d["on_time_wakes"] for d in series)),
            "challenge_attempts": int(sum(d["challenge_attempts"] for d in series)),
        }
        on_time_rate = (
            float(
                np.round(
                    (totals["on_time_wakes"] / totals["verified_wakes"]) * 100.0, 2
                )
            )
            if totals["verified_wakes"]
            else 0.0
        )

        # Half-window comparison for trend direction
        mid = max(1, days // 2)
        first = series[:mid]
        second = series[mid:]
        first_w = sum(d["verified_wakes"] for d in first)
        second_w = sum(d["verified_wakes"] for d in second)
        first_ot = sum(d["on_time_wakes"] for d in first)
        second_ot = sum(d["on_time_wakes"] for d in second)
        if first_w and second_w:
            trend = cls._compare_trend(
                second_ot / second_w,
                first_ot / first_w,
                lower_is_better=False,
            )
        else:
            trend = "insufficient_data"

        return {
            "period": period_label,
            "days": days,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "totals": {**totals, "on_time_rate": on_time_rate},
            "trend": trend,
            "series": series,
        }

    @classmethod
    def _daily_habit_proxy(
        cls,
        day_wakes: pd.DataFrame,
        day_snoozes: pd.DataFrame,
        day_challenges: pd.DataFrame,
        preferred_minutes: Optional[float],
    ) -> Dict[str, Any]:
        has_activity = bool(
            len(day_wakes) or len(day_snoozes) or len(day_challenges)
        )
        if not has_activity:
            return {
                "habit_score": 0.0,
                "breakdown": {
                    "wake_up_consistency": 0.0,
                    "challenge_completion": 0.0,
                    "snooze_reduction": 0.0,
                    "sleep_adherence": 0.0,
                },
                "has_activity": False,
            }

        # Wake consistency for the day from deviation / presence
        if len(day_wakes) and preferred_minutes is not None:
            devs = cls._circular_minute_delta(
                day_wakes["wake_minutes"].to_numpy(dtype=float),
                preferred_minutes,
            )
            wake_score = float(
                np.clip(100.0 - float(np.mean(np.abs(devs))), 0.0, 100.0)
            )
            adherent = bool(np.mean(np.abs(devs)) <= ON_TIME_TOLERANCE_MINUTES)
            streak_proxy = 1 if adherent else 0
        elif len(day_wakes):
            wake_score = 70.0
            streak_proxy = 1
        else:
            wake_score = 40.0
            streak_proxy = 0

        dismissed = int(len(day_wakes))
        snoozes = int(len(day_snoozes))
        if not snoozes and len(day_wakes):
            snoozes = int(day_wakes["snooze_count_at_dismiss"].astype(int).sum())

        # Puzzle accuracy for challenge_completion (SSOT prefers logs)
        puzzle_correct = 0
        puzzle_attempts = 0
        if len(day_challenges):
            puzzle_correct = int(day_challenges["is_correct"].sum())
            puzzle_attempts = int(len(day_challenges))

        result = calculate_habit_score(
            {
                "wake_up_consistency_score": wake_score,
                "total_alarms_dismissed": dismissed,
                "total_snoozes": snoozes,
                "streak_days": streak_proxy,
                "total_puzzle_correct": puzzle_correct,
                "total_puzzle_attempts": puzzle_attempts,
            }
        )
        return {
            "habit_score": result["habit_score"],
            "breakdown": result["breakdown"],
            "has_activity": True,
        }

    @staticmethod
    def _verified_wakes(wake_df: pd.DataFrame) -> pd.DataFrame:
        if wake_df.empty:
            return wake_df
        out = wake_df[
            (wake_df["verified"] == True)  # noqa: E712
            & wake_df["dismissed_at"].notna()
            & wake_df["wake_minutes"].notna()
        ].copy()
        return out

    @staticmethod
    def _preferred_wake_minutes(profile: Optional[UserProfile]) -> Optional[float]:
        if profile is None or profile.preferred_wake_time is None:
            return None
        t: time = profile.preferred_wake_time
        return float(t.hour * 60 + t.minute + (t.second or 0) / 60.0)

    @staticmethod
    def _minutes_to_hhmm(minutes: Optional[float]) -> Optional[str]:
        if minutes is None or (isinstance(minutes, float) and np.isnan(minutes)):
            return None
        total = int(round(float(minutes))) % (24 * 60)
        h, m = divmod(total, 60)
        return f"{h:02d}:{m:02d}"

    @staticmethod
    def _suggested_bedtime(
        preferred_minutes: Optional[float], sleep_hours: float
    ) -> Optional[str]:
        if preferred_minutes is None:
            return None
        bed = (preferred_minutes - sleep_hours * 60.0) % (24 * 60)
        return BehavioralAnalyticsService._minutes_to_hhmm(bed)

    @staticmethod
    def _circular_minute_delta(
        values: np.ndarray, target: float
    ) -> np.ndarray:
        """Signed minute delta on a 24h circle, range (-720, 720]."""
        diff = values.astype(float) - float(target)
        diff = ((diff + 720.0) % 1440.0) - 720.0
        return diff

    @staticmethod
    def _as_utc_ts(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _compare_trend(
        recent: float, previous: float, *, lower_is_better: bool
    ) -> str:
        if previous == 0 and recent == 0:
            return "stable"
        baseline = abs(previous) if previous != 0 else 1.0
        change = (recent - previous) / baseline
        # 5% band counts as stable
        if abs(change) < 0.05:
            return "stable"
        improving = change < 0 if lower_is_better else change > 0
        return "improving" if improving else "declining"

    @staticmethod
    def _build_insights(
        snooze: Dict[str, Any],
        wake: Dict[str, Any],
        sleep: Dict[str, Any],
        habit: Dict[str, Any],
    ) -> List[str]:
        insights: List[str] = []
        if snooze["total_snoozes"] == 0 and wake["verified_wakes"] == 0:
            insights.append(
                "Not enough wake/snooze history yet. Dismiss a few alarms to unlock trends."
            )
            return insights

        if snooze["avg_snoozes_per_wake"] >= 2:
            insights.append(
                f"You average {snooze['avg_snoozes_per_wake']} snoozes per wake — "
                "tightening the snooze limit can raise habit score quickly."
            )
        elif snooze["total_snoozes"] > 0 and snooze["trend"] == "improving":
            insights.append("Snooze volume is trending down — keep reinforcing first-ring dismissals.")

        if wake["verified_wakes"] >= 3:
            insights.append(
                f"Wake consistency score is {wake['consistency_score']} "
                f"(std {wake['std_wake_minutes']} min). "
                f"On-time rate vs preferred wake: {wake['on_time_rate']}%."
            )

        if sleep.get("preferred_wake_time") and sleep["observed_days"]:
            insights.append(
                f"Sleep schedule adherence is {sleep['adherence_rate']}% "
                f"({sleep['adherent_days']}/{sleep['observed_days']} days within "
                f"±{sleep['tolerance_minutes']} min of {sleep['preferred_wake_time']})."
            )

        if habit["current_habit_score"] is not None:
            insights.append(
                f"Current habit score is {habit['current_habit_score']}; "
                f"30-day proxy trend is {habit['trend']}."
            )
        return insights
