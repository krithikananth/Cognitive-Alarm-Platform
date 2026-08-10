"""
Personalized Recommendation Engine.

Generates sleep-schedule advice, wake-habit coaching tips, and productivity
suggestions from the user's profile, alarms, wake events, and challenge history.

Recommendations are progress-gated: completed onboarding milestones are hidden,
same-action / topic overlaps are removed (one tip per intent), and only the
next onboarding action is shown at a time. Advanced coaching unlocks as the
user completes wake goals, alarms, verified wakes, challenges, and
productivity goals.

Challenge-focused recommendations are folded in via ChallengeService so callers
get one unified coaching feed.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.models.user import User
from app.schemas.recommendation import (
    DailyPlan,
    RecommendationCategory,
    RecommendationItem,
    RecommendationPriority,
    RecommendationResponse,
    RecommendationSummary,
)
from app.services.challenge_service import ChallengeService
from app.services.day_streak import DayStreakService
from app.services.habit_score import format_habit_score
from app.services.profile_service import ProfileService
from app.services.recommendation_cache import RecommendationCache

WAKE_LOOKBACK = 21
CHALLENGE_LOOKBACK = 40

PRIORITY_RANK = {
    RecommendationPriority.HIGH: 0,
    RecommendationPriority.MEDIUM: 1,
    RecommendationPriority.LOW: 2,
}

# Milestone → recommendation IDs that are "done" once the milestone is complete.
COMPLETED_MILESTONE_IDS: Dict[str, frozenset] = {
    "wake_goal": frozenset({"sleep-set-wake-goal"}),
    "active_alarm": frozenset(
        {"sleep-create-matching-alarm", "wake-arm-alarm"}
    ),
    "verified_wake": frozenset({"wake-getting-started"}),
    "productivity_goals": frozenset(
        {"productivity-set-goals", "productivity-morning-block"}
    ),
    "challenges": frozenset(
        {"challenge-getting_started", "challenge-getting_started-0"}
    ),
}

# Ordered onboarding sequence (first incomplete = next action).
# Each milestone maps to tip id(s) that represent that single next action.
ONBOARDING_SEQUENCE: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("wake_goal", ("sleep-set-wake-goal",)),
    # Prefer create-matching; wake-arm-alarm is a fallback alias for the same action.
    ("active_alarm", ("sleep-create-matching-alarm", "wake-arm-alarm")),
    ("verified_wake", ("wake-getting-started",)),
    ("productivity_goals", ("productivity-set-goals",)),
    ("challenges", ("challenge-getting_started", "challenge-getting_started-0")),
)

# Affirmation / status cards — hidden when actionable coaching exists.
STATUS_AFFIRMATION_IDS = frozenset(
    {
        "sleep-duration-healthy",
        "wake-snooze-excellent",
        "wake-alertness-strong",
        "habit-maintain",
        "productivity-goals-active",
        "challenge-maintain",
    }
)

# Same-action / overlapping advice — keep the single best item per intent.
# Never surface two tips that ask the user to do the same thing
# (e.g. "Create an alarm" + "Arm an alarm" + "Add your first alarm").
ACTION_INTENT_GROUPS: Tuple[frozenset, ...] = (
    # Alarm setup — create / arm / enable are one action.
    frozenset({"sleep-create-matching-alarm", "wake-arm-alarm"}),
    frozenset(
        {
            "wake-reduce-snooze",
            "wake-snooze-discipline",
            "wake-anti-snooze-harder",
            "wake-snooze-excellent",
        }
    ),
    frozenset({"wake-build-consistency", "wake-consistency-improve"}),
    frozenset(
        {"wake-restart-streak", "wake-protect-streak", "wake-grow-streak"}
    ),
    frozenset({"wake-raise-alertness", "wake-alertness-strong"}),
    frozenset({"habit-foundation", "habit-raise-score", "habit-maintain"}),
    frozenset({"productivity-set-goals", "productivity-morning-block"}),
    frozenset(
        {"productivity-stabilize-first", "productivity-use-morning-window"}
    ),
    # Goal templates that share the same morning-work intent.
    frozenset(
        {
            "productivity-goal-exercise",
            "productivity-goal-workout",
            "productivity-goal-fitness",
        }
    ),
    frozenset(
        {
            "productivity-goal-study",
            "productivity-goal-learn",
            "productivity-goal-read",
        }
    ),
    frozenset(
        {"productivity-goal-meditat", "productivity-goal-mindful"}
    ),
    frozenset(
        {
            "productivity-goal-work",
            "productivity-goal-productiv",
            "productivity-goal-focus",
        }
    ),
)

# Backward-compatible alias used by older tests / imports.
TOPIC_GROUPS = ACTION_INTENT_GROUPS

# Onboarding checklist tip IDs (later milestones are suppressed until due).
_ONBOARDING_TIP_IDS: frozenset = frozenset(
    rid for _, ids in ONBOARDING_SEQUENCE for rid in ids
)

GOAL_COACHING: Dict[str, Dict[str, str]] = {
    "exercise": {
        "title": "Anchor workouts to your wake window",
        "detail": (
            "Schedule light movement within 30–60 minutes of waking. "
            "Morning exercise compounds wake-up consistency and energy."
        ),
        "action_hint": "Block a 20-min movement slot after your alarm",
    },
    "workout": {
        "title": "Anchor workouts to your wake window",
        "detail": (
            "Treat your alarm as the start of training day. "
            "Even a short mobility session reduces snooze temptation."
        ),
        "action_hint": "Prep gym clothes the night before",
    },
    "fitness": {
        "title": "Use wake success as your fitness cue",
        "detail": (
            "On on-time wake days, do a minimum viable workout. "
            "Linking fitness to the alarm builds two habits at once."
        ),
        "action_hint": "Define a 10-minute fallback workout",
    },
    "study": {
        "title": "Protect a morning deep-work block",
        "detail": (
            "Your freshest cognitive window is usually the first 90 minutes "
            "after a verified wake. Use it for the hardest study topic."
        ),
        "action_hint": "Pick tomorrow's first study task tonight",
    },
    "learn": {
        "title": "Stack learning onto your morning ritual",
        "detail": (
            "After dismissing the alarm, spend 15 focused minutes on learning "
            "before opening social apps."
        ),
        "action_hint": "Keep study materials next to your phone",
    },
    "read": {
        "title": "Replace snooze with a reading ritual",
        "detail": (
            "If you tend to hit snooze, put a book by the bed and read one "
            "page before standing up — it redirects the urge to delay."
        ),
        "action_hint": "Place a book on your nightstand tonight",
    },
    "write": {
        "title": "Capture one morning writing sprint",
        "detail": (
            "A 10-minute free-write right after wake-up leverages alertness "
            "from cognitive challenges before the day fills up."
        ),
        "action_hint": "Open a blank note as your first post-alarm action",
    },
    "meditat": {
        "title": "Pair meditation with verified wake-up",
        "detail": (
            "After solving your challenge, do 3–5 minutes of breathing before "
            "checking messages. It locks in calm alertness."
        ),
        "action_hint": "Set a 5-minute timer after dismiss",
    },
    "mindful": {
        "title": "Add a mindful minute after dismiss",
        "detail": (
            "A short grounding practice after the alarm reduces relapse into "
            "bed and improves daytime focus."
        ),
        "action_hint": "Practice 10 slow breaths after waking",
    },
    "work": {
        "title": "Front-load your highest-leverage task",
        "detail": (
            "Schedule your most important work item in the first deep-focus "
            "block after waking — before meetings and inbox triage."
        ),
        "action_hint": "Write tomorrow's #1 work task tonight",
    },
    "productiv": {
        "title": "Convert wake streak into output",
        "detail": (
            "Treat consecutive on-time wakes as fuel for a fixed morning "
            "productivity ritual you never skip."
        ),
        "action_hint": "Define a non-negotiable 25-min morning block",
    },
    "focus": {
        "title": "Defend a distraction-free morning hour",
        "detail": (
            "Keep phone in grayscale or Do Not Disturb for the first hour "
            "after wake to protect focus for your goals."
        ),
        "action_hint": "Enable DND until your first focus block ends",
    },
}


class RecommendationService:
    """Builds personalized sleep, wake, habit, and productivity recommendations."""

    @staticmethod
    def generate_recommendations(
        user: User,
        db: Session,
        *,
        categories: Optional[List[RecommendationCategory]] = None,
        limit: Optional[int] = None,
    ) -> RecommendationResponse:
        """Generate a full recommendation feed for the user.

        Results are served from Redis when available. Cache misses and Redis
        outages fall through to the same computation path (logic unchanged).
        """
        cached = RecommendationCache.get(
            user.id, categories=categories, limit=limit
        )
        if cached is not None:
            return cached

        result = RecommendationService._compute_recommendations(
            user, db, categories=categories, limit=limit
        )
        RecommendationCache.set(
            user.id, result, categories=categories, limit=limit
        )
        return result

    @staticmethod
    def _compute_recommendations(
        user: User,
        db: Session,
        *,
        categories: Optional[List[RecommendationCategory]] = None,
        limit: Optional[int] = None,
    ) -> RecommendationResponse:
        """Compute recommendations from DB signals (no cache I/O)."""
        profile = RecommendationService._ensure_profile(user, db)
        alarms = (
            db.query(Alarm)
            .filter(Alarm.user_id == user.id)
            .order_by(Alarm.alarm_time.asc())
            .all()
        )
        wake_events = (
            db.query(AlarmWakeEvent)
            .filter(AlarmWakeEvent.user_id == user.id)
            .order_by(AlarmWakeEvent.triggered_at.desc())
            .limit(WAKE_LOOKBACK)
            .all()
        )
        challenge_logs = (
            db.query(AlarmChallengeLog)
            .filter(AlarmChallengeLog.user_id == user.id)
            .order_by(AlarmChallengeLog.created_at.desc())
            .limit(CHALLENGE_LOOKBACK)
            .all()
        )

        signals = RecommendationService._build_signals(
            profile, alarms, wake_events, challenge_logs, db=db
        )

        items: List[RecommendationItem] = []
        items.extend(RecommendationService._sleep_recommendations(signals))
        items.extend(RecommendationService._wake_recommendations(signals))
        items.extend(RecommendationService._habit_recommendations(signals))
        items.extend(
            RecommendationService._productivity_recommendations(signals)
        )
        items.extend(
            RecommendationService._challenge_recommendations(
                challenge_logs, signals=signals
            )
        )

        progress = RecommendationService._detect_progress(signals)
        signals["progress"] = progress
        items = RecommendationService._finalize_recommendations(items, progress)

        allowed = set(categories) if categories else None
        if allowed is not None:
            items = [i for i in items if i.category in allowed]

        if limit is not None:
            items = items[: max(0, limit)]

        by_category: Dict[str, List[RecommendationItem]] = {
            c.value: [] for c in RecommendationCategory
        }
        for item in items:
            by_category[item.category.value].append(item)

        summary = RecommendationService._build_summary(signals, items)
        insights = RecommendationService._build_insights(signals, items)
        daily_plan = RecommendationService._build_daily_plan(signals, items)

        return RecommendationResponse(
            generated_at=datetime.now(timezone.utc),
            summary=summary,
            insights=insights,
            recommendations=items,
            by_category=by_category,
            daily_plan=daily_plan,
        )

    @staticmethod
    def generate_daily_digest(user: User, db: Session) -> RecommendationResponse:
        """Top daily coaching items (max 5) with a focused daily plan.

        When the user has saved productivity goals, the digest always includes
        at least one personalized productivity recommendation so Dashboard
        "Today's Coaching" surfaces goal-based advice (not only Analytics).
        """
        cached = RecommendationCache.get(user.id, digest=True)
        if cached is not None:
            return cached

        # Compute from uncached full feed so digest shape is independent of
        # any previously filtered cache entries.
        full = RecommendationService._compute_recommendations(user, db)
        top = RecommendationService._ensure_productivity_in_digest(
            full.recommendations,
            goals_count=full.summary.goals_count,
            limit=5,
        )
        by_category: Dict[str, List[RecommendationItem]] = {
            c.value: [] for c in RecommendationCategory
        }
        for item in top:
            by_category[item.category.value].append(item)

        result = RecommendationResponse(
            generated_at=full.generated_at,
            summary=full.summary,
            insights=full.insights[:4],
            recommendations=top,
            by_category=by_category,
            daily_plan=full.daily_plan,
        )
        RecommendationCache.set(user.id, result, digest=True)
        # Also warm the full-feed cache for Analytics / category endpoints.
        RecommendationCache.set(user.id, full)
        return result

    @staticmethod
    def _ensure_productivity_in_digest(
        recommendations: List[RecommendationItem],
        *,
        goals_count: int,
        limit: int = 5,
    ) -> List[RecommendationItem]:
        """Keep top coaching items, guaranteeing a productivity card when goals exist."""
        top = list(recommendations[:limit])
        if goals_count <= 0:
            return top

        if any(r.category == RecommendationCategory.PRODUCTIVITY for r in top):
            return top

        productivity = [
            r
            for r in recommendations
            if r.category == RecommendationCategory.PRODUCTIVITY
        ]
        if not productivity:
            return top

        # Prefer goal-matched / actionable tips over the generic goals summary.
        preferred_ids = {
            "productivity-use-morning-window",
            "productivity-stabilize-first",
            "productivity-streak-leverage",
            "productivity-high-alertness",
            "productivity-ai-tip",
            "productivity-morning-block",
        }
        ranked = sorted(
            productivity,
            key=lambda r: (
                0
                if r.id.startswith("productivity-goal-")
                else 1
                if r.id in preferred_ids
                else 2,
                PRIORITY_RANK.get(r.priority, 9),
                -r.confidence,
            ),
        )
        pick = ranked[0]

        if len(top) < limit:
            top.append(pick)
        else:
            # Drop the lowest-priority tail item to make room.
            top[-1] = pick

        return RecommendationService._dedupe_and_sort(top)

    @staticmethod
    def _ensure_profile(user: User, db: Session) -> UserProfile:
        profile = getattr(user, "profile", None)
        if profile is not None:
            return profile
        from app.models.profile import DifficultyPreference

        profile = (
            db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
        )
        if profile is None:
            profile = UserProfile(
                user_id=user.id,
                sleep_duration_hours=8.0,
                timezone="UTC",
                difficulty_preference=DifficultyPreference.MEDIUM,
                adapted_difficulty=DifficultyPreference.MEDIUM,
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile

    @staticmethod
    def _build_signals(
        profile: UserProfile,
        alarms: List[Alarm],
        wake_events: List[AlarmWakeEvent],
        challenge_logs: List[AlarmChallengeLog],
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        # Habit score must use the lifetime SSOT path (wake replay + puzzle logs)
        # so recommendations agree with dashboard / analytics habit score.
        if db is not None and getattr(profile, "user_id", None) is not None:
            score_data = ProfileService.calculate_habit_score(profile, db=db)
        else:
            puzzle_stats = None
            if challenge_logs:
                puzzle_stats = {
                    "total_puzzle_correct": sum(
                        1 for log in challenge_logs if log.is_correct
                    ),
                    "total_puzzle_attempts": len(challenge_logs),
                }
            score_data = ProfileService.calculate_habit_score(
                profile, events=wake_events, puzzle_stats=puzzle_stats
            )
        habit_score = score_data["habit_score"]

        active_alarms = [a for a in alarms if a.is_active]
        preferred = profile.preferred_wake_time
        duration = float(profile.sleep_duration_hours or 8.0)
        bedtime = (
            RecommendationService._compute_bedtime(preferred, duration)
            if preferred
            else None
        )

        verified = [e for e in wake_events if e.verified]
        # Canonical Day Streak: stored profile value (written only on final
        # wake outcome). Do not overwrite from event-derived counters.
        streak_days = DayStreakService.read_stored_streak(
            profile, db=db, commit=False
        )
        best_streak = int(profile.best_streak or 0)
        from app.services.success_streak import SuccessStreakService

        success_streak = SuccessStreakService.read_stored_streak(profile)
        failure_streak = int(profile.consecutive_failure_streak or 0)

        snooze_events = [
            e
            for e in verified
            if (e.snooze_count_at_dismiss or 0) > 0
            or e.dismiss_method == "snooze_exhausted"
        ]
        snooze_rate = (
            round(len(snooze_events) / len(verified) * 100.0, 1)
            if verified
            else None
        )

        wake_scores = [
            e.wakefulness_score
            for e in verified
            if e.wakefulness_score is not None
        ]
        avg_wake = (
            round(sum(wake_scores) / len(wake_scores), 1) if wake_scores else None
        )
        levels = [e.wakefulness_level for e in verified if e.wakefulness_level]
        avg_level = RecommendationService._dominant_level(levels)

        dismiss_times = [
            e.time_to_dismiss_seconds
            for e in verified
            if e.time_to_dismiss_seconds is not None
        ]
        avg_dismiss = (
            int(round(sum(dismiss_times) / len(dismiss_times)))
            if dismiss_times
            else None
        )

        goals = RecommendationService._normalize_goals(profile.productivity_goals)
        alarm_vs_goal = RecommendationService._alarm_wake_alignment(
            preferred, active_alarms
        )

        challenge_accuracy = None
        if challenge_logs:
            challenge_accuracy = round(
                sum(1 for l in challenge_logs if l.is_correct)
                / len(challenge_logs)
                * 100.0,
                1,
            )

        return {
            "profile": profile,
            "habit_score": habit_score,
            "habit_breakdown": score_data.get("breakdown", {}),
            "preferred_wake_time": preferred,
            "sleep_duration_hours": duration,
            "suggested_bedtime": bedtime,
            "timezone": profile.timezone or "UTC",
            "streak_days": streak_days,
            "best_streak": best_streak,
            "success_streak": success_streak,
            "failure_streak": failure_streak,
            "consistency": min(float(profile.wake_up_consistency_score or 0), 100.0),
            "total_dismissed": profile.total_alarms_dismissed or 0,
            "total_snoozes": profile.total_snoozes or 0,
            "goals": goals,
            "alarms": alarms,
            "active_alarms": active_alarms,
            "wake_events": wake_events,
            "verified_events": verified,
            "snooze_rate": snooze_rate,
            "avg_wakefulness": avg_wake,
            "avg_wakefulness_level": avg_level,
            "avg_dismiss_seconds": avg_dismiss,
            "alarm_alignment": alarm_vs_goal,
            "challenge_accuracy": challenge_accuracy,
            "challenge_logs": challenge_logs,
        }

    @staticmethod
    def _sleep_recommendations(signals: Dict[str, Any]) -> List[RecommendationItem]:
        items: List[RecommendationItem] = []
        preferred: Optional[time] = signals["preferred_wake_time"]
        duration: float = signals["sleep_duration_hours"]
        bedtime: Optional[time] = signals["suggested_bedtime"]
        active = signals["active_alarms"]
        alignment = signals["alarm_alignment"]

        if preferred is None:
            items.append(
                RecommendationItem(
                    id="sleep-set-wake-goal",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.HIGH,
                    title="Set your preferred wake-up time",
                    detail=(
                        "Without a wake goal, the engine cannot tailor bedtime "
                        "or alarm alignment advice. Pick a realistic weekday wake time."
                    ),
                    action_hint="Open Profile → Sleep Schedule",
                    action_path="/profile",
                    confidence=0.95,
                    metrics={"preferred_wake_time": None},
                )
            )
        else:
            wake_str = preferred.strftime("%H:%M")
            bed_str = bedtime.strftime("%H:%M") if bedtime else None
            items.append(
                RecommendationItem(
                    id="sleep-bedtime-anchor",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Aim for lights-out near {bed_str}",
                    detail=(
                        f"With a {duration:g}-hour sleep target and a {wake_str} wake goal, "
                        f"start winding down so you are in bed by ~{bed_str}. "
                        "Keep the hour before bed screen-light and caffeine-free."
                    ),
                    action_hint="Set a bedtime wind-down reminder",
                    action_path="/profile",
                    confidence=0.9,
                    metrics={
                        "preferred_wake_time": wake_str,
                        "suggested_bedtime": bed_str,
                        "sleep_duration_hours": duration,
                    },
                )
            )

        if duration < 7.0:
            items.append(
                RecommendationItem(
                    id="sleep-extend-duration",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.HIGH,
                    title="Increase your sleep target toward 7–9 hours",
                    detail=(
                        f"Your current target is {duration:g} hours. Adults generally "
                        "perform best with 7–9 hours. Short sleep raises snooze risk "
                        "and lowers morning challenge accuracy."
                    ),
                    action_hint="Raise sleep duration in Profile",
                    action_path="/profile",
                    confidence=0.88,
                    metrics={"sleep_duration_hours": duration},
                )
            )
        elif duration > 9.5:
            items.append(
                RecommendationItem(
                    id="sleep-trim-duration",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.LOW,
                    title="Consider a slightly shorter sleep window",
                    detail=(
                        f"A {duration:g}-hour target is above the typical adult range. "
                        "If mornings feel sluggish, try 8–9 hours with a fixed wake time."
                    ),
                    action_hint="Tune sleep duration in Profile",
                    action_path="/profile",
                    confidence=0.65,
                    metrics={"sleep_duration_hours": duration},
                )
            )
        elif 7.0 <= duration <= 9.0:
            items.append(
                RecommendationItem(
                    id="sleep-duration-healthy",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.LOW,
                    title="Your sleep duration target looks healthy",
                    detail=(
                        f"{duration:g} hours sits in the recommended adult range. "
                        "Protect it by keeping bedtime and wake time consistent ±30 minutes."
                    ),
                    action_hint="Keep schedule consistent this week",
                    action_path="/profile",
                    confidence=0.75,
                    metrics={"sleep_duration_hours": duration},
                )
            )

        if preferred and not active:
            items.append(
                RecommendationItem(
                    id="sleep-create-matching-alarm",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.HIGH,
                    title="Create an alarm that matches your wake goal",
                    detail=(
                        f"You want to wake at {preferred.strftime('%H:%M')} but have no "
                        "active alarms. Set one so the recommendation engine can coach "
                        "adherence from real wake events."
                    ),
                    action_hint="Create an alarm",
                    action_path="/alarms",
                    confidence=0.92,
                    metrics={"active_alarms": 0},
                )
            )

        if alignment and alignment.get("delta_minutes") is not None:
            delta = abs(alignment["delta_minutes"])
            if delta >= 45:
                items.append(
                    RecommendationItem(
                        id="sleep-align-alarm",
                        category=RecommendationCategory.SLEEP,
                        priority=RecommendationPriority.HIGH,
                        title="Align your alarm with your preferred wake time",
                        detail=(
                            f"Your earliest active alarm is {alignment['earliest_alarm']} "
                            f"but your wake goal is {alignment['preferred_wake']}. "
                            f"That is a {delta}-minute gap — inconsistency trains your "
                            "body clock to expect conflicting schedules."
                        ),
                        action_hint="Edit alarm time or update wake goal",
                        action_path="/alarms",
                        confidence=0.9,
                        metrics=alignment,
                    )
                )
            elif delta >= 20:
                items.append(
                    RecommendationItem(
                        id="sleep-nudge-alarm-alignment",
                        category=RecommendationCategory.SLEEP,
                        priority=RecommendationPriority.MEDIUM,
                        title="Tighten alarm ↔ wake-goal alignment",
                        detail=(
                            f"Alarm at {alignment['earliest_alarm']} vs goal "
                            f"{alignment['preferred_wake']} ({delta} min apart). "
                            "Aim for under 15 minutes of drift on weekdays."
                        ),
                        action_hint="Nudge alarm or goal closer together",
                        action_path="/profile",
                        confidence=0.8,
                        metrics=alignment,
                    )
                )

        if preferred and preferred.hour < 5 and duration < 7.5:
            items.append(
                RecommendationItem(
                    id="sleep-early-wake-caution",
                    category=RecommendationCategory.SLEEP,
                    priority=RecommendationPriority.MEDIUM,
                    title="Very early wake needs a protected bedtime",
                    detail=(
                        "Waking before 5:00 AM with a short sleep target often causes "
                        "chronic sleep debt. Either move bedtime earlier or soften the "
                        "wake goal on recovery days."
                    ),
                    action_hint="Protect an earlier wind-down",
                    action_path="/profile",
                    confidence=0.78,
                    metrics={
                        "preferred_wake_time": preferred.strftime("%H:%M"),
                        "sleep_duration_hours": duration,
                    },
                )
            )

        return items

    @staticmethod
    def _wake_recommendations(signals: Dict[str, Any]) -> List[RecommendationItem]:
        items: List[RecommendationItem] = []
        verified = signals["verified_events"]
        snooze_rate = signals["snooze_rate"]
        consistency = signals["consistency"]
        streak = signals["streak_days"]
        best = signals["best_streak"]
        avg_wake = signals["avg_wakefulness"]
        avg_level = signals["avg_wakefulness_level"]
        avg_dismiss = signals["avg_dismiss_seconds"]
        active = signals["active_alarms"]

        if not verified:
            preferred: Optional[time] = signals["preferred_wake_time"]
            if active:
                # First verified wake is only actionable once an alarm exists.
                items.append(
                    RecommendationItem(
                        id="wake-getting-started",
                        category=RecommendationCategory.WAKE,
                        priority=RecommendationPriority.HIGH,
                        title="Complete your first verified wake-up",
                        detail=(
                            "Wake coaching unlocks after you dismiss an alarm by solving "
                            "the cognitive challenge. That creates the signals we use for "
                            "personalized habit tips."
                        ),
                        action_hint="Solve the challenge when your alarm rings",
                        action_path="/alarms",
                        confidence=0.95,
                        metrics={"recent_wake_events": 0},
                    )
                )
            elif preferred is None:
                # No wake goal yet — sleep owns "set wake goal". Emit a single
                # alarm-setup tip only as a fallback (filtered until due).
                # When a wake goal exists, sleep-create-matching-alarm covers
                # the same "get an alarm armed" action — do not also emit arm.
                items.append(
                    RecommendationItem(
                        id="wake-arm-alarm",
                        category=RecommendationCategory.WAKE,
                        priority=RecommendationPriority.HIGH,
                        title="Arm at least one active alarm",
                        detail=(
                            "Habit coaching needs live alarms. Create a daily alarm "
                            "aligned with your preferred wake time."
                        ),
                        action_hint="Create or re-enable an alarm",
                        action_path="/alarms",
                        confidence=0.93,
                        metrics={"active_alarms": 0},
                    )
                )
            return items

        if snooze_rate is not None and snooze_rate >= 40:
            items.append(
                RecommendationItem(
                    id="wake-reduce-snooze",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Cut morning snoozes — they fragment sleep",
                    detail=(
                        f"You snoozed on ~{snooze_rate}% of recent wakes. Place the phone "
                        "across the room, lower snooze limit to 1, and stand up before "
                        "interacting with the alarm UI."
                    ),
                    action_hint="Lower snooze limit on your main alarm",
                    action_path="/alarms",
                    confidence=0.9,
                    metrics={"snooze_rate": snooze_rate},
                )
            )
        elif snooze_rate is not None and snooze_rate >= 20:
            items.append(
                RecommendationItem(
                    id="wake-snooze-discipline",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.MEDIUM,
                    title="Tighten snooze discipline",
                    detail=(
                        f"Snooze rate is {snooze_rate}%. Try a single allowed snooze "
                        "and require an extra challenge step after any snooze."
                    ),
                    action_hint="Raise challenge count after snooze days",
                    action_path="/alarms",
                    confidence=0.8,
                    metrics={"snooze_rate": snooze_rate},
                )
            )
        elif snooze_rate is not None and snooze_rate < 10:
            items.append(
                RecommendationItem(
                    id="wake-snooze-excellent",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.LOW,
                    title="Excellent snooze control",
                    detail=(
                        f"Only ~{snooze_rate}% of recent wakes used snooze. Keep the "
                        "phone out of reach and maintain your current challenge setup."
                    ),
                    action_hint="Maintain your current alarm settings",
                    action_path="/alarms",
                    confidence=0.85,
                    metrics={"snooze_rate": snooze_rate},
                )
            )

        if consistency < 40:
            items.append(
                RecommendationItem(
                    id="wake-build-consistency",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Rebuild wake-up consistency",
                    detail=(
                        f"Consistency score is {consistency:.0f}/100. Pick one wake time "
                        "for the next 7 days — including weekends — and treat it as fixed."
                    ),
                    action_hint="Lock one wake time for a week",
                    action_path="/profile",
                    confidence=0.88,
                    metrics={"wake_up_consistency_score": consistency},
                )
            )
        elif consistency < 70:
            items.append(
                RecommendationItem(
                    id="wake-consistency-improve",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.MEDIUM,
                    title="Push consistency above 70",
                    detail=(
                        f"You are at {consistency:.0f}/100. Avoid >30-minute weekend "
                        "sleep-ins relative to your weekday wake goal."
                    ),
                    action_hint="Keep weekend wake within 30 minutes",
                    action_path="/profile",
                    confidence=0.8,
                    metrics={"wake_up_consistency_score": consistency},
                )
            )

        if streak == 0 and best >= 3:
            items.append(
                RecommendationItem(
                    id="wake-restart-streak",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Restart your wake streak tomorrow",
                    detail=(
                        f"Streak is 0 but your best is {best} days. One clean "
                        "no-snooze dismiss tomorrow restarts momentum — prepare "
                        "tonight to make failure harder."
                    ),
                    action_hint="Prep for a no-snooze wake tomorrow",
                    action_path="/dashboard",
                    confidence=0.85,
                    metrics={"streak_days": streak, "best_streak": best},
                )
            )
        elif streak >= 7:
            items.append(
                RecommendationItem(
                    id="wake-protect-streak",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.LOW,
                    title=f"Protect your {streak}-day streak",
                    detail=(
                        "Long streaks fail most often on weekends and travel days. "
                        "Keep at least one active alarm and avoid 'just this once' snoozes."
                    ),
                    action_hint="Confirm weekend alarms are armed",
                    action_path="/alarms",
                    confidence=0.8,
                    metrics={"streak_days": streak},
                )
            )
        elif 1 <= streak < 7:
            items.append(
                RecommendationItem(
                    id="wake-grow-streak",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Grow your streak past {streak} days",
                    detail=(
                        "You are building momentum. Aim for 7 consecutive verified "
                        "wakes — the habit score weights streak heavily."
                    ),
                    action_hint="Target a 7-day streak",
                    action_path="/dashboard",
                    confidence=0.75,
                    metrics={"streak_days": streak},
                )
            )

        if avg_level in ("drowsy", "groggy") or (
            avg_wake is not None and avg_wake < 45
        ):
            items.append(
                RecommendationItem(
                    id="wake-raise-alertness",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Raise morning alertness before the challenge",
                    detail=(
                        f"Recent wakefulness looks low"
                        f"{f' ({avg_level})' if avg_level else ''}"
                        f"{f' — avg score {avg_wake}' if avg_wake is not None else ''}. "
                        "Get bright light within 5 minutes of rising, drink water, "
                        "and stand while solving the puzzle."
                    ),
                    action_hint="Add light + water to your wake ritual",
                    action_path="/dashboard",
                    confidence=0.82,
                    metrics={
                        "avg_wakefulness": avg_wake,
                        "avg_wakefulness_level": avg_level,
                    },
                )
            )
        elif avg_wake is not None and avg_wake >= 75:
            items.append(
                RecommendationItem(
                    id="wake-alertness-strong",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.LOW,
                    title="Morning alertness looks strong",
                    detail=(
                        f"Average wakefulness score is {avg_wake}. Use that sharp window "
                        "for your top productivity goal instead of scrolling."
                    ),
                    action_hint="Start your #1 goal right after dismiss",
                    action_path="/profile",
                    confidence=0.8,
                    metrics={"avg_wakefulness": avg_wake},
                )
            )

        if avg_dismiss is not None and avg_dismiss > 180:
            items.append(
                RecommendationItem(
                    id="wake-faster-dismiss",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.MEDIUM,
                    title="Shorten time-to-dismiss",
                    detail=(
                        f"You average ~{avg_dismiss // 60}m {avg_dismiss % 60}s from ring "
                        "to verified dismiss. Practice challenges and keep the phone "
                        "out of bed to shrink lag."
                    ),
                    action_hint="Practice a challenge before bed",
                    action_path="/analytics",
                    confidence=0.75,
                    metrics={"avg_time_to_dismiss_seconds": avg_dismiss},
                )
            )

        exhausted = sum(
            1 for e in verified if e.dismiss_method == "snooze_exhausted"
        )
        if exhausted >= 2:
            items.append(
                RecommendationItem(
                    id="wake-anti-snooze-harder",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Stop waking only after max snoozes",
                    detail=(
                        f"{exhausted} recent wakes ended via snooze exhaustion. "
                        "Reduce snooze limit, increase challenge count, and put the "
                        "device outside arm's reach."
                    ),
                    action_hint="Tighten snooze + challenge settings",
                    action_path="/alarms",
                    confidence=0.9,
                    metrics={"snooze_exhausted_count": exhausted},
                )
            )

        # Re-arm only after the user already has wake history — otherwise the
        # pre-verified branch (or sleep-create-matching-alarm) owns this action.
        if not active:
            items.append(
                RecommendationItem(
                    id="wake-arm-alarm",
                    category=RecommendationCategory.WAKE,
                    priority=RecommendationPriority.HIGH,
                    title="Arm at least one active alarm",
                    detail=(
                        "Habit coaching needs live alarms. Create a daily alarm aligned "
                        "with your preferred wake time."
                    ),
                    action_hint="Create or re-enable an alarm",
                    action_path="/alarms",
                    confidence=0.93,
                    metrics={"active_alarms": 0},
                )
            )

        return items

    @staticmethod
    def _habit_recommendations(signals: Dict[str, Any]) -> List[RecommendationItem]:
        items: List[RecommendationItem] = []
        score = signals["habit_score"]
        breakdown = signals["habit_breakdown"]
        consistency = signals["consistency"]
        streak = signals["streak_days"]

        if score < 40:
            items.append(
                RecommendationItem(
                    id="habit-foundation",
                    category=RecommendationCategory.HABIT,
                    priority=RecommendationPriority.HIGH,
                    title="Focus on habit fundamentals this week",
                    detail=(
                        f"Habit score is {format_habit_score(score)}. Prioritize one fixed wake time, "
                        "zero-snooze mornings, and a realistic sleep duration before "
                        "adding new productivity goals."
                    ),
                    action_hint="Stabilize wake time for 7 days",
                    action_path="/dashboard",
                    confidence=0.9,
                    metrics={"habit_score": score, "breakdown": breakdown},
                )
            )
        elif score < 70:
            weakest = RecommendationService._weakest_habit_component(
                consistency, streak, signals
            )
            items.append(
                RecommendationItem(
                    id="habit-raise-score",
                    category=RecommendationCategory.HABIT,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Raise habit score by improving {weakest['label']}",
                    detail=weakest["detail"],
                    action_hint=weakest["action_hint"],
                    action_path=weakest["action_path"],
                    confidence=0.82,
                    metrics={"habit_score": score, "focus": weakest["key"]},
                )
            )
        else:
            items.append(
                RecommendationItem(
                    id="habit-maintain",
                    category=RecommendationCategory.HABIT,
                    priority=RecommendationPriority.LOW,
                    title="Habit score is strong — maintain the system",
                    detail=(
                        f"At {format_habit_score(score)} you are in a healthy range. Keep the same "
                        "wake time, continue verified dismissals, and channel surplus "
                        "energy into your productivity goals."
                    ),
                    action_hint="Review goals and keep the streak",
                    action_path="/profile",
                    confidence=0.85,
                    metrics={"habit_score": score},
                )
            )

        return items

    @staticmethod
    def _weakest_habit_component(
        consistency: float, streak: int, signals: Dict[str, Any]
    ) -> Dict[str, str]:
        snooze_rate = signals["snooze_rate"]
        candidates = [
            (
                "consistency",
                consistency,
                "wake-up consistency",
                (
                    f"Consistency is {consistency:.0f}/100. Same wake time daily "
                    "moves this component fastest."
                ),
                "Lock preferred wake time",
                "/profile",
            ),
            (
                "streak",
                min(streak / 30.0 * 100, 100.0),
                "streak adherence",
                (
                    f"Current streak is {streak} days. Aim for uninterrupted "
                    "verified wakes to lift sleep-adherence scoring."
                ),
                "Protect tomorrow's wake",
                "/dashboard",
            ),
        ]
        if snooze_rate is not None:
            candidates.append(
                (
                    "snooze",
                    max(0.0, 100.0 - snooze_rate),
                    "snooze reduction",
                    (
                        f"Snooze rate is {snooze_rate}%. Fewer snoozes directly "
                        "improve challenge-completion and snooze-reduction weights."
                    ),
                    "Lower snooze limit",
                    "/alarms",
                )
            )
        candidates.sort(key=lambda c: c[1])
        key, _score, label, detail, hint, path = candidates[0]
        return {
            "key": key,
            "label": label,
            "detail": detail,
            "action_hint": hint,
            "action_path": path,
        }

    @staticmethod
    def _productivity_recommendations(
        signals: Dict[str, Any],
    ) -> List[RecommendationItem]:
        items: List[RecommendationItem] = []
        goals: List[str] = signals["goals"]
        score = signals["habit_score"]
        streak = signals["streak_days"]
        avg_wake = signals["avg_wakefulness"]
        preferred: Optional[time] = signals["preferred_wake_time"]
        has_verified = bool(signals["verified_events"])

        if not goals:
            items.append(
                RecommendationItem(
                    id="productivity-set-goals",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.HIGH,
                    title="Add productivity goals to unlock coaching",
                    detail=(
                        "The engine personalizes morning advice from your goals "
                        "(e.g. exercise, study, deep work). Add 1–3 concrete goals "
                        "in Profile → Preferences."
                    ),
                    action_hint="Write 1–3 productivity goals",
                    action_path="/profile",
                    confidence=0.95,
                    metrics={"goals_count": 0},
                )
            )
            # Generic morning-block only after the user has started waking —
            # otherwise onboarding stays focused on set-goals.
            if has_verified:
                items.append(
                    RecommendationItem(
                        id="productivity-morning-block",
                        category=RecommendationCategory.PRODUCTIVITY,
                        priority=RecommendationPriority.MEDIUM,
                        title="Reserve a 25-minute morning focus block",
                        detail=(
                            "Even without named goals, a fixed post-alarm focus block "
                            "turns wake success into output. Pick one recurring task."
                        ),
                        action_hint="Choose a recurring morning task",
                        action_path="/profile",
                        confidence=0.7,
                        metrics={"habit_score": score},
                    )
                )
            return items

        primary_goal = RecommendationService._format_goal_label(goals[0])

        # Advanced goal coaching unlocks after at least one verified wake.
        if not has_verified:
            items.append(
                RecommendationItem(
                    id="productivity-goals-active",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.LOW,
                    title=f"Working toward {len(goals)} goal(s)",
                    detail=(
                        "Goals on file: "
                        + RecommendationService._format_goals_list(goals)
                        + ". Complete a verified wake to unlock morning goal coaching."
                    ),
                    action_hint="Complete a verified wake tomorrow",
                    action_path="/alarms",
                    confidence=0.7,
                    metrics={"goals": goals[:5], "goals_count": len(goals)},
                )
            )
            return items

        if score < 50:
            items.append(
                RecommendationItem(
                    id="productivity-stabilize-first",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.HIGH,
                    title="Stabilize wake habits before stacking goals",
                    detail=(
                        f"Habit score is {format_habit_score(score)}. Ambition without a reliable "
                        "wake time usually fails. Fix consistency first, then attack: "
                        f"{primary_goal}."
                    ),
                    action_hint="Prioritize wake consistency this week",
                    action_path="/dashboard",
                    confidence=0.88,
                    metrics={"habit_score": score, "primary_goal": goals[0]},
                )
            )
        else:
            wake_label = (
                preferred.strftime("%H:%M") if preferred else "your wake time"
            )
            items.append(
                RecommendationItem(
                    id="productivity-use-morning-window",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Schedule “{primary_goal}” right after {wake_label}",
                    detail=(
                        "Your habit foundation is solid enough to attach goal work "
                        "to the alarm. Do the hardest goal task in the first hour "
                        "after a verified dismiss."
                    ),
                    action_hint=f"Block time for: {primary_goal}",
                    action_path="/profile",
                    confidence=0.85,
                    metrics={
                        "habit_score": score,
                        "primary_goal": goals[0],
                        "preferred_wake_time": wake_label,
                    },
                )
            )

        matched_keys: set = set()
        for goal in goals:
            template = RecommendationService._match_goal_template(goal)
            if template is None:
                continue
            key = template["key"]
            if key in matched_keys:
                continue
            matched_keys.add(key)
            goal_label = RecommendationService._format_goal_label(goal)
            items.append(
                RecommendationItem(
                    id=f"productivity-goal-{key}",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.MEDIUM,
                    title=template["title"],
                    detail=f"For your goal “{goal_label}”: {template['detail']}",
                    action_hint=template["action_hint"],
                    action_path="/profile",
                    confidence=0.8,
                    metrics={"goal": goal, "match_key": key},
                )
            )

        # Streak leverage requires a real streak + solid habits.
        if streak >= 3 and score >= 60:
            items.append(
                RecommendationItem(
                    id="productivity-streak-leverage",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.MEDIUM,
                    title="Convert your streak into goal momentum",
                    detail=(
                        f"A {streak}-day wake streak is rare leverage. Pair each "
                        f"successful wake with a minimum action toward “{primary_goal}” "
                        "so the streak compounds into results."
                    ),
                    action_hint="Define a minimum daily goal action",
                    action_path="/profile",
                    confidence=0.83,
                    metrics={"streak_days": streak, "primary_goal": goals[0]},
                )
            )

        if avg_wake is not None and avg_wake >= 70:
            items.append(
                RecommendationItem(
                    id="productivity-high-alertness",
                    category=RecommendationCategory.PRODUCTIVITY,
                    priority=RecommendationPriority.LOW,
                    title="Use high-alertness mornings for deep work",
                    detail=(
                        f"Wakefulness averages {avg_wake}. Those mornings are ideal "
                        f"for cognitively hard goals such as “{primary_goal}” — avoid "
                        "spending them on email or social feeds."
                    ),
                    action_hint="Save deep work for high-alertness days",
                    action_path="/analytics",
                    confidence=0.78,
                    metrics={"avg_wakefulness": avg_wake},
                )
            )

        # AI tip only once foundation + goals are in place.
        if score >= 50:
            ai_tip = RecommendationService._optional_ai_productivity_tip(
                goals, signals
            )
            if ai_tip:
                items.append(ai_tip)

        return items

    @staticmethod
    def _match_goal_template(goal: str) -> Optional[Dict[str, str]]:
        lowered = goal.lower()
        for key, template in GOAL_COACHING.items():
            if key in lowered:
                return {"key": key, **template}
        return None

    @staticmethod
    def _optional_ai_productivity_tip(
        goals: List[str], signals: Dict[str, Any]
    ) -> Optional[RecommendationItem]:
        """Optionally refine a productivity tip via Gemini; fails soft."""
        try:
            from app.core.config import settings

            if not getattr(settings, "GEMINI_API_KEY", None):
                return None

            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                "You are a concise wake-up and productivity coach. "
                "Given the user's goals and habit stats, write ONE short tip "
                "(max 2 sentences) that is specific and actionable. "
                "No markdown, no greeting.\n"
                f"Goals: {goals}\n"
                f"Habit score: {format_habit_score(signals['habit_score'])}\n"
                f"Day streak: {signals['streak_days']}\n"
                f"Success streak: {signals.get('success_streak', 0)}\n"
                f"Snooze rate: {signals['snooze_rate']}\n"
                f"Preferred wake: {signals['preferred_wake_time']}\n"
            )
            response = model.generate_content(prompt)
            text = (getattr(response, "text", None) or "").strip()
            if not text or len(text) > 400:
                return None
            return RecommendationItem(
                id="productivity-ai-tip",
                category=RecommendationCategory.PRODUCTIVITY,
                priority=RecommendationPriority.LOW,
                title="AI coaching tip",
                detail=text,
                action_hint="Apply this tip tomorrow morning",
                action_path="/profile",
                confidence=0.6,
                metrics={"source": "gemini", "goals_count": len(goals)},
            )
        except Exception:
            return None

    @staticmethod
    def _challenge_recommendations(
        logs: List[AlarmChallengeLog],
        signals: Optional[Dict[str, Any]] = None,
    ) -> List[RecommendationItem]:
        analysis = ChallengeService.analyze_completion(logs)
        items: List[RecommendationItem] = []
        seen_ids: set = set()
        for rec in analysis.get("recommendations") or []:
            priority_raw = (rec.get("priority") or "low").lower()
            try:
                priority = RecommendationPriority(priority_raw)
            except ValueError:
                priority = RecommendationPriority.LOW
            category_tag = rec.get("category") or "maintain"
            # Stable IDs (no index suffix) so the same tip never duplicates.
            challenge_type = (rec.get("challenge_type") or "").strip().lower()
            if category_tag == "practice_focus" and challenge_type:
                rec_id = f"challenge-{category_tag}-{challenge_type}"
            else:
                rec_id = f"challenge-{category_tag}"
            if rec_id in seen_ids:
                continue
            seen_ids.add(rec_id)
            items.append(
                RecommendationItem(
                    id=rec_id,
                    category=RecommendationCategory.CHALLENGE,
                    priority=priority,
                    title=rec.get("title") or "Challenge tip",
                    detail=rec.get("detail") or "",
                    action_hint="Review challenge analytics",
                    action_path="/analytics",
                    confidence=0.75,
                    metrics={
                        "source_category": category_tag,
                        **(
                            {"challenge_type": challenge_type}
                            if challenge_type
                            else {}
                        ),
                    },
                )
            )

        # Success Streak SSOT — same counter Analytics / Personalization use.
        # Only surface after the user has challenge history (not onboarding).
        signals = signals or {}
        success_streak = int(signals.get("success_streak", 0) or 0)
        try:
            from app.services.challenge_service import _adaptive_streak_threshold

            threshold = _adaptive_streak_threshold()
        except Exception:
            threshold = 5
        if success_streak > 0 and logs:
            items.append(
                RecommendationItem(
                    id="challenge-success-streak",
                    category=RecommendationCategory.CHALLENGE,
                    priority=RecommendationPriority.LOW,
                    title="Protect your Success Streak",
                    detail=(
                        f"Success Streak is {success_streak} consecutive wake "
                        f"completion(s). Adaptive difficulty rises every "
                        f"{threshold} successes and never resets this streak — "
                        "only a failed wake does."
                    ),
                    action_hint="Complete tomorrow's wake without giving up",
                    action_path="/analytics",
                    confidence=0.8,
                    metrics={
                        "success_streak": success_streak,
                        "streak_threshold": threshold,
                    },
                )
            )
        return items

    @staticmethod
    def _build_summary(
        signals: Dict[str, Any], items: List[RecommendationItem]
    ) -> RecommendationSummary:
        preferred = signals["preferred_wake_time"]
        bedtime = signals["suggested_bedtime"]
        top_focus, top_label = RecommendationService._determine_top_focus(
            signals, items
        )
        return RecommendationSummary(
            habit_score=signals["habit_score"],
            wake_consistency=signals["consistency"],
            streak_days=signals["streak_days"],
            best_streak=signals["best_streak"],
            sleep_target_hours=signals["sleep_duration_hours"],
            preferred_wake_time=(
                preferred.strftime("%H:%M") if preferred else None
            ),
            suggested_bedtime=(
                bedtime.strftime("%H:%M") if bedtime else None
            ),
            avg_wakefulness=signals["avg_wakefulness"],
            avg_wakefulness_level=signals["avg_wakefulness_level"],
            snooze_rate=signals["snooze_rate"],
            recent_wake_events=len(signals["verified_events"]),
            active_alarms=len(signals["active_alarms"]),
            goals_count=len(signals["goals"]),
            top_focus=top_focus,
            top_focus_label=top_label,
        )

    @staticmethod
    def _determine_top_focus(
        signals: Dict[str, Any], items: List[RecommendationItem]
    ) -> Tuple[str, str]:
        progress = signals.get("progress") or {}
        next_milestone = progress.get("next_milestone")
        milestone_labels = {
            "wake_goal": ("sleep", "Set sleep schedule"),
            "active_alarm": ("wake", "Arm an alarm"),
            "verified_wake": ("wake", "Complete first verified wake"),
            "productivity_goals": ("productivity", "Define productivity goals"),
            "challenges": ("challenge", "Start morning challenges"),
        }
        if next_milestone and next_milestone in milestone_labels:
            return milestone_labels[next_milestone]

        if not signals["verified_events"] and not signals["active_alarms"]:
            return "getting_started", "Getting started"
        if signals["preferred_wake_time"] is None:
            return "sleep", "Set sleep schedule"
        if not signals["goals"]:
            high_prod = any(
                i.category == RecommendationCategory.PRODUCTIVITY
                and i.priority == RecommendationPriority.HIGH
                for i in items
            )
            if high_prod:
                return "productivity", "Define productivity goals"
        high = [i for i in items if i.priority == RecommendationPriority.HIGH]
        if high:
            cat = high[0].category.value
            labels = {
                "sleep": "Improve sleep schedule",
                "wake": "Strengthen wake habits",
                "habit": "Raise habit score",
                "productivity": "Boost productivity",
                "challenge": "Sharpen challenges",
            }
            return cat, labels.get(cat, cat.title())
        if signals["habit_score"] >= 70:
            return "maintain", "Maintain & optimize"
        return "habit", "Build stronger habits"

    @staticmethod
    def _build_insights(
        signals: Dict[str, Any], items: List[RecommendationItem]
    ) -> List[str]:
        insights: List[str] = []
        preferred = signals["preferred_wake_time"]
        bedtime = signals["suggested_bedtime"]
        insights.append(
            f"Habit score {format_habit_score(signals['habit_score'])} · "
            f"consistency {signals['consistency']:.0f} · "
            f"streak {signals['streak_days']} day(s)."
        )
        if preferred and bedtime:
            insights.append(
                f"Sleep plan: lights-out ~{bedtime.strftime('%H:%M')} for a "
                f"{signals['sleep_duration_hours']:g}h target before "
                f"{preferred.strftime('%H:%M')} wake."
            )
        if signals["snooze_rate"] is not None:
            insights.append(
                f"Recent snooze rate: {signals['snooze_rate']}% across "
                f"{len(signals['verified_events'])} verified wake(s)."
            )
        if signals["avg_wakefulness"] is not None:
            level = signals["avg_wakefulness_level"] or "unknown"
            insights.append(
                f"Average wakefulness {signals['avg_wakefulness']} ({level})."
            )
        goals = signals["goals"]
        if goals:
            primary = RecommendationService._format_goal_label(goals[0])
            insights.append(
                f"Tracking {len(goals)} productivity goal(s); primary: “{primary}”."
            )
        else:
            insights.append(
                "No productivity goals set yet — add them for personalized coaching."
            )
        high = sum(
            1 for i in items if i.priority == RecommendationPriority.HIGH
        )
        if high:
            insights.append(
                f"{high} high-priority action(s) need attention today."
            )
        return insights

    @staticmethod
    def _build_daily_plan(
        signals: Dict[str, Any], items: List[RecommendationItem]
    ) -> DailyPlan:
        preferred = signals["preferred_wake_time"]
        bedtime = signals["suggested_bedtime"]
        goals = signals["goals"]
        if goals:
            morning_focus = (
                f"First focus: {RecommendationService._format_goal_label(goals[0])}"
            )
        elif signals["habit_score"] < 50:
            morning_focus = "First focus: no-snooze verified wake"
        else:
            morning_focus = "First focus: protect wake time, then deep work"

        actions: List[str] = []
        for item in items:
            if item.priority == RecommendationPriority.HIGH:
                actions.append(item.action_hint or item.title)
            if len(actions) >= 3:
                break
        if len(actions) < 3:
            for item in items:
                hint = item.action_hint or item.title
                if hint not in actions:
                    actions.append(hint)
                if len(actions) >= 3:
                    break
        if bedtime and preferred:
            actions = [
                f"Wind down for bedtime ~{bedtime.strftime('%H:%M')}",
                *actions,
            ][:4]

        return DailyPlan(
            suggested_bedtime=(
                bedtime.strftime("%H:%M") if bedtime else None
            ),
            suggested_wake_time=(
                preferred.strftime("%H:%M") if preferred else None
            ),
            morning_focus=morning_focus,
            priority_actions=actions,
        )

    @staticmethod
    def _compute_bedtime(wake: time, duration_hours: float) -> time:
        base = datetime.combine(datetime.today().date(), wake)
        bed = base - timedelta(hours=duration_hours)
        return bed.time().replace(microsecond=0)

    @staticmethod
    def _normalize_goals(raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
            return [p for p in parts if p]
        if isinstance(raw, list):
            return [str(g).strip() for g in raw if str(g).strip()]
        return []

    @staticmethod
    def _format_goal_label(goal: str) -> str:
        """Capitalize a goal for user-facing copy without changing stored values."""
        text = (goal or "").strip()
        if not text:
            return text
        return text[0].upper() + text[1:]

    @staticmethod
    def _format_goals_list(goals: List[str], *, limit: int = 5) -> str:
        """Comma-separated, capitalized goal list for English presentation."""
        labels = [
            RecommendationService._format_goal_label(g) for g in goals[:limit]
        ]
        text = ", ".join(labels)
        if len(goals) > limit:
            text += ", …"
        return text

    @staticmethod
    def _alarm_wake_alignment(
        preferred: Optional[time], active_alarms: List[Alarm]
    ) -> Optional[Dict[str, Any]]:
        if preferred is None or not active_alarms:
            return None
        earliest = min(active_alarms, key=lambda a: a.alarm_time)
        delta = RecommendationService._minutes_between(
            preferred, earliest.alarm_time
        )
        return {
            "preferred_wake": preferred.strftime("%H:%M"),
            "earliest_alarm": earliest.alarm_time.strftime("%H:%M"),
            "delta_minutes": delta,
            "alarm_id": earliest.id,
        }

    @staticmethod
    def _minutes_between(a: time, b: time) -> int:
        """Signed minutes from a → b on a 24h circle, normalized to [-720, 720]."""
        ma = a.hour * 60 + a.minute
        mb = b.hour * 60 + b.minute
        delta = mb - ma
        if delta > 720:
            delta -= 1440
        elif delta < -720:
            delta += 1440
        return delta

    @staticmethod
    def _dominant_level(levels: List[str]) -> Optional[str]:
        if not levels:
            return None
        order = ["alert", "awake", "groggy", "drowsy", "unknown"]
        counts: Dict[str, int] = {}
        for level in levels:
            counts[level] = counts.get(level, 0) + 1
        return max(
            counts.keys(),
            key=lambda k: (counts[k], -order.index(k) if k in order else -99),
        )

    @staticmethod
    def _detect_progress(signals: Dict[str, Any]) -> Dict[str, Any]:
        """Derive completed milestones and the next onboarding action from live state."""
        has_wake_goal = signals["preferred_wake_time"] is not None
        has_alarm = len(signals["active_alarms"]) > 0
        has_verified = len(signals["verified_events"]) > 0
        has_goals = len(signals["goals"]) > 0
        has_challenges = len(signals.get("challenge_logs") or []) > 0

        flags = {
            "wake_goal": has_wake_goal,
            "active_alarm": has_alarm,
            "verified_wake": has_verified,
            "productivity_goals": has_goals,
            "challenges": has_challenges,
        }
        completed = [name for name, done in flags.items() if done]

        next_milestone: Optional[str] = None
        next_rec_ids: Tuple[str, ...] = ()
        for milestone, rec_ids in ONBOARDING_SEQUENCE:
            if not flags[milestone]:
                next_milestone = milestone
                next_rec_ids = rec_ids
                break

        # Core onboarding = wake goal + alarm + first verified wake.
        onboarding_complete = has_wake_goal and has_alarm and has_verified
        habit_score = float(signals.get("habit_score") or 0)
        if not onboarding_complete:
            stage = "onboarding"
        elif habit_score >= 70 and has_goals:
            stage = "advanced"
        elif has_goals and habit_score >= 50:
            stage = "optimizing"
        else:
            stage = "building"

        return {
            "completed": completed,
            "flags": flags,
            "next_milestone": next_milestone,
            "next_rec_ids": next_rec_ids,
            "onboarding_complete": onboarding_complete,
            "stage": stage,
        }

    @staticmethod
    def _finalize_recommendations(
        items: List[RecommendationItem],
        progress: Dict[str, Any],
    ) -> List[RecommendationItem]:
        """Hide completed items, drop duplicates, and prioritize the next action."""
        items = RecommendationService._hide_completed(items, progress)
        items = RecommendationService._filter_by_progress_stage(items, progress)
        items = RecommendationService._dedupe_and_sort(items)
        items = RecommendationService._dedupe_topics(items)
        items = RecommendationService._suppress_status_affirmations(items)
        items = RecommendationService._prioritize_next_action(items, progress)
        return items

    @staticmethod
    def _hide_completed(
        items: List[RecommendationItem],
        progress: Dict[str, Any],
    ) -> List[RecommendationItem]:
        """Remove recommendations whose milestones the user has already finished."""
        hide: set = set()
        completed = set(progress.get("completed") or [])
        for milestone, ids in COMPLETED_MILESTONE_IDS.items():
            if milestone in completed:
                hide |= set(ids)

        result: List[RecommendationItem] = []
        for item in items:
            if item.id in hide:
                continue
            # Prefix match for challenge getting_started variants.
            if "challenges" in completed and item.id.startswith(
                "challenge-getting_started"
            ):
                continue
            result.append(item)
        return result

    @staticmethod
    def _filter_by_progress_stage(
        items: List[RecommendationItem],
        progress: Dict[str, Any],
    ) -> List[RecommendationItem]:
        """During onboarding, keep only the next action + sleep schedule helpers.

        Later checklist tips (arm alarm, first wake, set goals, …) stay hidden
        until they become the current milestone — avoids repetitive same-intent
        cards like Create / Arm / Complete first wake all at once.
        """
        if progress.get("onboarding_complete"):
            return items

        flags = progress.get("flags") or {}
        next_ids = set(progress.get("next_rec_ids") or ())

        result: List[RecommendationItem] = []
        for item in items:
            # Soft status when goals were set early — nudges the next wake.
            if (
                item.id == "productivity-goals-active"
                and flags.get("productivity_goals")
                and not flags.get("verified_wake")
            ):
                result.append(item)
                continue

            # Onboarding checklist: only the current next milestone tip(s).
            is_onboarding_tip = (
                item.id in _ONBOARDING_TIP_IDS
                or item.id.startswith("challenge-getting_started")
            )
            if is_onboarding_tip:
                if item.id in next_ids:
                    result.append(item)
                    continue
                if item.id.startswith("challenge-getting_started") and any(
                    n.startswith("challenge-getting_started") for n in next_ids
                ):
                    result.append(item)
                continue

            # Sleep schedule helpers (except status affirmation) stay useful
            # once a wake goal exists — not the same action as alarm setup.
            if item.id.startswith("sleep-") and item.id != "sleep-duration-healthy":
                result.append(item)
                continue
            # Challenge history unlocks challenge coaching even mid-onboarding.
            if flags.get("challenges") and item.category == (
                RecommendationCategory.CHALLENGE
            ):
                result.append(item)
                continue
            # Drop advanced wake/habit/productivity coaching until the user
            # finishes core onboarding (wake goal + alarm + verified wake).
        return result

    @staticmethod
    def _dedupe_topics(
        items: List[RecommendationItem],
    ) -> List[RecommendationItem]:
        """Keep one recommendation per same-action / overlapping intent group."""
        by_id = {item.id: item for item in items}
        drop: set = set()
        for group in ACTION_INTENT_GROUPS:
            present = [by_id[i] for i in group if i in by_id]
            if len(present) <= 1:
                continue
            present.sort(
                key=lambda r: (
                    PRIORITY_RANK.get(r.priority, 9),
                    -r.confidence,
                    r.id,
                )
            )
            for loser in present[1:]:
                drop.add(loser.id)
        if not drop:
            return items
        return [item for item in items if item.id not in drop]

    @staticmethod
    def _suppress_status_affirmations(
        items: List[RecommendationItem],
    ) -> List[RecommendationItem]:
        """Hide completed-style status cards when actionable coaching remains."""

        def _is_status(item: RecommendationItem) -> bool:
            if item.id in STATUS_AFFIRMATION_IDS:
                return True
            return item.id.startswith("challenge-maintain")

        actionables = [i for i in items if not _is_status(i)]
        if not actionables:
            return items
        if any(
            i.priority
            in (RecommendationPriority.HIGH, RecommendationPriority.MEDIUM)
            for i in actionables
        ):
            return [i for i in items if not _is_status(i)]
        return items

    @staticmethod
    def _prioritize_next_action(
        items: List[RecommendationItem],
        progress: Dict[str, Any],
    ) -> List[RecommendationItem]:
        """Boost the single next onboarding milestone to the front of the feed."""
        next_ids = set(progress.get("next_rec_ids") or ())
        if not next_ids or not items:
            return RecommendationService._dedupe_and_sort(items)

        onboarding_ids = {
            rid for _, ids in ONBOARDING_SEQUENCE for rid in ids
        }

        def _is_next(item: RecommendationItem) -> bool:
            if item.id in next_ids:
                return True
            return item.id.startswith("challenge-getting_started") and any(
                n.startswith("challenge-getting_started") for n in next_ids
            )

        boosted: List[RecommendationItem] = []
        for item in items:
            if _is_next(item):
                boosted.append(
                    item.model_copy(
                        update={"priority": RecommendationPriority.HIGH}
                    )
                )
            elif (
                item.id in onboarding_ids
                or item.id.startswith("challenge-getting_started")
            ) and item.priority == RecommendationPriority.HIGH:
                boosted.append(
                    item.model_copy(
                        update={"priority": RecommendationPriority.MEDIUM}
                    )
                )
            else:
                boosted.append(item)

        return RecommendationService._dedupe_and_sort(boosted)

    @staticmethod
    def _dedupe_and_sort(
        items: List[RecommendationItem],
    ) -> List[RecommendationItem]:
        seen = set()
        unique: List[RecommendationItem] = []
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            unique.append(item)
        unique.sort(
            key=lambda i: (
                PRIORITY_RANK.get(i.priority, 9),
                -i.confidence,
                i.category.value,
            )
        )
        return unique
