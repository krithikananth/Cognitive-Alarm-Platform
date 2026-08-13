"""
Behavioral Analytics Engine (pandas / numpy).

Aggregates domain SSOT tables (snooze events, wake events, challenge logs,
analytics events, user profile) into behavioral insights:

- Snooze patterns
- Wake-up consistency
- Sleep schedule adherence
- Sleep patterns (observed bedtime / duration / regularity)
- Productivity correlation
- Weekly trends
- Monthly trends
- Habit trends

Does not mutate existing dashboard contracts; read-only over domain data.
Habit score components reuse ``calculate_habit_score`` as SSOT.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import select, union_all
from sqlalchemy.orm import Session

from app.models.alarm import AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.profile import UserProfile
from app.services import correlation as corr
from app.services.habit_score import (
    calculate_habit_score,
    calculate_habit_score_for_user,
    format_habit_score,
)

# Default lookback windows
DEFAULT_DAYS = 30
WEEKLY_DAYS = 7
MONTHLY_DAYS = 30

# Wake is "on time" if within this many minutes of preferred_wake_time
ON_TIME_TOLERANCE_MINUTES = 15

# Weekday labels (pandas dayofweek: Mon=0 … Sun=6)
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ── Snooze reduction ────────────────────────────────────────────────────
# Raw snooze counts are not comparable across two periods: setting fewer
# alarms also produces fewer snoozes. Both sides are therefore normalised to
# snoozes per wake event before the reduction is taken.
SNOOZE_REDUCTION_DEFAULT_PERIOD_DAYS = WEEKLY_DAYS
# Upper bound on one comparison period, so the paired lookback stays bounded.
SNOOZE_REDUCTION_MAX_PERIOD_DAYS = 90
# Wake events required in *each* period before a reduction is reported.
SNOOZE_REDUCTION_MIN_WAKES = 3

# ── Wake-up verification accuracy ───────────────────────────────────────
# Finished wake cycles needed before the gate's decisions are scored.
VERIFICATION_MIN_DECISIONS = 3

# ── Sleep-session reconstruction bounds ─────────────────────────────────
# A verified wake is paired with the user's last observed activity before it.
# Activity closer than MIN (still winding down / already awake) or older than
# MAX (an idle gap, not a night) cannot bound a plausible sleep session.
SLEEP_MIN_DURATION_HOURS = 2.0
SLEEP_MAX_DURATION_HOURS = 16.0
SHORT_SLEEP_HOURS = 6.0
LONG_SLEEP_HOURS = 9.0

# Explicitly logged sleep boundaries always beat an interaction-derived estimate
SLEEP_STARTED_EVENT = "sleep.started"
SLEEP_ENDED_EVENT = "sleep.ended"
SLEEP_RECORD_EVENT_TYPES = (SLEEP_STARTED_EVENT, SLEEP_ENDED_EVENT)

# How a night's sleep start was established
SLEEP_SOURCE_RECORDED = "recorded"
SLEEP_SOURCE_ESTIMATED = "estimated"

# Minutes of combined bedtime/wake scatter that drives regularity to zero
REGULARITY_ZERO_AT_STD_MINUTES = 120.0
# Hours of duration scatter that drives duration consistency to zero
DURATION_CONSISTENCY_ZERO_AT_STD_HOURS = 4.0

# Complete paired observations required before a coefficient is reported
CORRELATION_MIN_PAIRS = corr.DEFAULT_MIN_PAIRS


class _CorrelationSpec(NamedTuple):
    """One behaviour/outcome pair to correlate."""

    id: str
    behavior: str
    behavior_label: str
    outcome: str
    outcome_label: str
    # Direction the domain predicts, used only to annotate the result
    expected_direction: str


_CORRELATION_SPECS: Tuple[_CorrelationSpec, ...] = (
    _CorrelationSpec(
        "snooze_vs_accuracy",
        "snooze_count",
        "daily snoozes",
        "challenge_accuracy",
        "challenge accuracy",
        "negative",
    ),
    _CorrelationSpec(
        "snooze_vs_wakefulness",
        "snooze_count",
        "daily snoozes",
        "wakefulness",
        "wakefulness score",
        "negative",
    ),
    _CorrelationSpec(
        "schedule_deviation_vs_accuracy",
        "schedule_deviation_minutes",
        "wake-time deviation",
        "challenge_accuracy",
        "challenge accuracy",
        "negative",
    ),
    _CorrelationSpec(
        "schedule_deviation_vs_wakefulness",
        "schedule_deviation_minutes",
        "wake-time deviation",
        "wakefulness",
        "wakefulness score",
        "negative",
    ),
    _CorrelationSpec(
        "wake_latency_vs_accuracy",
        "wake_latency_seconds",
        "time taken to get up",
        "challenge_accuracy",
        "challenge accuracy",
        "negative",
    ),
    _CorrelationSpec(
        "habit_vs_accuracy",
        "habit_score",
        "daily habit score",
        "challenge_accuracy",
        "challenge accuracy",
        "positive",
    ),
    _CorrelationSpec(
        "habit_vs_points",
        "habit_score",
        "daily habit score",
        "points_earned",
        "points earned",
        "positive",
    ),
    _CorrelationSpec(
        "sleep_duration_vs_accuracy",
        "sleep_duration_hours",
        "measured sleep duration",
        "challenge_accuracy",
        "challenge accuracy",
        "positive",
    ),
    _CorrelationSpec(
        "sleep_duration_vs_wakefulness",
        "sleep_duration_hours",
        "measured sleep duration",
        "wakefulness",
        "wakefulness score",
        "positive",
    ),
    _CorrelationSpec(
        "sleep_duration_vs_response_time",
        "sleep_duration_hours",
        "measured sleep duration",
        "avg_response_seconds",
        "challenge response time",
        "negative",
    ),
)


class BehavioralAnalyticsService:
    """Compute behavioral analytics with pandas/numpy."""

    @classmethod
    def get_overview(
        cls,
        db: Session,
        user_id: int,
        days: int = DEFAULT_DAYS,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Full behavioral analytics bundle for the authenticated user.

        Prefer ``window_start`` / ``window_end`` when both are provided;
        otherwise use a lookback of ``days`` ending at ``window_end`` (or now).
        """
        now = window_end or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        if window_start is not None:
            start = window_start
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            days = max(1, (now.date() - start.date()).days + 1)
            days = min(days, 365)
        else:
            days = max(1, min(int(days or DEFAULT_DAYS), 365))
            start = now - timedelta(days=days)

        profile = (
            db.query(UserProfile)
            .filter(UserProfile.user_id == user_id)
            .first()
        )
        if profile is not None:
            from app.services.day_streak import DayStreakService

            DayStreakService.read_stored_streak(profile, db=db, commit=True)

        snooze_df = cls._load_snooze_df(db, user_id, start, window_end=now)
        wake_df = cls._load_wake_df(db, user_id, start, window_end=now)
        challenge_df = cls._load_challenge_df(db, user_id, start, window_end=now)
        # Lead-in so the first night's sleep onset is visible in the history
        history_start = start - timedelta(hours=SLEEP_MAX_DURATION_HOURS)
        activity_index = cls._load_activity_index(
            db, user_id, history_start, window_end=now
        )
        sleep_records = cls._load_sleep_records(
            db, user_id, history_start, window_end=now
        )

        preferred = cls._preferred_wake_minutes(profile)

        # Snooze reduction needs the period *before* the window as a baseline,
        # which the window-scoped frames above do not cover.
        reduction_period = max(
            1, min(days, SNOOZE_REDUCTION_MAX_PERIOD_DAYS)
        )
        comparison_start = now - timedelta(days=2 * reduction_period)
        if comparison_start < start:
            comparison_snooze_df = cls._load_snooze_df(
                db, user_id, comparison_start, window_end=now
            )
            comparison_wake_df = cls._load_wake_df(
                db, user_id, comparison_start, window_end=now
            )
        else:
            comparison_snooze_df = snooze_df
            comparison_wake_df = wake_df
        snooze_reduction = cls.analyze_snooze_reduction(
            comparison_snooze_df,
            comparison_wake_df,
            window_end=now,
            period_days=reduction_period,
        )

        snooze = cls.analyze_snooze_pattern(
            snooze_df, wake_df, reduction=snooze_reduction
        )
        wake = cls.analyze_wake_consistency(wake_df, preferred, profile)
        verification = cls.analyze_verification_accuracy(wake_df)
        sleep = cls.analyze_sleep_adherence(wake_df, preferred, profile)
        sleep_patterns = cls.analyze_sleep_patterns(
            wake_df, activity_index, profile, sleep_records
        )
        productivity_correlation = cls.analyze_productivity_correlation(
            snooze_df,
            wake_df,
            challenge_df,
            preferred,
            sleep_patterns,
            days,
        )
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
            days=days,
        )

        # Series spanning exactly the requested window, so a 7/30/90 selector
        # charts the period the caller asked for (weekly/monthly stay fixed).
        if days == WEEKLY_DAYS:
            window = weekly
        elif days == MONTHLY_DAYS:
            window = monthly
        else:
            window = cls._period_trends(
                snooze_df,
                wake_df,
                challenge_df,
                preferred,
                days=days,
                period_label="window",
            )

        return {
            "generated_at": now.isoformat(),
            "window_days": days,
            "window_start": start.isoformat(),
            "window_end": now.isoformat(),
            "snooze_pattern": snooze,
            "wake_up_consistency": wake,
            "verification_accuracy": verification,
            "sleep_schedule_adherence": sleep,
            "sleep_patterns": sleep_patterns,
            "productivity_correlation": productivity_correlation,
            "weekly_trends": weekly,
            "monthly_trends": monthly,
            "window_trends": window,
            "habit_trends": habit,
            "insights": cls._build_insights(snooze, wake, sleep, habit),
        }

    # ── Public analyzers (also used by focused endpoints / tests) ───────

    @classmethod
    def analyze_snooze_pattern(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        reduction: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Snooze timing, volume, and limit-hit patterns."""
        reduction_block = (
            reduction if reduction is not None else cls._empty_snooze_reduction()
        )
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
            "reduction": reduction_block,
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
            "reduction": reduction_block,
        }

    @classmethod
    def analyze_snooze_reduction(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        *,
        window_end: Optional[datetime] = None,
        period_days: int = SNOOZE_REDUCTION_DEFAULT_PERIOD_DAYS,
    ) -> Dict[str, Any]:
        """Percentage drop in snoozing between two adjacent, equal periods.

        ``rate`` for a period is ``snoozes / wake events`` inside it, and::

            reduction_rate = (previous_rate - current_rate) / previous_rate * 100

        Positive means the user snoozed less. Normalising by wake events is
        what makes the two periods comparable — a raw count also falls when
        the user simply set fewer alarms.

        Current period is ``(end - period, end]``, previous is
        ``(end - 2*period, end - period]``, so the frames passed in must span
        ``2 * period_days`` back from ``window_end``; rows outside are ignored.
        """
        period = max(1, min(int(period_days or 1), SNOOZE_REDUCTION_MAX_PERIOD_DAYS))
        end = pd.Timestamp(window_end or datetime.now(timezone.utc))
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        mid = end - pd.Timedelta(days=period)
        start = end - pd.Timedelta(days=2 * period)

        result = cls._empty_snooze_reduction(period)
        result.update(
            {
                "current_period_start": mid.isoformat(),
                "current_period_end": end.isoformat(),
                "previous_period_start": start.isoformat(),
                "previous_period_end": mid.isoformat(),
                "current_snoozes": cls._count_in_window(
                    snooze_df, "created_at", mid, end
                ),
                "previous_snoozes": cls._count_in_window(
                    snooze_df, "created_at", start, mid
                ),
                "current_wakes": cls._count_in_window(
                    wake_df, "triggered_at", mid, end
                ),
                "previous_wakes": cls._count_in_window(
                    wake_df, "triggered_at", start, mid
                ),
            }
        )

        if (
            result["current_wakes"] < SNOOZE_REDUCTION_MIN_WAKES
            or result["previous_wakes"] < SNOOZE_REDUCTION_MIN_WAKES
        ):
            return result

        current_rate = round(result["current_snoozes"] / result["current_wakes"], 4)
        previous_rate = round(result["previous_snoozes"] / result["previous_wakes"], 4)
        result.update(
            {
                "current_snoozes_per_wake": current_rate,
                "previous_snoozes_per_wake": previous_rate,
                "absolute_change_per_wake": round(current_rate - previous_rate, 4),
                "direction": cls._compare_trend(
                    current_rate, previous_rate, lower_is_better=True
                ),
            }
        )

        if previous_rate == 0.0:
            # A percentage change off a zero baseline is undefined; the
            # absolute change still carries the real movement.
            result["status"] = "no_baseline_snoozes"
            return result

        result["status"] = "ok"
        result["reduction_rate"] = float(
            np.round(((previous_rate - current_rate) / previous_rate) * 100.0, 2)
        )
        return result

    @staticmethod
    def _empty_snooze_reduction(
        period_days: int = SNOOZE_REDUCTION_DEFAULT_PERIOD_DAYS,
    ) -> Dict[str, Any]:
        return {
            "period_days": int(period_days),
            "current_period_start": None,
            "current_period_end": None,
            "previous_period_start": None,
            "previous_period_end": None,
            "current_snoozes": 0,
            "previous_snoozes": 0,
            "current_wakes": 0,
            "previous_wakes": 0,
            "current_snoozes_per_wake": None,
            "previous_snoozes_per_wake": None,
            "absolute_change_per_wake": None,
            "reduction_rate": None,
            "direction": "insufficient_data",
            "status": "insufficient_data",
            "min_wakes_required": SNOOZE_REDUCTION_MIN_WAKES,
        }

    @staticmethod
    def _count_in_window(
        df: pd.DataFrame,
        column: str,
        lower: pd.Timestamp,
        upper: pd.Timestamp,
    ) -> int:
        """Rows with ``lower < df[column] <= upper``."""
        if df is None or df.empty or column not in df.columns:
            return 0
        moments = pd.to_datetime(df[column], utc=True, errors="coerce")
        return int(((moments > lower) & (moments <= upper)).sum())

    @staticmethod
    def _int_column(df: pd.DataFrame, column: str, default: int = 0) -> pd.Series:
        """Integer view of ``column``, substituting ``default`` when absent."""
        if column not in df.columns:
            return pd.Series([default] * len(df), index=df.index, dtype="int64")
        return (
            pd.to_numeric(df[column], errors="coerce")
            .fillna(default)
            .astype("int64")
        )

    @classmethod
    def analyze_verification_accuracy(
        cls,
        wake_df: pd.DataFrame,
        *,
        min_decisions: int = VERIFICATION_MIN_DECISIONS,
    ) -> Dict[str, Any]:
        """How accurately the wake-up verification gate decided each cycle.

        This is neither the dismissal success rate (how often a cycle ended
        verified) nor challenge accuracy (how often an answer was right). It
        audits the *decision*. Every finished cycle stores how many
        consecutive correct answers the gate collected and how many it
        required, so each outcome can be replayed against the contract::

            verified  <=>  consecutive_correct >= challenges_required

        A cycle marked verified without meeting the requirement is a **false
        verification** — the gate released a user it never confirmed. A cycle
        that met the requirement but was not marked verified is a **missed
        verification**. ``accuracy_rate`` is the share of decisions that agree
        with the contract.

        ``first_pass_rate`` is the second half of the picture: how often a
        confirmed wake needed no wrong answer at all. A gate that only reaches
        the right verdict after several retries is confirming on weaker
        evidence than one that reaches it immediately.

        Scope, stated honestly: this measures the verification gate against
        the evidence it collected. Whether the user stayed awake afterwards is
        not observable anywhere in the data model, so it is not claimed here.
        """
        floor = max(1, int(min_decisions or 1))
        result: Dict[str, Any] = {
            "decisions": 0,
            "verified": 0,
            "rejected": 0,
            "correct_decisions": 0,
            "accuracy_rate": None,
            "false_verifications": 0,
            "missed_verifications": 0,
            "first_pass_verifications": 0,
            "first_pass_rate": None,
            "answers_recorded": 0,
            "avg_answers_per_verification": None,
            "avg_wrong_answers_per_verification": None,
            "min_decisions_required": floor,
            "status": "insufficient_data",
            "integrity": "unknown",
        }
        if wake_df is None or wake_df.empty:
            return result

        decided = wake_df
        if "dismissed_at" in wake_df.columns:
            settled = pd.to_datetime(
                wake_df["dismissed_at"], utc=True, errors="coerce"
            )
            decided = wake_df[settled.notna()]
        if decided.empty:
            return result

        required = cls._int_column(decided, "challenges_required", 1).clip(lower=1)
        correct = cls._int_column(decided, "consecutive_correct", 0).clip(lower=0)
        wrong = cls._int_column(decided, "failed_attempts", 0).clip(lower=0)
        verified = (
            decided["verified"].fillna(False).astype(bool)
            if "verified" in decided.columns
            else pd.Series([False] * len(decided), index=decided.index)
        )

        met_requirement = correct >= required
        agrees = verified == met_requirement

        result["decisions"] = int(len(decided))
        result["verified"] = int(verified.sum())
        result["rejected"] = int((~verified).sum())
        result["correct_decisions"] = int(agrees.sum())
        result["false_verifications"] = int((verified & ~met_requirement).sum())
        result["missed_verifications"] = int((~verified & met_requirement).sum())
        result["first_pass_verifications"] = int((verified & (wrong == 0)).sum())
        # One answer per correct step plus one per wrong/timed-out try.
        result["answers_recorded"] = int((correct + wrong)[verified].sum())

        if result["decisions"] < floor:
            return result

        result["status"] = "ok"
        result["accuracy_rate"] = float(
            np.round(result["correct_decisions"] / result["decisions"] * 100.0, 2)
        )
        result["integrity"] = (
            "consistent" if result["correct_decisions"] == result["decisions"]
            else "inconsistent"
        )
        if result["verified"]:
            result["first_pass_rate"] = float(
                np.round(
                    result["first_pass_verifications"] / result["verified"] * 100.0, 2
                )
            )
            result["avg_answers_per_verification"] = float(
                np.round(result["answers_recorded"] / result["verified"], 2)
            )
            result["avg_wrong_answers_per_verification"] = float(
                np.round(int(wrong[verified].sum()) / result["verified"], 2)
            )
        return result

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
        if profile is not None:
            from app.services.day_streak import DayStreakService

            streak = DayStreakService.read_stored_streak(profile)

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
    def analyze_sleep_patterns(
        cls,
        wake_df: pd.DataFrame,
        activity_index: Optional[pd.DatetimeIndex],
        profile: Optional[UserProfile],
        sleep_records: Optional[Sequence[Dict[str, Optional[datetime]]]] = None,
    ) -> Dict[str, Any]:
        """Sleep sessions built from stored history, recorded data first.

        A night is ``recorded`` when the user logged its start via a
        ``sleep.started`` event; its end is then either a logged ``sleep.ended``
        or the verified wake, both of which are real recorded instants.

        A night is ``estimated`` only as a fallback, where the start is the last
        interaction before the wake. Estimated nights are labelled as such on
        every row and summarised separately, so an inferred duration is never
        presented as recorded sleep. Nights with neither a record nor a
        bounding interaction report a null duration rather than a guess.

        ``target_sleep_hours`` is the only profile-sourced value and is used
        solely to express measured duration as a surplus/deficit.
        """
        sleep_hours = 8.0
        if profile is not None:
            try:
                sleep_hours = float(
                    getattr(profile, "sleep_duration_hours", 8.0) or 8.0
                )
            except (TypeError, ValueError):
                sleep_hours = 8.0

        base: Dict[str, Any] = {
            "nights_observed": 0,
            "nights_with_duration": 0,
            "nights_recorded": 0,
            "nights_estimated": 0,
            "has_recorded_sleep": False,
            "duration_source": "none",
            "avg_recorded_duration_hours": None,
            "avg_estimated_duration_hours": None,
            "avg_sleep_duration_hours": None,
            "std_sleep_duration_hours": None,
            "min_sleep_duration_hours": None,
            "max_sleep_duration_hours": None,
            "avg_bedtime": None,
            "bedtime_std_minutes": None,
            "avg_wake_time": None,
            "wake_time_std_minutes": None,
            "avg_mid_sleep": None,
            "social_jetlag_minutes": None,
            "schedule_regularity_score": 0.0,
            "duration_consistency_score": 0.0,
            "target_sleep_hours": round(sleep_hours, 2),
            "avg_sleep_debt_hours": None,
            "short_sleep_nights": 0,
            "long_sleep_nights": 0,
            "avg_wake_latency_seconds": None,
            "weekday": cls._sleep_segment([]),
            "weekend": cls._sleep_segment([]),
            "recent_7d_avg_duration_hours": None,
            "previous_7d_avg_duration_hours": None,
            "trend": "insufficient_data",
            "bedtime_coverage_rate": 0.0,
            "has_open_session": False,
            "nights": [],
        }

        verified = cls._verified_wakes(wake_df)
        daily = None
        if not verified.empty:
            verified = verified.copy()
            verified["day"] = verified["dismissed_at"].dt.normalize()
            # The first verified wake of a day is the morning wake; later ones
            # are naps or secondary alarms and must not overwrite the night.
            daily = verified.sort_values("dismissed_at").drop_duplicates(
                subset="day", keep="first"
            )

        acts = activity_index
        if acts is None or len(acts) == 0:
            acts = pd.DatetimeIndex([], tz="UTC")
        elif acts.tz is None:
            acts = acts.tz_localize("UTC")

        min_gap = pd.Timedelta(hours=SLEEP_MIN_DURATION_HOURS)
        max_gap = pd.Timedelta(hours=SLEEP_MAX_DURATION_HOURS)

        wake_moments = (
            pd.DatetimeIndex(daily["dismissed_at"]).sort_values()
            if daily is not None
            else pd.DatetimeIndex([], tz="UTC")
        )
        latency_by_wake = (
            {
                row.dismissed_at: getattr(row, "time_to_dismiss_seconds", None)
                for row in daily.itertuples(index=False)
            }
            if daily is not None
            else {}
        )

        nights: List[Dict[str, Any]] = []
        covered_days = set()
        open_session = False
        recent_cutoff = pd.Timestamp.now(tz="UTC") - max_gap

        # ── Recorded sessions win ────────────────────────────────────
        for record in sorted(
            sleep_records or [], key=lambda r: r["start"]
        ):
            start = cls._as_utc_ts(record.get("start"))
            if start is None:
                continue
            start = pd.Timestamp(start)
            finish = record.get("end")
            end_source = "sleep_record"

            if finish is None:
                # Close the night on the verified wake the user actually had
                finish = cls._first_wake_between(
                    wake_moments, start + min_gap, start + max_gap
                )
                end_source = "verified_wake"
            if finish is None:
                # A start with no end yet — the user is still asleep
                open_session = open_session or start >= recent_cutoff
                continue

            finish = pd.Timestamp(cls._as_utc_ts(finish))
            duration_hours = float((finish - start).total_seconds() / 3600.0)
            if not (
                SLEEP_MIN_DURATION_HOURS <= duration_hours <= SLEEP_MAX_DURATION_HOURS
            ):
                continue

            day_ts = finish.normalize()
            if day_ts in covered_days:
                continue
            covered_days.add(day_ts)
            nights.append(
                cls._build_night(
                    day_ts,
                    finish,
                    start,
                    duration_hours,
                    source=SLEEP_SOURCE_RECORDED,
                    end_source=end_source,
                    latency=latency_by_wake.get(finish),
                )
            )

        # ── Estimated fallback for days without a recorded session ───
        if daily is not None:
            for row in daily.itertuples(index=False):
                wake_at = row.dismissed_at
                if pd.isna(wake_at):
                    continue
                day_ts = pd.Timestamp(row.day)
                if day_ts in covered_days:
                    continue
                covered_days.add(day_ts)

                onset = None
                if len(acts):
                    position = (
                        int(acts.searchsorted(wake_at - min_gap, side="right")) - 1
                    )
                    if position >= 0 and acts[position] > (wake_at - max_gap):
                        onset = acts[position]

                duration_hours = None
                if onset is not None:
                    measured = float((wake_at - onset).total_seconds() / 3600.0)
                    if (
                        SLEEP_MIN_DURATION_HOURS
                        <= measured
                        <= SLEEP_MAX_DURATION_HOURS
                    ):
                        duration_hours = measured
                    else:
                        onset = None

                nights.append(
                    cls._build_night(
                        day_ts,
                        wake_at,
                        onset,
                        duration_hours,
                        source=SLEEP_SOURCE_ESTIMATED,
                        end_source="verified_wake",
                        latency=getattr(row, "time_to_dismiss_seconds", None),
                    )
                )

        if not nights:
            return {**base, "has_open_session": open_session}

        nights.sort(key=lambda n: n["date"])
        return {
            **base,
            **cls._summarize_nights(nights, sleep_hours),
            "has_open_session": open_session,
        }

    @classmethod
    def _build_night(
        cls,
        day_ts: pd.Timestamp,
        sleep_end: pd.Timestamp,
        sleep_start: Optional[pd.Timestamp],
        duration_hours: Optional[float],
        *,
        source: str,
        end_source: str,
        latency: Any = None,
    ) -> Dict[str, Any]:
        wake_minutes = float(
            sleep_end.hour * 60 + sleep_end.minute + sleep_end.second / 60.0
        )
        bedtime_minutes = None
        mid_sleep_minutes = None
        if sleep_start is not None and duration_hours is not None:
            bedtime_minutes = float(
                sleep_start.hour * 60 + sleep_start.minute + sleep_start.second / 60.0
            )
            mid_sleep_minutes = (bedtime_minutes + duration_hours * 30.0) % 1440.0

        latency_seconds = (
            int(latency) if latency is not None and not pd.isna(latency) else None
        )

        return {
            "date": day_ts.date().isoformat(),
            "weekday": WEEKDAY_LABELS[int(day_ts.dayofweek)],
            "is_weekend": bool(int(day_ts.dayofweek) >= 5),
            "source": source,
            "sleep_end_source": end_source,
            "wake_time": cls._minutes_to_hhmm(wake_minutes),
            "wake_minutes": round(wake_minutes, 1),
            "bedtime": cls._minutes_to_hhmm(bedtime_minutes),
            "bedtime_minutes": (
                round(bedtime_minutes, 1) if bedtime_minutes is not None else None
            ),
            "sleep_duration_hours": (
                round(duration_hours, 2) if duration_hours is not None else None
            ),
            "mid_sleep_minutes": (
                round(mid_sleep_minutes, 1) if mid_sleep_minutes is not None else None
            ),
            "wake_latency_seconds": latency_seconds,
        }

    @staticmethod
    def _first_wake_between(
        wake_moments: pd.DatetimeIndex,
        earliest: pd.Timestamp,
        latest: pd.Timestamp,
    ) -> Optional[pd.Timestamp]:
        """First verified wake inside a recorded session's plausible end range."""
        if wake_moments is None or len(wake_moments) == 0:
            return None
        position = int(wake_moments.searchsorted(earliest, side="left"))
        if position >= len(wake_moments):
            return None
        candidate = wake_moments[position]
        return candidate if candidate <= latest else None

    @classmethod
    def _summarize_nights(
        cls, nights: List[Dict[str, Any]], sleep_hours: float
    ) -> Dict[str, Any]:
        def _durations(rows: Sequence[Dict[str, Any]]) -> np.ndarray:
            return np.array(
                [
                    r["sleep_duration_hours"]
                    for r in rows
                    if r["sleep_duration_hours"] is not None
                ],
                dtype=float,
            )

        recorded = [n for n in nights if n["source"] == SLEEP_SOURCE_RECORDED]
        estimated = [n for n in nights if n["source"] == SLEEP_SOURCE_ESTIMATED]

        durations = _durations(nights)
        recorded_durations = _durations(recorded)
        estimated_durations = _durations(estimated)

        bedtimes = np.array(
            [n["bedtime_minutes"] for n in nights if n["bedtime_minutes"] is not None],
            dtype=float,
        )
        wake_times = np.array([n["wake_minutes"] for n in nights], dtype=float)
        mids = np.array(
            [
                n["mid_sleep_minutes"]
                for n in nights
                if n["mid_sleep_minutes"] is not None
            ],
            dtype=float,
        )
        latencies = np.array(
            [
                n["wake_latency_seconds"]
                for n in nights
                if n["wake_latency_seconds"] is not None
            ],
            dtype=float,
        )

        bed_std = cls._circular_std_minutes(bedtimes)
        wake_std = cls._circular_std_minutes(wake_times)
        scatter = [s for s in (bed_std, wake_std) if s is not None]
        regularity = 0.0
        if scatter:
            regularity = float(
                np.clip(
                    100.0
                    - float(np.mean(scatter)) * (100.0 / REGULARITY_ZERO_AT_STD_MINUTES),
                    0.0,
                    100.0,
                )
            )

        duration_std = float(np.std(durations)) if durations.size else None
        duration_consistency = 0.0
        if duration_std is not None:
            duration_consistency = float(
                np.clip(
                    100.0
                    - duration_std * (100.0 / DURATION_CONSISTENCY_ZERO_AT_STD_HOURS),
                    0.0,
                    100.0,
                )
            )

        avg_duration = float(np.mean(durations)) if durations.size else None
        recent_avg, previous_avg, trend = cls._sleep_duration_trend(nights, sleep_hours)

        if recorded_durations.size and estimated_durations.size:
            duration_source = "mixed"
        elif recorded_durations.size:
            duration_source = SLEEP_SOURCE_RECORDED
        elif estimated_durations.size:
            duration_source = SLEEP_SOURCE_ESTIMATED
        else:
            duration_source = "none"

        return {
            "nights_observed": len(nights),
            "nights_with_duration": int(durations.size),
            "nights_recorded": len(recorded),
            "nights_estimated": len(estimated),
            "has_recorded_sleep": bool(recorded),
            "duration_source": duration_source,
            "avg_recorded_duration_hours": (
                round(float(np.mean(recorded_durations)), 2)
                if recorded_durations.size
                else None
            ),
            "avg_estimated_duration_hours": (
                round(float(np.mean(estimated_durations)), 2)
                if estimated_durations.size
                else None
            ),
            "avg_sleep_duration_hours": (
                round(avg_duration, 2) if avg_duration is not None else None
            ),
            "std_sleep_duration_hours": (
                round(duration_std, 2) if duration_std is not None else None
            ),
            "min_sleep_duration_hours": (
                round(float(np.min(durations)), 2) if durations.size else None
            ),
            "max_sleep_duration_hours": (
                round(float(np.max(durations)), 2) if durations.size else None
            ),
            "avg_bedtime": cls._minutes_to_hhmm(cls._circular_mean_minutes(bedtimes)),
            "bedtime_std_minutes": (
                round(bed_std, 1) if bed_std is not None else None
            ),
            "avg_wake_time": cls._minutes_to_hhmm(
                cls._circular_mean_minutes(wake_times)
            ),
            "wake_time_std_minutes": (
                round(wake_std, 1) if wake_std is not None else None
            ),
            "avg_mid_sleep": cls._minutes_to_hhmm(cls._circular_mean_minutes(mids)),
            "social_jetlag_minutes": cls._social_jetlag_minutes(nights),
            "schedule_regularity_score": round(regularity, 2),
            "duration_consistency_score": round(duration_consistency, 2),
            "avg_sleep_debt_hours": (
                round(sleep_hours - avg_duration, 2)
                if avg_duration is not None
                else None
            ),
            "short_sleep_nights": (
                int((durations < SHORT_SLEEP_HOURS).sum()) if durations.size else 0
            ),
            "long_sleep_nights": (
                int((durations > LONG_SLEEP_HOURS).sum()) if durations.size else 0
            ),
            "avg_wake_latency_seconds": (
                round(float(np.mean(latencies)), 1) if latencies.size else None
            ),
            "weekday": cls._sleep_segment([n for n in nights if not n["is_weekend"]]),
            "weekend": cls._sleep_segment([n for n in nights if n["is_weekend"]]),
            "recent_7d_avg_duration_hours": recent_avg,
            "previous_7d_avg_duration_hours": previous_avg,
            "trend": trend,
            "bedtime_coverage_rate": round(
                (int(durations.size) / len(nights)) * 100.0, 2
            ),
            "nights": nights,
        }

    @classmethod
    def analyze_productivity_correlation(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        sleep_patterns: Optional[Dict[str, Any]],
        days: int,
    ) -> Dict[str, Any]:
        """Correlate recorded wake/habit behaviour with productivity outcomes.

        One observation per day on which the user actually did something; days
        with no recorded interaction are skipped rather than counted as zeros,
        because an absent day is missing data and not a bad day.

        Each pair is scored with Pearson (linear) and Spearman (monotonic)
        coefficients and a Fisher-z two-sided p-value. Pairs without enough
        complete observations, or where a series never varies, report that
        explicitly instead of a fabricated number.
        """
        frame = cls._daily_behaviour_outcome_frame(
            snooze_df,
            wake_df,
            challenge_df,
            preferred_minutes,
            sleep_patterns,
            days,
        )

        pairs: List[Dict[str, Any]] = []
        for spec in _CORRELATION_SPECS:
            result = corr.correlate(
                frame.get(spec.behavior, []),
                frame.get(spec.outcome, []),
                min_pairs=CORRELATION_MIN_PAIRS,
            )
            pairs.append(
                {
                    "id": spec.id,
                    "behavior": spec.behavior,
                    "behavior_label": spec.behavior_label,
                    "outcome": spec.outcome,
                    "outcome_label": spec.outcome_label,
                    "expected_direction": spec.expected_direction,
                    **result,
                    "interpretation": cls._correlation_interpretation(result, spec),
                }
            )

        findings = corr.significant_findings(pairs)
        computed = [p for p in pairs if p["status"] == "ok"]
        days_analyzed = len(frame.get("date", []))

        if findings:
            insights = [f["interpretation"] for f in findings[:3]]
        elif computed:
            insights = [
                "No statistically significant link between wake behaviour and "
                f"productivity outcomes yet across {days_analyzed} active days."
            ]
        else:
            insights = [
                "Not enough paired daily history to run correlation analysis — "
                f"at least {CORRELATION_MIN_PAIRS} active days with both a wake "
                "event and challenge attempts are needed."
            ]

        return {
            "status": "ok" if computed else "insufficient_data",
            "method": {
                "coefficients": ["pearson", "spearman"],
                "significance_test": "fisher_z",
                "alpha": corr.ALPHA,
                "min_pairs": CORRELATION_MIN_PAIRS,
            },
            "window_days": days,
            "days_analyzed": days_analyzed,
            "pairs": pairs,
            "significant_findings": [f["id"] for f in findings],
            "strongest": findings[0] if findings else None,
            "insights": insights,
        }

    @classmethod
    def sleep_and_correlation_snapshot(
        cls,
        db: Session,
        user_id: int,
        days: int,
        *,
        window_end: Optional[datetime] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Sleep patterns + productivity correlation for one window.

        Same math as ``get_overview`` but skips the trend series, so the
        productivity dashboard can carry correlations without paying for the
        whole behavioural bundle.
        """
        now = window_end or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        days = max(1, min(int(days or DEFAULT_DAYS), 365))
        start = now - timedelta(days=days)
        history_start = start - timedelta(hours=SLEEP_MAX_DURATION_HOURS)

        profile = (
            db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        )
        snooze_df = cls._load_snooze_df(db, user_id, start, window_end=now)
        wake_df = cls._load_wake_df(db, user_id, start, window_end=now)
        challenge_df = cls._load_challenge_df(db, user_id, start, window_end=now)
        activity_index = cls._load_activity_index(
            db, user_id, history_start, window_end=now
        )
        sleep_records = cls._load_sleep_records(
            db, user_id, history_start, window_end=now
        )

        preferred = cls._preferred_wake_minutes(profile)
        sleep_patterns = cls.analyze_sleep_patterns(
            wake_df, activity_index, profile, sleep_records
        )
        correlation = cls.analyze_productivity_correlation(
            snooze_df, wake_df, challenge_df, preferred, sleep_patterns, days
        )
        return sleep_patterns, correlation

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
        days: int = MONTHLY_DAYS,
    ) -> Dict[str, Any]:
        """Daily habit-score proxies + current SSOT habit score.

        ``current_habit_score`` is recalculated from lifetime verified wake
        events when ``db``/``user_id`` are provided; otherwise profile
        counters (or empty defaults) are used.

        ``days`` sizes the daily proxy series so the caller's reporting window
        (7 / 30 / 90) is the window that gets charted.
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

        span = max(1, min(int(days or MONTHLY_DAYS), 365))
        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=span - 1)
        index = pd.date_range(start, end, freq="D", tz="UTC")

        verified = cls._verified_wakes(wake_df)
        series: List[Dict[str, Any]] = []
        scores: List[float] = []

        for day in index:
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
        recent_avg = 0.0
        previous_avg = 0.0
        if len(active_scores) >= 2:
            mid = len(active_scores) // 2
            first_avg = float(np.mean(active_scores[:mid])) if mid else 0.0
            second_avg = float(np.mean(active_scores[mid:]))
            trend = cls._compare_trend(second_avg, first_avg, lower_is_better=False)
            avg_score = float(np.round(float(np.mean(active_scores)), 2))
            recent_avg = float(np.round(second_avg, 2))
            previous_avg = float(np.round(first_avg, 2))
        elif len(active_scores) == 1:
            trend = "stable"
            avg_score = float(np.round(active_scores[0], 2))
            recent_avg = avg_score
        else:
            trend = "insufficient_data"
            avg_score = 0.0

        return {
            "current_habit_score": current["habit_score"],
            "current_breakdown": current["breakdown"],
            "weights": current["weights"],
            "avg_proxy_score": avg_score,
            "trend": trend,
            "trend_detail": {
                "direction": trend,
                "recent_avg": recent_avg,
                "previous_avg": previous_avg,
                "change": float(np.round(recent_avg - previous_avg, 2)),
                "active_days": len(active_scores),
                "window_days": span,
            },
            "series": series,
        }

    # ── Data loaders ────────────────────────────────────────────────────

    @classmethod
    def _load_snooze_df(
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        window_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        filters = [
            AlarmSnoozeEvent.user_id == user_id,
            AlarmSnoozeEvent.created_at >= window_start,
        ]
        if window_end is not None:
            end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
            filters.append(AlarmSnoozeEvent.created_at <= end)
        rows = db.query(AlarmSnoozeEvent).filter(*filters).all()
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
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        window_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        filters = [
            AlarmWakeEvent.user_id == user_id,
            AlarmWakeEvent.triggered_at >= window_start,
        ]
        if window_end is not None:
            end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
            filters.append(AlarmWakeEvent.triggered_at <= end)
        rows = db.query(AlarmWakeEvent).filter(*filters).all()
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
                    "wakefulness_score",
                    "challenges_required",
                    "consecutive_correct",
                    "failed_attempts",
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
                    "wakefulness_score": r.wakefulness_score,
                    "challenges_required": r.challenges_required or 1,
                    "consecutive_correct": r.consecutive_correct or 0,
                    "failed_attempts": r.failed_attempts or 0,
                }
            )
        df = pd.DataFrame(data)
        df["triggered_at"] = pd.to_datetime(df["triggered_at"], utc=True)
        df["dismissed_at"] = pd.to_datetime(df["dismissed_at"], utc=True)
        return df

    @classmethod
    def _load_challenge_df(
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        window_end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        filters = [
            AlarmChallengeLog.user_id == user_id,
            AlarmChallengeLog.created_at >= window_start,
        ]
        if window_end is not None:
            end = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
            filters.append(AlarmChallengeLog.created_at <= end)
        rows = db.query(AlarmChallengeLog).filter(*filters).all()
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

    @classmethod
    def _load_activity_index(
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        window_end: Optional[datetime] = None,
    ) -> pd.DatetimeIndex:
        """Sorted timestamps of everything we ever observed this user doing.

        Only used to *estimate* a sleep start when the user has not recorded
        one: the last activity before a verified wake is the most recent moment
        they are known to have been awake. Issued as a single UNION so the
        dashboard read path does not grow a query per source.
        """
        end = None
        if window_end is not None:
            end = (
                window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
            )

        statements = []
        for column, owner in (
            (AnalyticsEvent.created_at, AnalyticsEvent.user_id),
            (AlarmChallengeLog.created_at, AlarmChallengeLog.user_id),
            (AlarmSnoozeEvent.created_at, AlarmSnoozeEvent.user_id),
        ):
            statement = select(column.label("ts")).where(
                owner == user_id, column >= window_start
            )
            if end is not None:
                statement = statement.where(column <= end)
            statements.append(statement)

        rows = db.execute(union_all(*statements)).all()
        stamps = [cls._as_utc_ts(row[0]) for row in rows if row[0] is not None]
        if not stamps:
            return pd.DatetimeIndex([], tz="UTC")
        return pd.DatetimeIndex(pd.to_datetime(stamps, utc=True)).sort_values()

    @classmethod
    def _load_sleep_records(
        cls,
        db: Session,
        user_id: int,
        window_start: datetime,
        window_end: Optional[datetime] = None,
    ) -> List[Dict[str, Optional[datetime]]]:
        """Sleep sessions the user actually logged.

        Built from ``sleep.started`` / ``sleep.ended`` analytics events, which
        clients ingest through the existing ``POST /analytics/events`` path.
        Each start is paired with the first unconsumed end after it; a start
        with no end yields ``{"end": None}`` so the caller can close the night
        on the verified wake instead of inventing a duration.
        """
        filters = [
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.event_type.in_(SLEEP_RECORD_EVENT_TYPES),
            AnalyticsEvent.created_at >= window_start,
        ]
        if window_end is not None:
            end = (
                window_end.replace(tzinfo=None) if window_end.tzinfo else window_end
            )
            filters.append(AnalyticsEvent.created_at <= end)

        rows = db.query(AnalyticsEvent).filter(*filters).all()

        starts: List[datetime] = []
        ends: List[datetime] = []
        for row in rows:
            moment = cls._sleep_event_moment(row)
            if moment is None:
                continue
            if row.event_type == SLEEP_STARTED_EVENT:
                starts.append(moment)
            else:
                ends.append(moment)

        starts.sort()
        ends.sort()

        sessions: List[Dict[str, Optional[datetime]]] = []
        cursor = 0
        for start in starts:
            while cursor < len(ends) and ends[cursor] <= start:
                cursor += 1
            finish: Optional[datetime] = None
            if cursor < len(ends):
                candidate = ends[cursor]
                hours = (candidate - start).total_seconds() / 3600.0
                if SLEEP_MIN_DURATION_HOURS <= hours <= SLEEP_MAX_DURATION_HOURS:
                    finish = candidate
                    cursor += 1
            sessions.append({"start": start, "end": finish})
        return sessions

    @classmethod
    def _sleep_event_moment(cls, row: AnalyticsEvent) -> Optional[datetime]:
        """Timestamp of a sleep record, honouring an explicitly backfilled time.

        Lets a client log last night's sleep after the fact by sending
        ``event_data: {"at": "<iso8601>"}`` instead of relying on ingest time.
        """
        data = row.event_data if isinstance(row.event_data, dict) else {}
        for key in ("at", "started_at", "ended_at", "timestamp"):
            raw = data.get(key)
            if not raw:
                continue
            try:
                parsed = pd.to_datetime(raw, utc=True)
            except (ValueError, TypeError):
                continue
            if pd.isna(parsed):
                continue
            return parsed.to_pydatetime()
        return cls._as_utc_ts(row.created_at)


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

    @classmethod
    def _sleep_segment(cls, nights: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate a subset of nights (e.g. weekdays) into a summary block."""
        durations = [
            n["sleep_duration_hours"]
            for n in nights
            if n.get("sleep_duration_hours") is not None
        ]
        wake_minutes = [
            n["wake_minutes"] for n in nights if n.get("wake_minutes") is not None
        ]
        bedtimes = [
            n["bedtime_minutes"] for n in nights if n.get("bedtime_minutes") is not None
        ]
        return {
            "nights": len(nights),
            "avg_duration_hours": (
                round(float(np.mean(durations)), 2) if durations else None
            ),
            "avg_wake_time": cls._minutes_to_hhmm(
                cls._circular_mean_minutes(np.array(wake_minutes, dtype=float))
            )
            if wake_minutes
            else None,
            "avg_bedtime": cls._minutes_to_hhmm(
                cls._circular_mean_minutes(np.array(bedtimes, dtype=float))
            )
            if bedtimes
            else None,
        }

    @classmethod
    def _social_jetlag_minutes(
        cls, nights: Sequence[Dict[str, Any]]
    ) -> Optional[float]:
        """Weekend vs weekday mid-sleep shift, the standard social-jetlag measure."""
        weekend = [
            n["mid_sleep_minutes"]
            for n in nights
            if n["is_weekend"] and n.get("mid_sleep_minutes") is not None
        ]
        weekday = [
            n["mid_sleep_minutes"]
            for n in nights
            if not n["is_weekend"] and n.get("mid_sleep_minutes") is not None
        ]
        if not weekend or not weekday:
            return None
        we = cls._circular_mean_minutes(np.array(weekend, dtype=float))
        wd = cls._circular_mean_minutes(np.array(weekday, dtype=float))
        if we is None or wd is None:
            return None
        delta = cls._circular_minute_delta(np.array([we], dtype=float), wd)[0]
        return round(abs(float(delta)), 1)

    @classmethod
    def _sleep_duration_trend(
        cls, nights: Sequence[Dict[str, Any]], target_hours: float
    ) -> Tuple[Optional[float], Optional[float], str]:
        """Recent vs previous week, scored on distance from the target duration."""
        today = pd.Timestamp.now(tz="UTC").normalize().date()
        recent_cut = today - timedelta(days=7)
        previous_cut = today - timedelta(days=14)

        recent: List[float] = []
        previous: List[float] = []
        for night in nights:
            hours = night.get("sleep_duration_hours")
            if hours is None:
                continue
            night_date = date.fromisoformat(night["date"])
            if night_date > recent_cut:
                recent.append(float(hours))
            elif previous_cut < night_date <= recent_cut:
                previous.append(float(hours))

        if not recent or not previous:
            return (
                round(float(np.mean(recent)), 2) if recent else None,
                round(float(np.mean(previous)), 2) if previous else None,
                "insufficient_data",
            )

        recent_avg = float(np.mean(recent))
        previous_avg = float(np.mean(previous))
        trend = cls._compare_trend(
            abs(recent_avg - target_hours),
            abs(previous_avg - target_hours),
            lower_is_better=True,
        )
        return round(recent_avg, 2), round(previous_avg, 2), trend

    @classmethod
    def _daily_behaviour_outcome_frame(
        cls,
        snooze_df: pd.DataFrame,
        wake_df: pd.DataFrame,
        challenge_df: pd.DataFrame,
        preferred_minutes: Optional[float],
        sleep_patterns: Optional[Dict[str, Any]],
        days: int,
    ) -> Dict[str, List[Any]]:
        """Aligned per-day behaviour predictors and productivity outcomes.

        Missing metrics are ``nan`` so ``correlation.clean_pairs`` drops only
        the affected pair, not the whole day.
        """
        end = pd.Timestamp.now(tz="UTC").normalize()
        start = end - pd.Timedelta(days=max(1, days) - 1)
        index = pd.date_range(start, end, freq="D", tz="UTC")

        verified = cls._verified_wakes(wake_df)
        # Baseline is the user's own observed wake time, not a stated preference
        baseline = (
            cls._circular_mean_minutes(verified["wake_minutes"].to_numpy(dtype=float))
            if not verified.empty
            else None
        )

        sleep_by_date = {
            n["date"]: n["sleep_duration_hours"]
            for n in (sleep_patterns or {}).get("nights", [])
            if n.get("sleep_duration_hours") is not None
        }

        columns = (
            "date",
            "snooze_count",
            "schedule_deviation_minutes",
            "wake_latency_seconds",
            "habit_score",
            "sleep_duration_hours",
            "challenge_accuracy",
            "avg_response_seconds",
            "points_earned",
            "wakefulness",
        )
        frame: Dict[str, List[Any]] = {name: [] for name in columns}

        for day in index:
            day_end = day + pd.Timedelta(days=1)
            day_snoozes = (
                snooze_df[
                    (snooze_df["created_at"] >= day)
                    & (snooze_df["created_at"] < day_end)
                ]
                if not snooze_df.empty
                else snooze_df
            )
            day_wakes = (
                verified[
                    (verified["dismissed_at"] >= day)
                    & (verified["dismissed_at"] < day_end)
                ]
                if not verified.empty
                else verified
            )
            day_challenges = (
                challenge_df[
                    (challenge_df["created_at"] >= day)
                    & (challenge_df["created_at"] < day_end)
                ]
                if not challenge_df.empty
                else challenge_df
            )

            # A day with no recorded interaction is missing data, not a zero
            if not (len(day_wakes) or len(day_snoozes) or len(day_challenges)):
                continue

            snooze_count = float(len(day_snoozes))
            if not len(day_snoozes) and len(day_wakes):
                snooze_count = float(
                    day_wakes["snooze_count_at_dismiss"].astype(float).sum()
                )

            deviation = np.nan
            if len(day_wakes) and baseline is not None:
                deviations = cls._circular_minute_delta(
                    day_wakes["wake_minutes"].to_numpy(dtype=float), baseline
                )
                deviation = float(np.mean(np.abs(deviations)))

            latency = np.nan
            wakefulness = np.nan
            if len(day_wakes):
                times = day_wakes["time_to_dismiss_seconds"].dropna()
                if len(times):
                    latency = float(times.mean())
                if "wakefulness_score" in day_wakes:
                    scores = day_wakes["wakefulness_score"].dropna()
                    if len(scores):
                        wakefulness = float(scores.astype(float).mean())

            proxy = cls._daily_habit_proxy(
                day_wakes, day_snoozes, day_challenges, preferred_minutes
            )
            habit = float(proxy["habit_score"]) if proxy["has_activity"] else np.nan

            attempts = int(len(day_challenges))
            accuracy = np.nan
            points = np.nan
            response = np.nan
            if attempts:
                accuracy = float(
                    day_challenges["is_correct"].sum() / attempts * 100.0
                )
                points = float(
                    day_challenges["points_earned"].astype(float).sum()
                )
                solved = day_challenges[day_challenges["is_correct"] == True]  # noqa: E712
                if len(solved):
                    response = float(
                        solved["time_taken_seconds"].astype(float).mean()
                    )

            iso_date = day.date().isoformat()
            frame["date"].append(iso_date)
            frame["snooze_count"].append(snooze_count)
            frame["schedule_deviation_minutes"].append(deviation)
            frame["wake_latency_seconds"].append(latency)
            frame["habit_score"].append(habit)
            frame["sleep_duration_hours"].append(
                sleep_by_date.get(iso_date, np.nan)
            )
            frame["challenge_accuracy"].append(accuracy)
            frame["avg_response_seconds"].append(response)
            frame["points_earned"].append(points)
            frame["wakefulness"].append(wakefulness)

        return frame

    @staticmethod
    def _correlation_interpretation(
        result: Dict[str, Any], spec: "_CorrelationSpec"
    ) -> str:
        behavior = spec.behavior_label
        outcome = spec.outcome_label
        status = result["status"]

        if status == "insufficient_data":
            return (
                f"Only {result['n']} of the {result['min_pairs']} paired days "
                f"needed are available, so {behavior} cannot yet be related to "
                f"{outcome}."
            )
        if status == "no_variance":
            return (
                f"Either {behavior} or {outcome} never changed across "
                f"{result['n']} days, so no relationship is measurable."
            )

        r = result["pearson_r"]
        stats = f"r={r}, rho={result['spearman_rho']}, p={result['p_value']}, n={result['n']}"
        if not result["significant"]:
            return (
                f"No statistically significant relationship between {behavior} "
                f"and {outcome} ({stats})."
            )

        movement = "higher" if r > 0 else "lower"
        agreement = (
            "consistent with expectation"
            if result["direction"] == spec.expected_direction
            else "opposite to the usual pattern"
        )
        return (
            f"{result['strength'].replace('_', ' ').capitalize()} "
            f"{result['direction']} link: more {behavior} goes with {movement} "
            f"{outcome} ({stats}) — {agreement}."
        )

    @staticmethod
    def _circular_mean_minutes(minutes: np.ndarray) -> Optional[float]:
        """Mean clock time on a 24h circle (23:50 and 00:10 average to 00:00)."""
        values = np.asarray(minutes, dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return None
        angles = values * (2.0 * math.pi / 1440.0)
        sin_mean = float(np.mean(np.sin(angles)))
        cos_mean = float(np.mean(np.cos(angles)))
        if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
            # Perfectly opposed times cancel out; no meaningful mean exists
            return None
        return float(
            (math.atan2(sin_mean, cos_mean) * 1440.0 / (2.0 * math.pi)) % 1440.0
        )

    @staticmethod
    def _circular_std_minutes(minutes: np.ndarray) -> Optional[float]:
        """Circular standard deviation in minutes, from the mean resultant length."""
        values = np.asarray(minutes, dtype=float)
        values = values[np.isfinite(values)]
        if values.size == 0:
            return None
        if values.size == 1:
            return 0.0
        angles = values * (2.0 * math.pi / 1440.0)
        resultant = math.hypot(
            float(np.mean(np.sin(angles))), float(np.mean(np.cos(angles)))
        )
        resultant = min(1.0, max(1e-12, resultant))
        return float(
            math.sqrt(-2.0 * math.log(resultant)) * 1440.0 / (2.0 * math.pi)
        )

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

        reduction = snooze.get("reduction") or {}
        if reduction.get("status") == "ok":
            rate = reduction["reduction_rate"]
            movement = "down" if rate > 0 else "up"
            insights.append(
                f"Snoozes per wake-up are {movement} "
                f"{abs(rate)}% versus the previous "
                f"{reduction['period_days']} days "
                f"({reduction['previous_snoozes_per_wake']} → "
                f"{reduction['current_snoozes_per_wake']} per wake)."
            )

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
                f"Current habit score is {format_habit_score(habit['current_habit_score'])}; "
                f"30-day proxy trend is {habit['trend']}."
            )
        return insights
