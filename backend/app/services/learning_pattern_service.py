"""
Learning-pattern analysis and engagement optimization.

Both analyzers are pure functions over already-loaded ORM rows. Callers pass
history they have usually already fetched, so wiring these into the challenge
pipeline costs no extra round trips, and every rule below is unit testable
without a database.

``LearningPatternService`` turns raw attempt history into a learning profile:
per-type mastery and learning slope, per-difficulty competence, an estimated
optimal difficulty, a time-of-day performance profile, and an overall learning
state derived from a least-squares trend plus block-variance consistency —
not a single before/after comparison.

``EngagementService`` turns the same history plus wake outcomes into an
engagement score and, crucially, *directives* the challenge engine applies at
runtime: a bounded difficulty bias and a novelty boost that re-weights
challenge-type selection toward under-served types.

Both degrade to explicit ``insufficient_data`` with neutral directives when
history is too thin, so a new user's experience is unchanged.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.challenge_service import (
    DIFFICULTY_LEVELS,
    SELECTABLE_CHALLENGE_TYPES,
)

# ── Learning-pattern thresholds ───────────────────────────────────────

#: Attempts loaded for pattern analysis (bounded so the query stays cheap).
LEARNING_WINDOW = 120

#: Minimum attempts before any learning state other than insufficient_data.
MIN_PATTERN_SAMPLE = 8
#: Minimum attempts before a per-type / per-difficulty verdict is reported.
MIN_TYPE_SAMPLE = 4
MIN_LEVEL_SAMPLE = 4
#: Minimum attempts in an hour bucket before it can be a peak / low hour.
MIN_HOUR_SAMPLE = 3

#: Accuracy band the engine aims to keep the user inside.
TARGET_ACCURACY_LOW = 60.0
TARGET_ACCURACY_HIGH = 85.0

#: Trend magnitude (percentage points per 10 attempts) treated as meaningful.
SLOPE_SIGNIFICANCE_PP = 5.0
#: Consistency below this with a flat trend means erratic, not plateaued.
#: Block accuracies are bounded to [0, 100], so their population stdev peaks at
#: 50 and consistency only ever spans [50, 100] — the threshold must sit inside
#: that range to be reachable at all.
CONSISTENCY_VOLATILE = 60.0
#: A flat trend at or above this accuracy, with enough data, is a plateau.
PLATEAU_ACCURACY = 80.0
PLATEAU_MIN_SAMPLE = 15
#: Mirror of the plateau rule: flat at or below this accuracy is not "steady",
#: it is stuck. Without it a user failing everything reads as holding steady.
STRUGGLING_ACCURACY_CEILING = 40.0

#: Attempts per block when measuring consistency across time.
CONSISTENCY_BLOCK = 5
MIN_CONSISTENCY_BLOCKS = 3

# ── Adaptation effectiveness ──────────────────────────────────────────
# Every attempt stores the difficulty that was actually served, so a change
# between consecutive attempts is an observable adaptation event. Effectiveness
# is judged on whether the user moved *toward the target band*, not on whether
# accuracy rose: raising difficulty for a user sitting at 100% is supposed to
# pull accuracy down, and that is a success, not a regression.

#: Attempts on each side of a difficulty change used to judge it.
ADAPTATION_WINDOW = 5
#: Attempts required on each side before an event can be judged at all.
ADAPTATION_MIN_SIDE_SAMPLE = 3
#: Judged events required before an overall verdict is issued.
ADAPTATION_MIN_EVENTS = 3
#: Movement smaller than this many percentage points is noise, not an effect.
ADAPTATION_TOLERANCE_PP = 5.0
#: Most recent events echoed back for inspection.
ADAPTATION_RECENT_EVENTS = 5

# ── Engagement thresholds ─────────────────────────────────────────────

#: Wake events loaded for engagement analysis.
ENGAGEMENT_WAKE_WINDOW = 30
#: Minimum attempts before engagement directives may be non-neutral.
ENGAGEMENT_MIN_SAMPLE = 6
#: Windows used by the activity signals.
ENGAGEMENT_RECENT_DAYS = 14
ENGAGEMENT_ACTIVE_DAYS = 7
#: Attempts inspected for type repetition / novelty starvation.
NOVELTY_SPAN = 12
#: Share of the novelty span held by one type before novelty is boosted.
NOVELTY_REPEAT_PRESSURE = 0.5
#: Upper bound on the novelty boost handed to type selection.
MAX_NOVELTY_BOOST = 0.6

DISENGAGED_SCORE = 35.0
AT_RISK_SCORE = 50.0
ENGAGED_SCORE = 70.0
THRIVING_SCORE = 85.0

# ── Engagement improvement ────────────────────────────────────────────
# The engagement score is a point-in-time reading. Improvement re-scores the
# same stored history as it stood one period earlier and compares the two, so
# the delta comes from real attempts and wake events, not a stored snapshot.

#: One comparison period; matches the window the score's activity signals use.
ENGAGEMENT_PERIOD_DAYS = ENGAGEMENT_RECENT_DAYS
#: Score movement smaller than this many points is noise, not a trend.
ENGAGEMENT_IMPROVEMENT_TOLERANCE = 5.0

#: Guardrails for raising difficulty on a bored/plateaued user.
BORED_MIN_ACCURACY = 85.0
BORED_MAX_ABANDON_RATE = 0.15
#: Guardrails for easing difficulty on a struggling/disengaged user.
STRUGGLING_ABANDON_RATE = 0.4
STRUGGLING_ACCURACY = 45.0

_NEUTRAL_DIRECTIVES = {
    "difficulty_bias": 0,
    "novelty_boost": 0.0,
    "underused_types": [],
    "reason": "Not enough history yet — challenge selection is unbiased.",
}


# ── Shared helpers ────────────────────────────────────────────────────


def _resolve_tz(tz_name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _norm_type(raw: Any) -> str:
    value = str(raw or "unknown").strip().lower()
    if value == "word" or value.startswith("word"):
        return "word_game"
    return value or "unknown"


def _norm_difficulty(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    return value if value in DIFFICULTY_LEVELS else "unknown"


def _as_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _created_at(log: Any) -> Optional[datetime]:
    """Attempt timestamp as an aware UTC datetime (stored values are naive)."""
    value = getattr(log, "created_at", None)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _chronological(logs: Optional[Sequence[Any]]) -> List[Any]:
    """Oldest-first copy. Callers hand us newest-first query results."""
    rows = [log for log in (logs or []) if log is not None]
    rows.sort(key=lambda log: (_created_at(log) or datetime.min.replace(tzinfo=timezone.utc)))
    return rows


def _wake_moment(event: Any) -> Optional[datetime]:
    """When a wake event happened, as an aware UTC datetime."""
    for attr in ("triggered_at", "dismissed_at", "created_at"):
        value = getattr(event, attr, None)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _at_or_before(moment: Optional[datetime], cutoff: datetime) -> bool:
    return moment is not None and moment <= cutoff


def _count_between(rows: Sequence[Any], lower: datetime, upper: datetime) -> int:
    """Rows whose timestamp falls in ``(lower, upper]``."""
    return sum(
        1
        for m in (_created_at(r) for r in rows)
        if m is not None and lower < m <= upper
    )


def _active_days(rows: Sequence[Any], lower: datetime, upper: datetime) -> int:
    """Distinct UTC days with at least one attempt in ``(lower, upper]``."""
    return len(
        {
            m.date()
            for m in (_created_at(r) for r in rows)
            if m is not None and lower < m <= upper
        }
    )


def _least_squares_slope(values: Sequence[float]) -> float:
    """Slope of ``values`` against their index, via ordinary least squares."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    numerator = 0.0
    denominator = 0.0
    for i, y in enumerate(values):
        dx = i - mean_x
        numerator += dx * (y - mean_y)
        denominator += dx * dx
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _accuracy_slope_pp(outcomes: Sequence[int]) -> float:
    """Trend in accuracy, expressed as percentage points per 10 attempts."""
    return round(_least_squares_slope([float(o) for o in outcomes]) * 10 * 100, 2)


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


def _consistency(outcomes: Sequence[int]) -> Optional[float]:
    """100 minus the spread of block accuracies; None when data is too thin.

    Raw 0/1 outcomes have a variance fixed by their mean, so measuring spread
    across consecutive blocks is what actually separates "erratic" from
    "steady" at the same overall accuracy. The result spans [50, 100].
    """
    blocks: List[float] = []
    for start in range(0, len(outcomes), CONSISTENCY_BLOCK):
        chunk = outcomes[start:start + CONSISTENCY_BLOCK]
        if len(chunk) >= max(2, CONSISTENCY_BLOCK // 2):
            blocks.append(100.0 * sum(chunk) / len(chunk))
    if len(blocks) < MIN_CONSISTENCY_BLOCKS:
        return None
    return round(max(0.0, 100.0 - statistics.pstdev(blocks)), 1)


def _mastery_label(accuracy: float, attempts: int) -> str:
    if accuracy >= 85.0 and attempts >= 8:
        return "mastered"
    if accuracy >= TARGET_ACCURACY_HIGH - 15.0:
        return "proficient"
    if accuracy >= 50.0:
        return "developing"
    return "novice"


def _band_distance(accuracy: float) -> float:
    """How far ``accuracy`` sits outside the target band, in points.

    Zero means the user is inside the band the engine aims for, which is the
    outcome adaptation exists to produce.
    """
    return round(
        max(TARGET_ACCURACY_LOW - accuracy, accuracy - TARGET_ACCURACY_HIGH, 0.0), 1
    )


def _mean(values: Sequence[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


def _run_before(
    levels: Sequence[str], outcomes: Sequence[int], index: int, window: int
) -> List[int]:
    """Outcomes of the contiguous run at the old difficulty, ending at index-1."""
    level = levels[index - 1]
    run: List[int] = []
    i = index - 1
    while i >= 0 and levels[i] == level and len(run) < window:
        run.append(outcomes[i])
        i -= 1
    return run


def _run_after(
    levels: Sequence[str], outcomes: Sequence[int], index: int, window: int
) -> List[int]:
    """Outcomes of the contiguous run at the new difficulty, starting at index."""
    level = levels[index]
    run: List[int] = []
    i = index
    while i < len(levels) and levels[i] == level and len(run) < window:
        run.append(outcomes[i])
        i += 1
    return run


def _direction_summary(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    judged = len(events)
    effective = sum(1 for e in events if e["verdict"] == "effective")
    return {
        "judged": judged,
        "effective": effective,
        "ineffective": sum(1 for e in events if e["verdict"] == "ineffective"),
        "neutral": sum(1 for e in events if e["verdict"] == "neutral"),
        "effectiveness_rate": _pct(effective, judged),
        "avg_accuracy_before": _mean([e["accuracy_before"] for e in events]),
        "avg_accuracy_after": _mean([e["accuracy_after"] for e in events]),
        "avg_band_distance_change": _mean(
            [e["band_distance_change"] for e in events]
        ),
    }


def _summarize_adaptation(
    events: List[Dict[str, Any]],
    detected: int,
    window: int,
    min_side_sample: int,
) -> Dict[str, Any]:
    judged = len(events)
    effective = sum(1 for e in events if e["verdict"] == "effective")
    ineffective = sum(1 for e in events if e["verdict"] == "ineffective")
    distance_change = _mean([e["band_distance_change"] for e in events])

    if judged < ADAPTATION_MIN_EVENTS:
        verdict = "insufficient_data"
    elif distance_change is not None and distance_change < -ADAPTATION_TOLERANCE_PP:
        verdict = "effective"
    elif distance_change is not None and distance_change > ADAPTATION_TOLERANCE_PP:
        verdict = "ineffective"
    else:
        verdict = "neutral"

    return {
        "window": window,
        "min_side_sample": min_side_sample,
        "min_events": ADAPTATION_MIN_EVENTS,
        "target_band": {"low": TARGET_ACCURACY_LOW, "high": TARGET_ACCURACY_HIGH},
        # Difficulty changes seen in the history, judged or not.
        "adaptations_detected": detected,
        "adaptations_judged": judged,
        "effective": effective,
        "ineffective": ineffective,
        "neutral": judged - effective - ineffective,
        "effectiveness_rate": _pct(effective, judged),
        "avg_accuracy_before": _mean([e["accuracy_before"] for e in events]),
        "avg_accuracy_after": _mean([e["accuracy_after"] for e in events]),
        "avg_band_distance_before": _mean(
            [e["band_distance_before"] for e in events]
        ),
        "avg_band_distance_after": _mean([e["band_distance_after"] for e in events]),
        # Negative = adaptation pulled the user closer to the target band.
        "avg_band_distance_change": distance_change,
        "by_direction": {
            "harder": _direction_summary(
                [e for e in events if e["direction"] == "harder"]
            ),
            "easier": _direction_summary(
                [e for e in events if e["direction"] == "easier"]
            ),
        },
        "recent_events": events[-ADAPTATION_RECENT_EVENTS:][::-1],
        "verdict": verdict,
    }


class LearningPatternService:
    """Derive a learning profile from a user's challenge attempt history."""

    @staticmethod
    def analyze(
        logs: Optional[Sequence[Any]],
        *,
        tz_name: str = "UTC",
    ) -> Dict[str, Any]:
        """Build the learning profile for ``logs`` (newest-first accepted)."""
        rows = _chronological(logs)
        total = len(rows)

        if total == 0:
            return LearningPatternService._empty(
                "No attempts logged yet — learning analysis starts after your "
                "first few challenges."
            )

        outcomes = [1 if getattr(log, "is_correct", False) else 0 for log in rows]
        times = [max(0, _as_int(getattr(log, "time_taken_seconds", 0))) for log in rows]
        correct = sum(outcomes)
        accuracy = _pct(correct, total)

        accuracy_slope = _accuracy_slope_pp(outcomes)
        speed_slope = round(_least_squares_slope([float(t) for t in times]) * 10, 2)
        consistency = _consistency(outcomes)

        by_type = LearningPatternService._by_type(rows)
        by_difficulty = LearningPatternService._by_difficulty(rows)
        time_of_day = LearningPatternService._time_of_day(rows, tz_name, accuracy)
        optimal = LearningPatternService._optimal_difficulty(by_difficulty)

        state, state_label = LearningPatternService._learning_state(
            total=total,
            accuracy=accuracy,
            accuracy_slope=accuracy_slope,
            consistency=consistency,
        )

        strengths = sorted(
            (t for t in by_type.values() if t["attempts"] >= MIN_TYPE_SAMPLE
             and t["accuracy"] >= TARGET_ACCURACY_HIGH),
            key=lambda t: t["accuracy"],
            reverse=True,
        )
        focus = sorted(
            (t for t in by_type.values() if t["attempts"] >= MIN_TYPE_SAMPLE
             and t["accuracy"] < TARGET_ACCURACY_LOW),
            key=lambda t: t["accuracy"],
        )

        return {
            "sample_size": total,
            "has_enough_data": total >= MIN_PATTERN_SAMPLE,
            "accuracy": accuracy,
            "learning_state": state,
            "learning_state_label": state_label,
            # Positive = accuracy climbing; negative = regressing.
            "accuracy_trend_pp_per_10": accuracy_slope,
            # Negative = getting faster.
            "speed_trend_seconds_per_10": speed_slope,
            "consistency": consistency,
            "by_type": by_type,
            "by_difficulty": by_difficulty,
            "optimal_difficulty": optimal,
            "adaptation_effectiveness": (
                LearningPatternService.analyze_adaptation_effectiveness(rows)
            ),
            "time_of_day": time_of_day,
            "mastered_types": [t["type"] for t in strengths],
            "focus_types": [t["type"] for t in focus],
        }

    @staticmethod
    def analyze_adaptation_effectiveness(
        logs: Optional[Sequence[Any]],
        *,
        window: int = ADAPTATION_WINDOW,
        min_side_sample: int = ADAPTATION_MIN_SIDE_SAMPLE,
    ) -> Dict[str, Any]:
        """Did changing the served difficulty move the user toward the band?

        Each attempt records the difficulty it was actually served at, so a
        change between consecutive attempts is an observable adaptation event.
        For each event the accuracy of the attempts immediately before (old
        difficulty) is compared with the attempts immediately after (new
        difficulty), and success is measured as a *reduction in distance from
        the target band* — not as a rise in accuracy, which would score every
        difficulty increase as a failure by construction.

        Accepts newest-first or oldest-first rows. Events without
        ``min_side_sample`` attempts on both sides are counted but not judged.
        """
        rows = [
            log
            for log in _chronological(logs)
            if _norm_difficulty(getattr(log, "difficulty", None)) != "unknown"
        ]
        levels = [_norm_difficulty(getattr(log, "difficulty", None)) for log in rows]
        outcomes = [1 if getattr(log, "is_correct", False) else 0 for log in rows]

        events: List[Dict[str, Any]] = []
        detected = 0
        for i in range(1, len(rows)):
            if levels[i] == levels[i - 1]:
                continue
            detected += 1
            before = _run_before(levels, outcomes, i, window)
            after = _run_after(levels, outcomes, i, window)
            if len(before) < min_side_sample or len(after) < min_side_sample:
                continue

            accuracy_before = _pct(sum(before), len(before))
            accuracy_after = _pct(sum(after), len(after))
            distance_before = _band_distance(accuracy_before)
            distance_after = _band_distance(accuracy_after)
            change = round(distance_after - distance_before, 1)

            if change < -ADAPTATION_TOLERANCE_PP:
                verdict = "effective"
            elif change > ADAPTATION_TOLERANCE_PP:
                verdict = "ineffective"
            else:
                verdict = "neutral"

            events.append(
                {
                    "at": (_created_at(rows[i]) or datetime.now(timezone.utc)).isoformat(),
                    "from_difficulty": levels[i - 1],
                    "to_difficulty": levels[i],
                    "direction": (
                        "harder"
                        if DIFFICULTY_LEVELS.index(levels[i])
                        > DIFFICULTY_LEVELS.index(levels[i - 1])
                        else "easier"
                    ),
                    "attempts_before": len(before),
                    "attempts_after": len(after),
                    "accuracy_before": accuracy_before,
                    "accuracy_after": accuracy_after,
                    "band_distance_before": distance_before,
                    "band_distance_after": distance_after,
                    "band_distance_change": change,
                    "verdict": verdict,
                }
            )

        return _summarize_adaptation(events, detected, window, min_side_sample)

    # ── Internals ────────────────────────────────────────────────

    @staticmethod
    def _empty(reason: str) -> Dict[str, Any]:
        return {
            "sample_size": 0,
            "has_enough_data": False,
            "accuracy": 0.0,
            "learning_state": "insufficient_data",
            "learning_state_label": reason,
            "accuracy_trend_pp_per_10": 0.0,
            "speed_trend_seconds_per_10": 0.0,
            "consistency": None,
            "by_type": {},
            "by_difficulty": {},
            "optimal_difficulty": None,
            "adaptation_effectiveness": _summarize_adaptation(
                [], 0, ADAPTATION_WINDOW, ADAPTATION_MIN_SIDE_SAMPLE
            ),
            "time_of_day": {
                "buckets": {}, "peak_hours": [], "low_hours": []
            },
            "mastered_types": [],
            "focus_types": [],
        }

    @staticmethod
    def _by_type(rows: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
        """Per-type accuracy, speed, and an independent learning slope."""
        grouped: Dict[str, List[Any]] = {}
        for log in rows:
            grouped.setdefault(_norm_type(getattr(log, "challenge_type", None)), []).append(log)

        result: Dict[str, Dict[str, Any]] = {}
        for name, group in grouped.items():
            if name in ("unknown", "random"):
                continue
            outcomes = [1 if getattr(log, "is_correct", False) else 0 for log in group]
            times = [max(0, _as_int(getattr(log, "time_taken_seconds", 0))) for log in group]
            attempts = len(group)
            accuracy = _pct(sum(outcomes), attempts)
            slope = _accuracy_slope_pp(outcomes) if attempts >= MIN_TYPE_SAMPLE else 0.0
            result[name] = {
                "type": name,
                "attempts": attempts,
                "accuracy": accuracy,
                "avg_time": round(sum(times) / attempts, 1) if attempts else 0.0,
                "trend_pp_per_10": slope,
                "mastery": (
                    _mastery_label(accuracy, attempts)
                    if attempts >= MIN_TYPE_SAMPLE
                    else "unrated"
                ),
            }
        return result

    @staticmethod
    def _by_difficulty(rows: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
        """Per-level competence across all five difficulty levels seen."""
        grouped: Dict[str, List[Any]] = {}
        for log in rows:
            level = _norm_difficulty(getattr(log, "difficulty", None))
            if level == "unknown":
                continue
            grouped.setdefault(level, []).append(log)

        result: Dict[str, Dict[str, Any]] = {}
        for level, group in grouped.items():
            outcomes = [1 if getattr(log, "is_correct", False) else 0 for log in group]
            times = [max(0, _as_int(getattr(log, "time_taken_seconds", 0))) for log in group]
            attempts = len(group)
            accuracy = _pct(sum(outcomes), attempts)
            result[level] = {
                "difficulty": level,
                "attempts": attempts,
                "accuracy": accuracy,
                "avg_time": round(sum(times) / attempts, 1) if attempts else 0.0,
                "competence": (
                    _mastery_label(accuracy, attempts)
                    if attempts >= MIN_LEVEL_SAMPLE
                    else "unrated"
                ),
            }
        return result

    @staticmethod
    def _optimal_difficulty(
        by_difficulty: Dict[str, Dict[str, Any]]
    ) -> Optional[str]:
        """Hardest level the user still clears at or above the target band.

        Falls back to the easiest level with data when nothing qualifies, so a
        struggling user is pointed down rather than left without a target.
        """
        rated = {
            level: stats for level, stats in by_difficulty.items()
            if stats["attempts"] >= MIN_LEVEL_SAMPLE
        }
        if not rated:
            return None
        for level in reversed(DIFFICULTY_LEVELS):
            stats = rated.get(level)
            if stats and stats["accuracy"] >= TARGET_ACCURACY_LOW:
                return level
        for level in DIFFICULTY_LEVELS:
            if level in rated:
                return level
        return None

    @staticmethod
    def _time_of_day(
        rows: Sequence[Any], tz_name: str, overall_accuracy: float
    ) -> Dict[str, Any]:
        """Accuracy by local hour, and which hours beat / trail the average."""
        tz = _resolve_tz(tz_name)
        buckets: Dict[int, Dict[str, Any]] = {}
        for log in rows:
            moment = _created_at(log)
            if moment is None:
                continue
            hour = moment.astimezone(tz).hour
            bucket = buckets.setdefault(
                hour, {"hour": hour, "attempts": 0, "correct": 0, "total_time": 0}
            )
            bucket["attempts"] += 1
            bucket["correct"] += 1 if getattr(log, "is_correct", False) else 0
            bucket["total_time"] += max(0, _as_int(getattr(log, "time_taken_seconds", 0)))

        peak: List[int] = []
        low: List[int] = []
        for hour, bucket in buckets.items():
            bucket["accuracy"] = _pct(bucket["correct"], bucket["attempts"])
            bucket["avg_time"] = round(bucket["total_time"] / bucket["attempts"], 1)
            del bucket["total_time"]
            if bucket["attempts"] < MIN_HOUR_SAMPLE:
                continue
            if bucket["accuracy"] >= overall_accuracy + 10.0:
                peak.append(hour)
            elif bucket["accuracy"] <= overall_accuracy - 10.0:
                low.append(hour)

        return {
            "buckets": {str(h): b for h, b in sorted(buckets.items())},
            "peak_hours": sorted(peak),
            "low_hours": sorted(low),
        }

    @staticmethod
    def _learning_state(
        *,
        total: int,
        accuracy: float,
        accuracy_slope: float,
        consistency: Optional[float],
    ) -> tuple:
        if total < MIN_PATTERN_SAMPLE:
            return (
                "insufficient_data",
                f"Need {MIN_PATTERN_SAMPLE} attempts to read your learning "
                f"pattern ({total} so far).",
            )
        if accuracy_slope >= SLOPE_SIGNIFICANCE_PP:
            return (
                "improving",
                f"Accuracy is climbing about {accuracy_slope:g} points every "
                f"10 attempts.",
            )
        if accuracy_slope <= -SLOPE_SIGNIFICANCE_PP:
            return (
                "declining",
                f"Accuracy is slipping about {abs(accuracy_slope):g} points "
                f"every 10 attempts.",
            )
        if consistency is not None and consistency < CONSISTENCY_VOLATILE:
            return (
                "volatile",
                "Results swing widely between sessions — consistency, not "
                "difficulty, is the current limit.",
            )
        if accuracy >= PLATEAU_ACCURACY and total >= PLATEAU_MIN_SAMPLE:
            return (
                "plateaued",
                f"Accuracy has settled at {accuracy:g}% with no upward trend — "
                f"ready for a harder level.",
            )
        if accuracy <= STRUGGLING_ACCURACY_CEILING:
            return (
                "struggling",
                f"Accuracy is stuck at {accuracy:g}% with no upward trend — "
                f"the current level is too hard.",
            )
        return ("steady", "Performance is holding steady.")


class EngagementService:
    """Score engagement and emit directives the challenge engine acts on."""

    @staticmethod
    def analyze(
        logs: Optional[Sequence[Any]],
        wake_events: Optional[Sequence[Any]] = None,
        *,
        learning_state: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Build the engagement profile and its runtime directives."""
        rows = _chronological(logs)
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)

        signals = EngagementService._signals(rows, wake_events, moment)
        improvement = EngagementService.analyze_improvement(
            rows, wake_events, now=moment
        )

        if len(rows) < ENGAGEMENT_MIN_SAMPLE:
            return {
                "engagement_score": 0.0,
                "state": "insufficient_data",
                "signals": signals,
                "improvement": improvement,
                "directives": dict(_NEUTRAL_DIRECTIVES),
            }

        score = EngagementService._score(signals)
        state = EngagementService._state(score)
        directives = EngagementService._directives(
            state=state,
            signals=signals,
            learning_state=learning_state,
        )
        return {
            "engagement_score": score,
            "state": state,
            "signals": signals,
            "improvement": improvement,
            "directives": directives,
        }

    @staticmethod
    def analyze_improvement(
        logs: Optional[Sequence[Any]],
        wake_events: Optional[Sequence[Any]] = None,
        *,
        now: Optional[datetime] = None,
        period_days: int = ENGAGEMENT_PERIOD_DAYS,
    ) -> Dict[str, Any]:
        """Engagement now versus engagement one period ago.

        The earlier score is produced by re-running the same scoring function
        over only the history that existed at that instant, so both readings
        use identical weights and the difference is a real change in behaviour.

        A score is only meaningful once ``ENGAGEMENT_MIN_SAMPLE`` attempts
        exist, so an endpoint with less history than that is reported as
        ``insufficient_data`` rather than compared against zero.
        """
        period = max(1, int(period_days or 1))
        end = now or datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        mid = end - timedelta(days=period)
        start = end - timedelta(days=2 * period)

        rows = _chronological(logs)
        events = [e for e in (wake_events or []) if e is not None]

        previous_rows = [r for r in rows if _at_or_before(_created_at(r), mid)]
        # Wake events with no timestamp cannot be proven to have existed then,
        # so they are left out of the earlier reading rather than assumed.
        previous_events = [e for e in events if _at_or_before(_wake_moment(e), mid)]

        result = {
            "period_days": period,
            "current_period_start": mid.isoformat(),
            "current_period_end": end.isoformat(),
            "previous_period_start": start.isoformat(),
            "previous_period_end": mid.isoformat(),
            "current_attempts": _count_between(rows, mid, end),
            "previous_attempts": _count_between(rows, start, mid),
            "current_active_days": _active_days(rows, mid, end),
            "previous_active_days": _active_days(rows, start, mid),
            "min_sample": ENGAGEMENT_MIN_SAMPLE,
            "current_score": None,
            "previous_score": None,
            "current_state": "insufficient_data",
            "previous_state": "insufficient_data",
            "change": None,
            "improvement_rate": None,
            "direction": "insufficient_data",
            "status": "insufficient_data",
        }

        if (
            len(rows) < ENGAGEMENT_MIN_SAMPLE
            or len(previous_rows) < ENGAGEMENT_MIN_SAMPLE
        ):
            return result

        current_score = EngagementService._score(
            EngagementService._signals(rows, events, end)
        )
        previous_score = EngagementService._score(
            EngagementService._signals(previous_rows, previous_events, mid)
        )
        change = round(current_score - previous_score, 1)

        if change > ENGAGEMENT_IMPROVEMENT_TOLERANCE:
            direction = "improving"
        elif change < -ENGAGEMENT_IMPROVEMENT_TOLERANCE:
            direction = "declining"
        else:
            direction = "stable"

        result.update(
            {
                "current_score": current_score,
                "previous_score": previous_score,
                "current_state": EngagementService._state(current_score),
                "previous_state": EngagementService._state(previous_score),
                "change": change,
                # Relative movement; undefined against a zero baseline.
                "improvement_rate": (
                    round((change / previous_score) * 100, 1)
                    if previous_score
                    else None
                ),
                "direction": direction,
                "status": "ok",
            }
        )
        return result

    # ── Internals ────────────────────────────────────────────────

    @staticmethod
    def _signals(
        rows: Sequence[Any],
        wake_events: Optional[Sequence[Any]],
        now: datetime,
    ) -> Dict[str, Any]:
        recent_cutoff = now - timedelta(days=ENGAGEMENT_RECENT_DAYS)
        active_cutoff = now - timedelta(days=ENGAGEMENT_ACTIVE_DAYS)

        stamps = [m for m in (_created_at(log) for log in rows) if m is not None]
        attempts_recent = sum(1 for m in stamps if m >= recent_cutoff)
        active_days = len({m.date() for m in stamps if m >= active_cutoff})
        days_since_last = (
            round((now - max(stamps)).total_seconds() / 86400.0, 2)
            if stamps else None
        )

        tail = list(rows)[-10:]
        recent_accuracy = _pct(
            sum(1 for log in tail if getattr(log, "is_correct", False)), len(tail)
        ) if tail else 0.0
        avg_failed = (
            round(sum(max(0, _as_int(getattr(log, "failed_attempts", 0)))
                      for log in tail) / len(tail), 2)
            if tail else 0.0
        )

        events = [e for e in (wake_events or []) if e is not None]
        abandoned = sum(
            1 for e in events
            if str(getattr(e, "dismiss_method", "") or "").lower() == "abandoned"
            or not bool(getattr(e, "verified", False))
        )
        snoozes = [max(0, _as_int(getattr(e, "snooze_count_at_dismiss", 0))) for e in events]
        abandon_rate = round(abandoned / len(events), 3) if events else 0.0
        avg_snoozes = round(sum(snoozes) / len(snoozes), 2) if snoozes else 0.0

        span = [_norm_type(getattr(log, "challenge_type", None))
                for log in list(rows)[-NOVELTY_SPAN:]]
        span = [t for t in span if t not in ("unknown", "random")]
        counts: Dict[str, int] = {}
        for name in span:
            counts[name] = counts.get(name, 0) + 1
        repeat_pressure = (
            round(max(counts.values()) / len(span), 3) if span else 0.0
        )
        selectable = [ct.value for ct in SELECTABLE_CHALLENGE_TYPES]
        underused = sorted(selectable, key=lambda name: (counts.get(name, 0), name))

        return {
            "total_attempts": len(rows),
            "attempts_recent_window": attempts_recent,
            "active_days_last_7": active_days,
            "days_since_last_attempt": days_since_last,
            "recent_accuracy": recent_accuracy,
            "avg_failed_attempts": avg_failed,
            "wake_events": len(events),
            "abandon_rate": abandon_rate,
            "avg_snoozes_per_wake": avg_snoozes,
            "distinct_recent_types": len(counts),
            "repeat_pressure": repeat_pressure,
            "underused_types": underused[:3],
        }

    @staticmethod
    def _score(signals: Dict[str, Any]) -> float:
        """Weighted 0-100 engagement score from the activity signals."""
        # Regularity (30) — showing up on distinct days matters most.
        regularity = min(1.0, signals["active_days_last_7"] / 5.0) * 30.0

        # Recency (20) — decays to zero after a week of silence.
        days_since = signals["days_since_last_attempt"]
        if days_since is None:
            recency = 0.0
        else:
            recency = max(0.0, 1.0 - (days_since / 7.0)) * 20.0

        # Follow-through (25) — abandoned wakes are the strongest churn signal.
        follow_through = (1.0 - min(1.0, signals["abandon_rate"])) * 25.0

        # Momentum (15) — recent accuracy, floored so a bad patch is not fatal.
        momentum = max(0.0, min(1.0, signals["recent_accuracy"] / 100.0)) * 15.0

        # Variety (10) — a monotonous mix predicts drop-off.
        variety = min(1.0, signals["distinct_recent_types"] / 4.0) * 10.0

        return round(
            regularity + recency + follow_through + momentum + variety, 1
        )

    @staticmethod
    def _state(score: float) -> str:
        if score >= THRIVING_SCORE:
            return "thriving"
        if score >= ENGAGED_SCORE:
            return "engaged"
        if score >= AT_RISK_SCORE:
            return "steady"
        if score >= DISENGAGED_SCORE:
            return "at_risk"
        return "disengaged"

    @staticmethod
    def _directives(
        *,
        state: str,
        signals: Dict[str, Any],
        learning_state: Optional[str],
    ) -> Dict[str, Any]:
        """Translate engagement into bounded, explainable engine actions."""
        bias = 0
        reasons: List[str] = []

        struggling = (
            signals["abandon_rate"] >= STRUGGLING_ABANDON_RATE
            or signals["recent_accuracy"] < STRUGGLING_ACCURACY
            or learning_state == "struggling"
        )
        bored = (
            learning_state == "plateaued"
            and signals["recent_accuracy"] >= BORED_MIN_ACCURACY
            and signals["abandon_rate"] <= BORED_MAX_ABANDON_RATE
        )

        if state in ("disengaged", "at_risk") and struggling:
            bias = -1
            reasons.append(
                "Easing difficulty one level to rebuild momentum after "
                "repeated struggles."
            )
        elif state in ("engaged", "thriving") and bored:
            bias = 1
            reasons.append(
                "Raising difficulty one level — accuracy has plateaued at a "
                "high level with strong follow-through."
            )

        novelty = 0.0
        # Collected separately: at exactly NOVELTY_REPEAT_PRESSURE the computed
        # boost is 0, so claiming a variety adjustment would describe an action
        # the engine never takes.
        novelty_reasons: List[str] = []
        if signals["repeat_pressure"] >= NOVELTY_REPEAT_PRESSURE:
            over = signals["repeat_pressure"] - NOVELTY_REPEAT_PRESSURE
            novelty = min(MAX_NOVELTY_BOOST, over * 1.2)
            novelty_reasons.append(
                "Favouring under-served challenge types for variety."
            )
        if state in ("disengaged", "at_risk"):
            novelty = min(MAX_NOVELTY_BOOST, novelty + 0.25)
            novelty_reasons.append(
                "Increasing challenge variety to re-engage after low activity."
            )
        if novelty > 0:
            reasons.extend(novelty_reasons)

        return {
            "difficulty_bias": bias,
            "novelty_boost": round(novelty, 3),
            "underused_types": (
                list(signals["underused_types"]) if novelty > 0 else []
            ),
            "reason": " ".join(reasons) or "Engagement is healthy — no adjustment applied.",
        }
