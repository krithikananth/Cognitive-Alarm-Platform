"""Tests for the Adaptive Difficulty Engine (Requirement 5).

Covers the two parts that were previously missing:

* ``LearningPatternService`` — a real learning profile computed from attempt
  history (least-squares accuracy/speed trends, block-variance consistency,
  per-type mastery, per-difficulty competence, optimal difficulty, and a
  time-of-day performance profile).
* ``EngagementService`` — an engagement score whose *directives* actually
  change what the challenge engine serves at runtime (bounded difficulty bias
  and a novelty boost that re-weights challenge-type selection).

Plus the end-to-end wiring, the ownership/robustness guarantees, and the five
difficulty levels.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.models.alarm import ChallengeType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.services import challenge_service as challenge_service_module
from app.services.challenge_service import (
    DIFFICULTY_LEVELS,
    SELECTABLE_CHALLENGE_TYPES,
    ChallengeService,
)
from app.services.learning_pattern_service import (
    ENGAGEMENT_IMPROVEMENT_TOLERANCE,
    ENGAGEMENT_PERIOD_DAYS,
    MAX_NOVELTY_BOOST,
    MIN_PATTERN_SAMPLE,
    EngagementService,
    LearningPatternService,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FakeLog:
    """Stand-in for an AlarmChallengeLog row (analyzers are pure functions)."""

    def __init__(
        self,
        *,
        is_correct=True,
        challenge_type="math",
        difficulty="medium",
        time_taken_seconds=10,
        failed_attempts=0,
        created_at=None,
    ):
        self.is_correct = is_correct
        self.challenge_type = challenge_type
        self.difficulty = difficulty
        self.time_taken_seconds = time_taken_seconds
        self.failed_attempts = failed_attempts
        self.created_at = created_at if created_at is not None else _now()


class FakeWake:
    """Stand-in for an AlarmWakeEvent row."""

    def __init__(self, *, verified=True, dismiss_method="challenge", snoozes=0):
        self.verified = verified
        self.dismiss_method = dismiss_method
        self.snooze_count_at_dismiss = snoozes


def _series(outcomes, *, challenge_type="math", difficulty="medium", start_days_ago=20):
    """Build a newest-first log list from an oldest-first outcome sequence."""
    base = _now() - timedelta(days=start_days_ago)
    logs = [
        FakeLog(
            is_correct=bool(o),
            challenge_type=challenge_type,
            difficulty=difficulty,
            created_at=base + timedelta(hours=i),
        )
        for i, o in enumerate(outcomes)
    ]
    return list(reversed(logs))


# ══════════════════════════════════════════════════════════════════
# Learning pattern analysis
# ══════════════════════════════════════════════════════════════════


class TestLearningPatternAnalysis:
    """The learning profile must be computed from history, not hard-coded."""

    def test_empty_history_is_insufficient_data(self):
        result = LearningPatternService.analyze([])
        assert result["learning_state"] == "insufficient_data"
        assert result["has_enough_data"] is False
        assert result["optimal_difficulty"] is None
        assert result["by_type"] == {}

    def test_below_minimum_sample_is_insufficient_data(self):
        result = LearningPatternService.analyze(_series([1] * (MIN_PATTERN_SAMPLE - 1)))
        assert result["learning_state"] == "insufficient_data"

    def test_improving_trend_is_detected_from_the_slope(self):
        # Struggled early, solid later.
        result = LearningPatternService.analyze(
            _series([0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1])
        )
        assert result["learning_state"] == "improving"
        assert result["accuracy_trend_pp_per_10"] > 0

    def test_declining_trend_is_detected_from_the_slope(self):
        result = LearningPatternService.analyze(
            _series([1, 1, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0])
        )
        assert result["learning_state"] == "declining"
        assert result["accuracy_trend_pp_per_10"] < 0

    def test_plateau_detected_at_high_flat_accuracy(self):
        result = LearningPatternService.analyze(_series([1] * 20))
        assert result["learning_state"] == "plateaued"
        assert result["accuracy"] == 100.0
        assert result["accuracy_trend_pp_per_10"] == 0.0

    def test_volatile_when_blocks_swing_at_a_flat_trend(self):
        # Symmetric so the slope is exactly flat, but blocks swing 100 -> 0.
        outcomes = [1] * 5 + [0] * 10 + [1] * 5
        result = LearningPatternService.analyze(_series(outcomes))
        assert result["accuracy_trend_pp_per_10"] == 0.0
        assert result["learning_state"] == "volatile"
        assert result["consistency"] < 60

    def test_steady_when_flat_and_consistent_below_plateau(self):
        # 60% in every block: flat and consistent, but not plateau-grade.
        block, mirror = [1, 1, 1, 0, 0], [0, 0, 1, 1, 1]
        result = LearningPatternService.analyze(_series(block + mirror + block + mirror))
        assert result["accuracy_trend_pp_per_10"] == 0.0
        assert result["accuracy"] == 60.0
        assert result["learning_state"] == "steady"

    def test_flat_but_failing_is_struggling_not_steady(self):
        """A flat trend at 0% is stuck, not 'holding steady'."""
        result = LearningPatternService.analyze(_series([0] * 12))
        assert result["accuracy"] == 0.0
        assert result["accuracy_trend_pp_per_10"] == 0.0
        assert result["learning_state"] == "struggling"
        assert "too hard" in result["learning_state_label"]

    def test_struggling_state_reinforces_engagement_easing(self):
        """A stuck learner counts as struggling even without abandoned wakes."""
        result = EngagementService.analyze(
            _disengaged_logs(),
            [FakeWake(verified=True) for _ in range(5)],
            learning_state="struggling",
        )
        assert result["state"] in ("disengaged", "at_risk")
        assert result["directives"]["difficulty_bias"] == -1

    def test_consistency_separates_steady_from_erratic_at_equal_accuracy(self):
        """Same overall accuracy, different consistency — the point of blocks."""
        steady = LearningPatternService.analyze(_series([1, 0] * 10))
        erratic = LearningPatternService.analyze(_series(([1] * 5 + [0] * 5) * 2))
        assert steady["accuracy"] == erratic["accuracy"] == 50.0
        assert steady["consistency"] > erratic["consistency"]

    def test_speed_trend_detects_getting_faster(self):
        base = _now() - timedelta(days=5)
        logs = [
            FakeLog(time_taken_seconds=40 - (2 * i), created_at=base + timedelta(hours=i))
            for i in range(12)
        ]
        result = LearningPatternService.analyze(list(reversed(logs)))
        assert result["speed_trend_seconds_per_10"] < 0

    def test_per_type_mastery_and_independent_slope(self):
        logs = _series([1] * 10, challenge_type="math") + _series(
            [0] * 8, challenge_type="riddle"
        )
        result = LearningPatternService.analyze(logs)

        assert result["by_type"]["math"]["mastery"] == "mastered"
        assert result["by_type"]["math"]["accuracy"] == 100.0
        assert result["by_type"]["riddle"]["mastery"] == "novice"
        assert result["by_type"]["riddle"]["accuracy"] == 0.0
        assert "math" in result["mastered_types"]
        assert "riddle" in result["focus_types"]

    def test_word_alias_is_normalized_into_word_game(self):
        result = LearningPatternService.analyze(
            _series([1] * 6, challenge_type="word")
        )
        assert "word_game" in result["by_type"]
        assert "word" not in result["by_type"]

    def test_random_and_unknown_types_are_excluded_from_mastery(self):
        result = LearningPatternService.analyze(
            _series([1] * 6, challenge_type="random")
        )
        assert result["by_type"] == {}

    @pytest.mark.parametrize("level", DIFFICULTY_LEVELS)
    def test_every_difficulty_level_is_analyzed(self, level):
        """All five levels — beginner, easy, medium, hard, expert."""
        result = LearningPatternService.analyze(_series([1] * 8, difficulty=level))
        assert result["by_difficulty"][level]["attempts"] == 8
        assert result["by_difficulty"][level]["competence"] == "mastered"
        assert result["optimal_difficulty"] == level

    def test_optimal_difficulty_is_hardest_level_above_the_target_band(self):
        logs = (
            _series([1] * 8, difficulty="easy")
            + _series([1] * 8, difficulty="medium")
            + _series([0] * 8, difficulty="expert")
        )
        result = LearningPatternService.analyze(logs)
        assert result["optimal_difficulty"] == "medium"

    def test_optimal_difficulty_falls_back_to_easiest_when_all_below_band(self):
        logs = _series([0] * 8, difficulty="hard") + _series(
            [0] * 8, difficulty="expert"
        )
        result = LearningPatternService.analyze(logs)
        assert result["optimal_difficulty"] == "hard"

    def test_optimal_difficulty_needs_a_minimum_sample(self):
        result = LearningPatternService.analyze(_series([1] * 2, difficulty="expert"))
        assert result["optimal_difficulty"] is None

    def test_time_of_day_profile_uses_the_user_timezone(self):
        """The same UTC rows bucket differently under a shifted timezone."""
        base = datetime(2026, 8, 1, 2, 0)  # 02:00 UTC == 07:30 Asia/Kolkata
        logs = [
            FakeLog(is_correct=True, created_at=base + timedelta(days=i))
            for i in range(6)
        ] + [
            FakeLog(
                is_correct=False,
                created_at=base + timedelta(days=i, hours=12),
            )
            for i in range(6)
        ]
        logs = list(reversed(logs))

        utc = LearningPatternService.analyze(logs, tz_name="UTC")
        kolkata = LearningPatternService.analyze(logs, tz_name="Asia/Kolkata")

        assert utc["time_of_day"]["peak_hours"] == [2]
        assert utc["time_of_day"]["low_hours"] == [14]
        # +5:30 shifts both buckets forward.
        assert kolkata["time_of_day"]["peak_hours"] == [7]
        assert kolkata["time_of_day"]["low_hours"] == [19]

    def test_time_of_day_ignores_thin_buckets(self):
        base = datetime(2026, 8, 1, 3, 0)
        logs = [FakeLog(is_correct=True, created_at=base)] + [
            FakeLog(is_correct=False, created_at=base + timedelta(days=i, hours=5))
            for i in range(8)
        ]
        result = LearningPatternService.analyze(list(reversed(logs)))
        # The single 03:00 attempt cannot qualify as a peak hour.
        assert 3 not in result["time_of_day"]["peak_hours"]

    def test_unknown_timezone_falls_back_to_utc(self):
        logs = _series([1] * 8)
        assert LearningPatternService.analyze(logs, tz_name="Not/AZone")[
            "time_of_day"
        ] == LearningPatternService.analyze(logs, tz_name="UTC")["time_of_day"]


# ══════════════════════════════════════════════════════════════════
# Difficulty adaptation effectiveness
# ══════════════════════════════════════════════════════════════════


def _segments(spec, *, start_days_ago=20):
    """Build a newest-first log list from ``[(difficulty, outcomes), ...]``.

    Each segment is a contiguous run at one served difficulty, so the boundary
    between two segments is exactly one adaptation event.
    """
    base = _now() - timedelta(days=start_days_ago)
    logs = []
    hour = 0
    for difficulty, outcomes in spec:
        for outcome in outcomes:
            logs.append(
                FakeLog(
                    is_correct=bool(outcome),
                    difficulty=difficulty,
                    created_at=base + timedelta(hours=hour),
                )
            )
            hour += 1
    return list(reversed(logs))


class TestAdaptationEffectiveness:
    """Whether changing the served difficulty actually improved the fit.

    Success is a *reduction in distance from the 60–85% target band*, so a
    difficulty increase that correctly pulls a 100% user down scores as
    effective while a naive "accuracy must rise" rule would call it a failure.
    """

    def test_no_difficulty_change_means_no_adaptations(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("medium", [1, 0, 1, 1, 0, 1, 1, 0])])
        )
        assert result["adaptations_detected"] == 0
        assert result["adaptations_judged"] == 0
        assert result["verdict"] == "insufficient_data"
        assert result["effectiveness_rate"] == 0.0

    def test_raising_difficulty_off_a_perfect_score_is_effective(self):
        """100% accuracy is 15 pts above the band; 80% is inside it."""
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("easy", [1, 1, 1, 1, 1]), ("medium", [1, 1, 1, 1, 0])])
        )
        event = result["recent_events"][0]
        assert event["direction"] == "harder"
        assert event["accuracy_before"] == 100.0
        assert event["accuracy_after"] == 80.0
        assert event["band_distance_before"] == 15.0
        assert event["band_distance_after"] == 0.0
        assert event["band_distance_change"] == -15.0
        assert event["verdict"] == "effective"
        assert result["effective"] == 1

    def test_easing_difficulty_for_a_struggling_user_is_effective(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("hard", [0, 0, 0, 0, 1]), ("medium", [1, 1, 1, 0, 1])])
        )
        event = result["recent_events"][0]
        assert event["direction"] == "easier"
        assert event["accuracy_before"] == 20.0
        assert event["accuracy_after"] == 80.0
        assert event["band_distance_before"] == 40.0
        assert event["band_distance_after"] == 0.0
        assert event["verdict"] == "effective"

    def test_an_accuracy_rise_that_overshoots_the_band_is_not_effective(self):
        """Rising 20% -> 100% is a big accuracy gain and still a bad fit."""
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("hard", [0, 0, 0, 0, 1]), ("easy", [1, 1, 1, 1, 1])])
        )
        event = result["recent_events"][0]
        assert event["accuracy_after"] > event["accuracy_before"]
        assert event["band_distance_before"] == 40.0
        assert event["band_distance_after"] == 15.0
        assert event["verdict"] == "effective"  # 40 -> 15 is still closer

    def test_pushing_a_user_further_outside_the_band_is_ineffective(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("medium", [1, 1, 1, 0, 1]), ("expert", [0, 0, 0, 0, 0])])
        )
        event = result["recent_events"][0]
        assert event["accuracy_before"] == 80.0
        assert event["accuracy_after"] == 0.0
        assert event["band_distance_before"] == 0.0
        assert event["band_distance_after"] == 60.0
        assert event["band_distance_change"] == 60.0
        assert event["verdict"] == "ineffective"
        assert result["ineffective"] == 1

    def test_a_change_inside_the_tolerance_is_neutral(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("easy", [1, 1, 1, 1, 1]), ("medium", [1, 1, 1, 1, 1])])
        )
        event = result["recent_events"][0]
        assert event["band_distance_before"] == 15.0
        assert event["band_distance_after"] == 15.0
        assert event["verdict"] == "neutral"
        assert result["neutral"] == 1

    def test_events_without_enough_attempts_are_detected_but_not_judged(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("easy", [1, 1, 1, 1, 1]), ("medium", [0]), ("hard", [1] * 5)])
        )
        # easy->medium and medium->hard both changed the served level
        assert result["adaptations_detected"] == 2
        assert result["adaptations_judged"] == 0
        assert result["verdict"] == "insufficient_data"

    def test_the_comparison_window_is_bounded(self):
        """Only the attempts adjacent to the change count, not the whole run."""
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments([("easy", [0] * 20 + [1] * 5), ("medium", [1, 1, 1, 1, 0])]),
            window=5,
        )
        event = result["recent_events"][0]
        assert event["attempts_before"] == 5
        assert event["accuracy_before"] == 100.0  # the 20 failures are outside it

    def test_rate_and_averages_aggregate_across_events(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments(
                [
                    ("easy", [1, 1, 1, 1, 1]),     # 100%, distance 15
                    ("medium", [1, 1, 1, 1, 0]),   # 80%,  distance 0  -> effective
                    ("hard", [0, 0, 0, 0, 0]),     # 0%,   distance 60 -> ineffective
                    ("easy", [1, 1, 1, 0, 1]),     # 80%,  distance 0  -> effective
                ]
            )
        )
        assert result["adaptations_detected"] == 3
        assert result["adaptations_judged"] == 3
        assert result["effective"] == 2
        assert result["ineffective"] == 1
        assert result["effectiveness_rate"] == 66.7
        assert result["avg_band_distance_before"] == 25.0  # (15 + 0 + 60) / 3
        assert result["avg_band_distance_after"] == 20.0   # (0 + 60 + 0) / 3
        assert result["avg_band_distance_change"] == -5.0
        assert result["verdict"] == "neutral"  # -5.0 is inside the tolerance

    def test_verdict_is_effective_when_adaptations_close_the_gap_overall(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments(
                [
                    ("hard", [0, 0, 0, 0, 0]),     # 0%,   distance 60
                    ("medium", [0, 1, 0, 1, 0]),   # 40%,  distance 20 -> -40
                    ("easy", [1, 1, 1, 1, 0]),     # 80%,  distance 0  -> -20
                    ("medium", [1, 1, 1, 1, 1]),   # 100%, distance 15 -> +15
                ]
            )
        )
        assert result["adaptations_judged"] == 3
        assert result["avg_band_distance_change"] == -15.0
        assert result["verdict"] == "effective"

    def test_verdict_is_ineffective_when_adaptations_widen_the_gap(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments(
                [
                    ("medium", [1, 1, 1, 0, 1]),
                    ("expert", [0, 0, 0, 0, 0]),
                    ("medium", [1, 1, 1, 0, 1]),
                    ("expert", [0, 0, 0, 0, 0]),
                ]
            )
        )
        assert result["adaptations_judged"] == 3
        assert result["avg_band_distance_change"] > 5.0
        assert result["verdict"] == "ineffective"

    def test_directions_are_summarized_separately(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments(
                [
                    ("easy", [1, 1, 1, 1, 1]),
                    ("hard", [0, 0, 0, 0, 0]),
                    ("easy", [1, 1, 1, 0, 1]),
                ]
            )
        )
        harder = result["by_direction"]["harder"]
        easier = result["by_direction"]["easier"]
        assert harder["judged"] == 1
        assert harder["ineffective"] == 1
        assert harder["effectiveness_rate"] == 0.0
        assert easier["judged"] == 1
        assert easier["effective"] == 1
        assert easier["effectiveness_rate"] == 100.0

    def test_unknown_difficulties_are_excluded_not_treated_as_a_change(self):
        result = LearningPatternService.analyze_adaptation_effectiveness(
            _segments(
                [
                    ("easy", [1, 1, 1, 1, 1]),
                    ("bogus", [0, 0]),
                    ("easy", [1, 1, 1, 1, 1]),
                ]
            )
        )
        assert result["adaptations_detected"] == 0

    def test_analyzer_accepts_newest_first_or_oldest_first(self):
        newest_first = _segments(
            [("easy", [1, 1, 1, 1, 1]), ("medium", [1, 1, 1, 1, 0])]
        )
        oldest_first = list(reversed(newest_first))
        assert LearningPatternService.analyze_adaptation_effectiveness(
            newest_first
        ) == LearningPatternService.analyze_adaptation_effectiveness(oldest_first)

    def test_empty_history_returns_the_neutral_shape(self):
        result = LearningPatternService.analyze_adaptation_effectiveness([])
        assert result["verdict"] == "insufficient_data"
        assert result["avg_accuracy_before"] is None
        assert result["avg_band_distance_change"] is None
        assert result["recent_events"] == []
        assert result["target_band"] == {"low": 60.0, "high": 85.0}

    def test_learning_profile_carries_the_effectiveness_block(self):
        profile = LearningPatternService.analyze(
            _segments([("easy", [1, 1, 1, 1, 1]), ("medium", [1, 1, 1, 1, 0])])
        )
        assert profile["adaptation_effectiveness"]["adaptations_judged"] == 1
        assert profile["adaptation_effectiveness"]["effective"] == 1

    def test_empty_profile_still_carries_the_effectiveness_block(self):
        profile = LearningPatternService.analyze([])
        assert (
            profile["adaptation_effectiveness"]["verdict"] == "insufficient_data"
        )


# ══════════════════════════════════════════════════════════════════
# Engagement optimization
# ══════════════════════════════════════════════════════════════════


def _disengaged_logs(count=12):
    """Stale, all-wrong, single-type history."""
    base = _now() - timedelta(days=12)
    return list(
        reversed([
            FakeLog(
                is_correct=False,
                challenge_type="math",
                created_at=base + timedelta(hours=i),
            )
            for i in range(count)
        ])
    )


def _thriving_logs(count=20):
    """Recent, perfect, well-varied history spread across distinct days."""
    types = ["math", "logic", "riddle", "quiz"]
    base = _now() - timedelta(days=6)
    return list(
        reversed([
            FakeLog(
                is_correct=True,
                challenge_type=types[i % len(types)],
                created_at=base + timedelta(days=i % 6, hours=i % 5),
            )
            for i in range(count)
        ])
    )


class TestEngagementOptimization:
    """Engagement must produce bounded, evidence-backed engine directives."""

    def test_insufficient_history_is_neutral(self):
        result = EngagementService.analyze(_series([1, 0, 1]))
        assert result["state"] == "insufficient_data"
        assert result["directives"]["difficulty_bias"] == 0
        assert result["directives"]["novelty_boost"] == 0.0
        assert result["directives"]["underused_types"] == []

    def test_no_history_at_all_is_neutral(self):
        result = EngagementService.analyze(None, None)
        assert result["state"] == "insufficient_data"
        assert result["directives"]["difficulty_bias"] == 0

    def test_disengaged_struggling_user_gets_difficulty_eased(self):
        result = EngagementService.analyze(
            _disengaged_logs(),
            [FakeWake(verified=False, dismiss_method="abandoned") for _ in range(4)],
            learning_state="declining",
        )
        assert result["state"] == "disengaged"
        assert result["directives"]["difficulty_bias"] == -1
        assert "Easing difficulty" in result["directives"]["reason"]

    def test_plateaued_engaged_user_gets_difficulty_raised(self):
        result = EngagementService.analyze(
            _thriving_logs(),
            [FakeWake(verified=True) for _ in range(6)],
            learning_state="plateaued",
        )
        assert result["state"] in ("engaged", "thriving")
        assert result["directives"]["difficulty_bias"] == 1
        assert "Raising difficulty" in result["directives"]["reason"]

    def test_engaged_but_still_improving_user_is_not_pushed_up(self):
        """Only a plateau justifies raising — improvement is left alone."""
        result = EngagementService.analyze(
            _thriving_logs(),
            [FakeWake(verified=True) for _ in range(6)],
            learning_state="improving",
        )
        assert result["directives"]["difficulty_bias"] == 0

    def test_high_abandon_rate_alone_does_not_ease_an_engaged_user(self):
        """The easing rule requires low engagement, not just a bad streak."""
        result = EngagementService.analyze(
            _thriving_logs(),
            [FakeWake(verified=False, dismiss_method="abandoned") for _ in range(2)]
            + [FakeWake(verified=True) for _ in range(8)],
            learning_state="steady",
        )
        assert result["directives"]["difficulty_bias"] == 0

    def test_repetitive_type_mix_triggers_a_novelty_boost(self):
        result = EngagementService.analyze(
            _thriving_logs()[:1] + _series([1] * 14, challenge_type="math"),
            [FakeWake(verified=True) for _ in range(4)],
            learning_state="plateaued",
        )
        assert result["signals"]["repeat_pressure"] >= 0.5
        assert result["directives"]["novelty_boost"] > 0
        assert result["directives"]["underused_types"]
        assert "math" not in result["directives"]["underused_types"]

    def test_varied_recent_mix_needs_no_novelty_boost(self):
        result = EngagementService.analyze(
            _thriving_logs(),
            [FakeWake(verified=True) for _ in range(6)],
            learning_state="plateaued",
        )
        assert result["directives"]["novelty_boost"] == 0.0
        assert result["directives"]["underused_types"] == []

    def test_reason_never_claims_variety_without_a_boost(self):
        """At the repeat-pressure boundary the boost is 0 — say nothing.

        Two alternating types put repeat_pressure at exactly the threshold,
        which yields a zero boost and no underused types; the explanation the
        UI shows must not describe an adjustment that never happens.
        """
        alternating = list(
            reversed([
                FakeLog(
                    is_correct=True,
                    challenge_type=("math", "pattern")[i % 2],
                    created_at=_now() - timedelta(days=5) + timedelta(hours=6 * i),
                )
                for i in range(14)
            ])
        )
        result = EngagementService.analyze(
            alternating,
            [FakeWake(verified=True) for _ in range(5)],
            learning_state="improving",
        )
        directives = result["directives"]

        assert result["signals"]["repeat_pressure"] == 0.5
        assert directives["novelty_boost"] == 0.0
        assert directives["underused_types"] == []
        assert "variety" not in directives["reason"].lower()
        assert "under-served" not in directives["reason"].lower()

    def test_reason_states_variety_when_a_boost_is_applied(self):
        result = EngagementService.analyze(
            _series([1] * 16, challenge_type="math"),
            [FakeWake(verified=True) for _ in range(5)],
        )
        directives = result["directives"]
        assert directives["novelty_boost"] > 0
        assert "under-served" in directives["reason"].lower()

    def test_underused_types_are_empty_whenever_the_boost_is_zero(self):
        """The two halves of the novelty directive can never disagree."""
        shapes = [
            (_thriving_logs(), [FakeWake(verified=True)] * 6, "plateaued"),
            (_series([1] * 16, challenge_type="math"), [FakeWake(verified=True)] * 5, None),
            (_disengaged_logs(), [FakeWake(verified=False)] * 4, "declining"),
        ]
        for logs, wakes, state in shapes:
            directives = EngagementService.analyze(
                logs, wakes, learning_state=state
            )["directives"]
            assert bool(directives["underused_types"]) == (
                directives["novelty_boost"] > 0
            )
            mentions_variety = "under-served" in directives["reason"].lower() or (
                "variety" in directives["reason"].lower()
            )
            assert mentions_variety == (directives["novelty_boost"] > 0)

    def test_novelty_boost_is_bounded(self):
        result = EngagementService.analyze(
            _disengaged_logs(30),
            [FakeWake(verified=False) for _ in range(5)],
            learning_state="declining",
        )
        assert 0.0 < result["directives"]["novelty_boost"] <= MAX_NOVELTY_BOOST

    def test_engagement_score_is_bounded(self):
        for logs, wakes in (
            (_disengaged_logs(), [FakeWake(verified=False)]),
            (_thriving_logs(), [FakeWake(verified=True)]),
        ):
            score = EngagementService.analyze(logs, wakes)["engagement_score"]
            assert 0.0 <= score <= 100.0

    def test_difficulty_bias_never_exceeds_one_level(self):
        """Bias is a nudge, never a jump — checked across many shapes."""
        shapes = [
            (_disengaged_logs(40), [FakeWake(verified=False)] * 20, "declining"),
            (_thriving_logs(60), [FakeWake(verified=True)] * 20, "plateaued"),
            (_series([1, 0] * 20), [FakeWake(verified=True)] * 5, "volatile"),
        ]
        for logs, wakes, state in shapes:
            bias = EngagementService.analyze(
                logs, wakes, learning_state=state
            )["directives"]["difficulty_bias"]
            assert bias in (-1, 0, 1)

    def test_wake_events_are_optional(self):
        result = EngagementService.analyze(_thriving_logs(), None)
        assert result["signals"]["wake_events"] == 0
        assert result["directives"]["difficulty_bias"] in (-1, 0, 1)


# ══════════════════════════════════════════════════════════════════
# Engagement improvement (period over period)
# ══════════════════════════════════════════════════════════════════


NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)
PERIOD = ENGAGEMENT_PERIOD_DAYS
# Current period is (NOW-14, NOW]; the one before it is (NOW-28, NOW-14].


def _activity(days_ago_list, *, correct=True, types=("math", "logic", "riddle", "quiz")):
    """One attempt per entry, placed ``days_ago`` before NOW."""
    return [
        FakeLog(
            is_correct=correct,
            challenge_type=types[i % len(types)],
            created_at=(NOW - timedelta(days=d)).replace(tzinfo=None),
        )
        for i, d in enumerate(days_ago_list)
    ]


def _daily(first_days_ago, count, **kwargs):
    """``count`` attempts on consecutive days starting ``first_days_ago`` back."""
    assert count <= first_days_ago + 1, "would place attempts in the future"
    return _activity([first_days_ago - i for i in range(count)], **kwargs)


def _abandons(days_ago_list):
    """Distinct abandoned wake events (never share one object across a list)."""
    events = []
    for d in days_ago_list:
        event = FakeWake(verified=False, dismiss_method="abandoned")
        event.triggered_at = (NOW - timedelta(days=d)).replace(tzinfo=None)
        events.append(event)
    return events


class TestEngagementImprovement:
    """The score is a snapshot; improvement must be a measured delta.

    The earlier reading re-scores only the history that existed at that
    instant, so both endpoints use the same weights.
    """

    def test_ramping_up_after_a_quiet_stretch_is_an_improvement(self):
        # Six stale attempts in the earlier period, then daily activity now.
        history = _activity([27, 26, 25, 24, 23, 22]) + _daily(6, 7)
        result = EngagementService.analyze_improvement(history, now=NOW)

        assert result["status"] == "ok"
        assert result["direction"] == "improving"
        assert result["change"] > 0
        assert result["current_score"] > result["previous_score"]
        assert result["previous_attempts"] == 6
        assert result["current_attempts"] == 7
        assert result["improvement_rate"] > 0

    def test_going_quiet_after_an_active_stretch_is_a_decline(self):
        # Daily activity throughout the earlier period, nothing since.
        history = _daily(21, 7)
        result = EngagementService.analyze_improvement(history, now=NOW)

        assert result["status"] == "ok"
        assert result["direction"] == "declining"
        assert result["change"] < 0
        assert result["current_score"] < result["previous_score"]
        assert result["previous_attempts"] == 7
        assert result["current_attempts"] == 0
        assert result["improvement_rate"] < 0

    def test_the_same_rhythm_in_both_periods_is_stable(self):
        history = _daily(21, 7) + _daily(7, 8)
        result = EngagementService.analyze_improvement(history, now=NOW)

        assert result["status"] == "ok"
        assert result["direction"] == "stable"
        assert abs(result["change"]) <= ENGAGEMENT_IMPROVEMENT_TOLERANCE

    def test_no_history_before_the_earlier_endpoint_is_insufficient_data(self):
        """A brand-new user has nothing to compare against."""
        result = EngagementService.analyze_improvement(_daily(6, 7), now=NOW)

        assert result["status"] == "insufficient_data"
        assert result["direction"] == "insufficient_data"
        assert result["previous_score"] is None
        assert result["change"] is None
        assert result["improvement_rate"] is None
        # Counts are still reported so the UI can explain the gap
        assert result["current_attempts"] == 7
        assert result["previous_attempts"] == 0

    def test_thin_history_at_the_earlier_endpoint_is_not_scored_as_zero(self):
        """Fewer than the minimum sample must not read as a huge improvement."""
        history = _activity([20, 19]) + _daily(6, 7)
        result = EngagementService.analyze_improvement(history, now=NOW)

        assert result["status"] == "insufficient_data"
        assert result["previous_score"] is None
        assert result["previous_attempts"] == 2

    def test_empty_history_is_insufficient_data(self):
        result = EngagementService.analyze_improvement([], now=NOW)
        assert result["status"] == "insufficient_data"
        assert result["current_attempts"] == 0
        assert result["previous_attempts"] == 0
        assert result["period_days"] == PERIOD

    def test_periods_are_adjacent_and_equal_length(self):
        result = EngagementService.analyze_improvement([], now=NOW, period_days=7)
        assert result["period_days"] == 7
        assert result["current_period_end"] == NOW.isoformat()
        assert result["current_period_start"] == (NOW - timedelta(days=7)).isoformat()
        assert result["previous_period_end"] == result["current_period_start"]
        assert result["previous_period_start"] == (
            NOW - timedelta(days=14)
        ).isoformat()

    def test_attempt_and_active_day_counts_are_per_period(self):
        # Two attempts on one day earlier, three separate days now, plus older
        # history that only exists to satisfy the minimum sample.
        history = _activity([30] * 6) + _activity([20, 20]) + _daily(4, 3)
        result = EngagementService.analyze_improvement(history, now=NOW)

        assert result["previous_attempts"] == 2
        assert result["previous_active_days"] == 1
        assert result["current_attempts"] == 3
        assert result["current_active_days"] == 3

    def test_later_activity_cannot_leak_into_the_earlier_reading(self):
        """The earlier score must not see attempts that had not happened yet."""
        past_only = _daily(21, 7)
        with_later = past_only + _daily(6, 7)

        a = EngagementService.analyze_improvement(past_only, now=NOW)
        b = EngagementService.analyze_improvement(with_later, now=NOW)
        assert a["previous_score"] == b["previous_score"]

    def test_wake_events_are_split_by_period_too(self):
        history = _daily(21, 7) + _daily(7, 8)
        result = EngagementService.analyze_improvement(
            history, _abandons([23, 22, 21, 20]), now=NOW
        )
        # Both endpoints see these abandons, so follow-through is penalised in
        # both readings rather than only in the current one.
        assert result["status"] == "ok"
        assert result["previous_score"] is not None
        assert result["change"] > 0

    def test_undated_wake_events_are_excluded_from_the_earlier_reading(self):
        history = _daily(21, 7) + _daily(7, 8)
        undated = [
            FakeWake(verified=False, dismiss_method="abandoned") for _ in range(4)
        ]

        result = EngagementService.analyze_improvement(history, undated, now=NOW)
        # The current reading is penalised by the abandons; the earlier one
        # cannot prove they existed, so it is not.
        assert result["current_score"] < result["previous_score"]

    def test_accepts_newest_first_or_oldest_first(self):
        oldest_first = _daily(21, 7) + _daily(7, 8)
        newest_first = list(reversed(oldest_first))
        assert EngagementService.analyze_improvement(
            oldest_first, now=NOW
        ) == EngagementService.analyze_improvement(newest_first, now=NOW)

    def test_naive_now_is_treated_as_utc(self):
        history = _daily(21, 7) + _daily(7, 8)
        aware = EngagementService.analyze_improvement(history, now=NOW)
        naive = EngagementService.analyze_improvement(
            history, now=NOW.replace(tzinfo=None)
        )
        assert naive["current_score"] == aware["current_score"]

    def test_the_engagement_profile_carries_the_improvement_block(self):
        history = _daily(21, 7) + _daily(7, 8)
        profile = EngagementService.analyze(history, None, now=NOW)
        assert profile["improvement"]["status"] == "ok"
        assert profile["improvement"]["current_score"] == profile["engagement_score"]

    def test_thin_profile_still_carries_the_improvement_block(self):
        profile = EngagementService.analyze(_series([1, 0, 1]))
        assert profile["state"] == "insufficient_data"
        assert profile["improvement"]["status"] == "insufficient_data"


# ══════════════════════════════════════════════════════════════════
# Engine integration (selection + difficulty)
# ══════════════════════════════════════════════════════════════════


class TestEngineIntegration:
    """Directives must actually change what the engine produces."""

    def test_apply_engagement_bias_walks_one_level(self):
        assert ChallengeService.apply_engagement_bias("medium", 1) == "hard"
        assert ChallengeService.apply_engagement_bias("medium", -1) == "easy"
        assert ChallengeService.apply_engagement_bias("medium", 0) == "medium"

    def test_apply_engagement_bias_clamps_at_floor_and_ceiling(self):
        assert ChallengeService.apply_engagement_bias("expert", 1) == "expert"
        assert ChallengeService.apply_engagement_bias("beginner", -1) == "beginner"

    def test_apply_engagement_bias_rejects_out_of_range_input(self):
        """An oversized bias cannot jump multiple levels."""
        assert ChallengeService.apply_engagement_bias("medium", 5) == "hard"
        assert ChallengeService.apply_engagement_bias("medium", -5) == "easy"
        assert ChallengeService.apply_engagement_bias("medium", None) == "medium"

    def test_novelty_boost_shifts_random_type_distribution(self):
        def sample(**kwargs):
            random.seed(20260811)
            hits = 0
            for _ in range(3000):
                if ChallengeService.select_challenge_type(
                    ChallengeType.RANDOM, None, [], **kwargs
                ) == ChallengeType.QUIZ:
                    hits += 1
            return hits

        baseline = sample()
        boosted = sample(novelty_boost=0.6, underused_types=["quiz"])
        assert boosted > baseline * 1.3

    def test_zero_novelty_boost_preserves_existing_selection(self):
        def sample(**kwargs):
            random.seed(99)
            return [
                ChallengeService.select_challenge_type(
                    ChallengeType.RANDOM, None, [], **kwargs
                )
                for _ in range(200)
            ]

        assert sample() == sample(novelty_boost=0.0, underused_types=["quiz"])

    def test_novelty_boost_cannot_introduce_a_non_preferred_type(self):
        """Variety pressure must never override an explicit user preference."""
        random.seed(7)
        for _ in range(300):
            chosen = ChallengeService.select_challenge_type(
                ChallengeType.RANDOM,
                ["math", "logic"],
                [],
                novelty_boost=1.0,
                underused_types=["quiz", "riddle"],
            )
            assert chosen in (ChallengeType.MATH, ChallengeType.LOGIC)

    def test_novelty_boost_never_overrides_a_fixed_alarm_type(self):
        for _ in range(50):
            assert ChallengeService.select_challenge_type(
                ChallengeType.MATH,
                None,
                [],
                novelty_boost=1.0,
                underused_types=["quiz"],
            ) == ChallengeType.MATH

    def test_generate_challenge_applies_the_engagement_bias(self):
        raised = ChallengeService.generate_challenge(
            ChallengeType.MATH,
            difficulty="medium",
            current_hour=12,
            apply_adaptive_difficulty=False,
            engagement_bias=1,
        )
        lowered = ChallengeService.generate_challenge(
            ChallengeType.MATH,
            difficulty="medium",
            current_hour=12,
            apply_adaptive_difficulty=False,
            engagement_bias=-1,
        )
        assert raised["difficulty"] == "hard"
        assert raised["engagement_bias"] == 1
        assert lowered["difficulty"] == "easy"
        assert lowered["engagement_bias"] == -1

    def test_generate_challenge_bias_defaults_to_a_no_op(self):
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH,
            difficulty="medium",
            current_hour=12,
            apply_adaptive_difficulty=False,
        )
        assert result["difficulty"] == "medium"
        assert result["engagement_bias"] == 0

    def test_engagement_bias_respects_the_expert_ceiling(self):
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH,
            difficulty="expert",
            current_hour=12,
            apply_adaptive_difficulty=False,
            engagement_bias=1,
        )
        assert result["difficulty"] == "expert"

    def test_time_limit_follows_the_biased_difficulty(self):
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH,
            difficulty="medium",
            current_hour=12,
            apply_adaptive_difficulty=False,
            engagement_bias=-1,
        )
        assert result["difficulty"] == "easy"
        assert result["time_limit_seconds"] == 45


# ══════════════════════════════════════════════════════════════════
# Runtime wiring through the API
# ══════════════════════════════════════════════════════════════════


@pytest.fixture
def no_time_softening(monkeypatch):
    """Disable groggy-hour softening so difficulty assertions are exact."""
    monkeypatch.setattr(
        challenge_service_module,
        "_adjust_for_time",
        lambda difficulty, current_hour=None: difficulty,
    )


def _make_alarm(client, auth_headers, **overrides):
    payload = {
        "title": "Adaptive",
        "alarm_time": "07:00",
        "challenge_type": "math",
        "challenge_count": 1,
        **overrides,
    }
    response = client.post("/api/v1/alarms/", json=payload, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["id"]


def _seed_logs(
    db_session,
    user_id,
    alarm_id,
    outcomes,
    *,
    days_ago=6,
    spread_days=None,
    types=None,
):
    """Seed attempt history ending ``days_ago`` back, spread over ``spread_days``."""
    from app.models.alarm import AlarmChallengeLog

    types = types or ["math"]
    spread = max(1, days_ago if spread_days is None else spread_days)
    base = _now() - timedelta(days=days_ago)
    for i, outcome in enumerate(outcomes):
        db_session.add(
            AlarmChallengeLog(
                alarm_id=alarm_id,
                user_id=user_id,
                challenge_type=types[i % len(types)],
                difficulty="medium",
                challenge_prompt=f"seed-{i}",
                is_correct=bool(outcome),
                time_taken_seconds=10,
                failed_attempts=0,
                points_earned=5 if outcome else 0,
                created_at=base + timedelta(days=i % spread, hours=i % 5),
            )
        )
    db_session.commit()


def _seed_wakes(db_session, user_id, alarm_id, count, *, verified=True):
    for i in range(count):
        db_session.add(
            AlarmWakeEvent(
                user_id=user_id,
                alarm_id=alarm_id,
                triggered_at=_now() - timedelta(days=i + 1),
                dismissed_at=_now() - timedelta(days=i + 1),
                dismiss_method="challenge" if verified else "abandoned",
                challenges_required=1,
                challenges_completed=1 if verified else 0,
                consecutive_correct=1 if verified else 0,
                failed_attempts=0 if verified else 3,
                snooze_count_at_dismiss=0,
                verified=verified,
            )
        )
    db_session.commit()


class TestAdaptiveEngineRuntimeWiring:
    """The served challenge must genuinely change with history."""

    def test_baseline_user_is_served_the_unbiased_level(
        self, client, test_user, auth_headers, no_time_softening
    ):
        alarm_id = _make_alarm(client, auth_headers)
        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        assert body["difficulty"] == "medium"
        assert body["engagement"]["state"] == "insufficient_data"
        assert body["engagement"]["difficulty_bias"] == 0
        assert body["learning_state"] == "insufficient_data"

    def test_plateaued_engaged_history_raises_the_served_difficulty(
        self, client, test_user, auth_headers, db_session, no_time_softening
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(
            db_session,
            test_user.id,
            alarm_id,
            [1] * 20,
            types=["math", "logic", "riddle", "quiz"],
        )
        _seed_wakes(db_session, test_user.id, alarm_id, 6, verified=True)

        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        assert body["learning_state"] == "plateaued"
        assert body["engagement"]["difficulty_bias"] == 1
        assert body["difficulty"] == "hard"

    def test_disengaged_failing_history_lowers_the_served_difficulty(
        self, client, test_user, auth_headers, db_session, no_time_softening
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(
            db_session, test_user.id, alarm_id, [0] * 12,
            days_ago=12, spread_days=1,
        )
        _seed_wakes(db_session, test_user.id, alarm_id, 5, verified=False)

        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        assert body["engagement"]["state"] == "disengaged"
        assert body["engagement"]["difficulty_bias"] == -1
        assert body["difficulty"] == "easy"

    def test_snooze_escalation_still_dominates_engagement_easing(
        self, client, test_user, auth_headers, db_session, no_time_softening
    ):
        """Anti-snooze must remain the last, winning word on difficulty."""
        alarm_id = _make_alarm(client, auth_headers, snooze_limit=3)
        _seed_logs(
            db_session, test_user.id, alarm_id, [0] * 12,
            days_ago=12, spread_days=1,
        )
        _seed_wakes(db_session, test_user.id, alarm_id, 5, verified=False)

        client.post(f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers)
        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        assert body["engagement"]["difficulty_bias"] == -1
        # medium -1 (engagement) +1 (snooze escalation) == medium
        assert body["difficulty"] == "medium"
        assert body["escalation_level"] == 1

    def test_engagement_never_overrides_the_expert_ceiling(
        self, client, test_user, auth_headers, db_session, no_time_softening
    ):
        pref = client.put(
            "/api/v1/users/profile/preferences",
            json={"difficulty_preference": "expert"},
            headers=auth_headers,
        )
        assert pref.status_code == 200

        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(
            db_session,
            test_user.id,
            alarm_id,
            [1] * 20,
            types=["math", "logic", "riddle", "quiz"],
        )
        _seed_wakes(db_session, test_user.id, alarm_id, 6, verified=True)

        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        assert body["engagement"]["difficulty_bias"] == 1
        assert body["difficulty"] == "expert"

    def test_repetitive_history_makes_the_engine_serve_other_types(
        self, client, test_user, auth_headers, db_session
    ):
        """Novelty pressure must show up in real RANDOM alarm selections."""
        alarm_id = _make_alarm(client, auth_headers, challenge_type="random")
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 16, types=["math"])
        _seed_wakes(db_session, test_user.id, alarm_id, 4, verified=True)

        served = set()
        for _ in range(25):
            body = client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            ).json()
            served.add(body["type"].lower())

        assert len(served) > 1, "novelty boost should diversify served types"

    def test_engagement_payload_shape_is_stable(
        self, client, test_user, auth_headers
    ):
        alarm_id = _make_alarm(client, auth_headers)
        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()

        for key in ("state", "score", "difficulty_bias", "novelty_boost", "reason"):
            assert key in body["engagement"]
        assert body["engagement"]["difficulty_bias"] in (-1, 0, 1)


class TestLearningProfileEndpoint:
    """GET /alarms/challenge/learning-profile."""

    def test_returns_full_profile(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 20)
        _seed_wakes(db_session, test_user.id, alarm_id, 5, verified=True)

        response = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()

        assert body["learning_patterns"]["learning_state"] == "plateaued"
        assert body["learning_patterns"]["by_type"]["math"]["attempts"] == 20
        assert body["learning_patterns"]["optimal_difficulty"] == "medium"
        assert body["difficulty_levels"] == [
            "beginner", "easy", "medium", "hard", "expert"
        ]
        assert body["current_baseline_difficulty"] == "medium"
        assert body["engagement"]["directives"]["difficulty_bias"] in (-1, 0, 1)
        assert body["projected_difficulty"] in DIFFICULTY_LEVELS

    def test_adaptation_effectiveness_is_computed_from_stored_attempts(
        self, client, test_user, auth_headers, db_session
    ):
        """End to end over real AlarmChallengeLog rows, not fake objects."""
        from app.models.alarm import AlarmChallengeLog

        alarm_id = _make_alarm(client, auth_headers)
        base = _now() - timedelta(days=10)
        hour = 0
        # easy at 100% (15 pts above the band) -> medium at 80% (inside it)
        for difficulty, outcomes in (
            ("easy", [1, 1, 1, 1, 1]),
            ("medium", [1, 1, 1, 1, 0]),
        ):
            for outcome in outcomes:
                db_session.add(
                    AlarmChallengeLog(
                        alarm_id=alarm_id,
                        user_id=test_user.id,
                        challenge_type="math",
                        difficulty=difficulty,
                        challenge_prompt=f"seed-{hour}",
                        is_correct=bool(outcome),
                        time_taken_seconds=10,
                        failed_attempts=0,
                        points_earned=5 if outcome else 0,
                        created_at=base + timedelta(hours=hour),
                    )
                )
                hour += 1
        db_session.commit()

        body = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        ).json()
        adaptation = body["learning_patterns"]["adaptation_effectiveness"]

        assert adaptation["adaptations_detected"] == 1
        assert adaptation["adaptations_judged"] == 1
        assert adaptation["effective"] == 1
        assert adaptation["effectiveness_rate"] == 100.0
        assert adaptation["avg_accuracy_before"] == 100.0
        assert adaptation["avg_accuracy_after"] == 80.0
        assert adaptation["avg_band_distance_change"] == -15.0
        assert adaptation["recent_events"][0]["from_difficulty"] == "easy"
        assert adaptation["recent_events"][0]["to_difficulty"] == "medium"

    def test_challenge_analysis_carries_the_effectiveness_block(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 12)

        body = client.get(
            "/api/v1/alarms/challenge/analysis", headers=auth_headers
        ).json()
        adaptation = body["personalization"]["learning_patterns"][
            "adaptation_effectiveness"
        ]
        # One difficulty all the way through, so there is nothing to judge.
        assert adaptation["adaptations_detected"] == 0
        assert adaptation["verdict"] == "insufficient_data"

    def test_engagement_improvement_is_computed_from_stored_attempts(
        self, client, test_user, auth_headers, db_session
    ):
        """End to end over real AlarmChallengeLog rows.

        Daily activity throughout the previous 14-day period and silence since
        must read as a decline, not as a healthy point-in-time score.
        """
        from app.models.alarm import AlarmChallengeLog

        alarm_id = _make_alarm(client, auth_headers)
        for offset in range(21, 14, -1):
            db_session.add(
                AlarmChallengeLog(
                    alarm_id=alarm_id,
                    user_id=test_user.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt=f"seed-{offset}",
                    is_correct=True,
                    time_taken_seconds=10,
                    failed_attempts=0,
                    points_earned=5,
                    created_at=_now() - timedelta(days=offset),
                )
            )
        db_session.commit()

        body = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        ).json()
        improvement = body["engagement"]["improvement"]

        assert improvement["status"] == "ok"
        assert improvement["direction"] == "declining"
        assert improvement["previous_attempts"] == 7
        assert improvement["current_attempts"] == 0
        assert improvement["change"] < 0
        assert improvement["current_score"] < improvement["previous_score"]
        assert improvement["period_days"] == ENGAGEMENT_PERIOD_DAYS

    def test_engagement_improvement_needs_history_before_the_window(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 12, days_ago=5)

        body = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        ).json()
        improvement = body["engagement"]["improvement"]

        assert improvement["status"] == "insufficient_data"
        assert improvement["previous_score"] is None
        assert improvement["change"] is None

    def test_empty_history_returns_a_safe_profile(self, client, auth_headers):
        response = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["learning_patterns"]["learning_state"] == "insufficient_data"
        assert body["projected_difficulty"] == body["current_baseline_difficulty"]

    def test_challenge_analysis_carries_the_same_profile(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 20)

        body = client.get(
            "/api/v1/alarms/challenge/analysis", headers=auth_headers
        ).json()
        personalization = body["personalization"]
        assert personalization["learning_patterns"]["learning_state"] == "plateaued"
        assert "engagement" in personalization


# ══════════════════════════════════════════════════════════════════
# Ownership, isolation, and robustness
# ══════════════════════════════════════════════════════════════════


class TestAdaptiveEngineSecurity:
    """The engine must not leak answers or cross user boundaries."""

    def test_learning_profile_requires_authentication(self, client):
        assert client.get(
            "/api/v1/alarms/challenge/learning-profile"
        ).status_code == 401

    def test_learning_profile_is_scoped_to_the_caller(
        self, client, test_user, auth_headers, admin_user, admin_headers, db_session
    ):
        """One user's history must never shape another user's engine."""
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 20)
        _seed_wakes(db_session, test_user.id, alarm_id, 5, verified=True)

        owner = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=auth_headers
        ).json()
        other = client.get(
            "/api/v1/alarms/challenge/learning-profile", headers=admin_headers
        ).json()

        assert owner["learning_patterns"]["sample_size"] == 20
        assert other["learning_patterns"]["sample_size"] == 0
        assert other["learning_patterns"]["learning_state"] == "insufficient_data"
        assert other["engagement"]["directives"]["difficulty_bias"] == 0

    def test_another_users_history_does_not_bias_served_difficulty(
        self, client, test_user, auth_headers, admin_user, admin_headers,
        db_session, no_time_softening,
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(
            db_session, test_user.id, alarm_id, [1] * 20,
            types=["math", "logic", "riddle", "quiz"],
        )
        _seed_wakes(db_session, test_user.id, alarm_id, 6, verified=True)

        other_alarm = _make_alarm(client, admin_headers, title="Admin alarm")
        body = client.get(
            f"/api/v1/alarms/{other_alarm}/challenge", headers=admin_headers
        ).json()

        assert body["engagement"]["difficulty_bias"] == 0
        assert body["difficulty"] == "medium"

    def test_new_engine_fields_never_leak_the_answer(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = _make_alarm(client, auth_headers)
        _seed_logs(db_session, test_user.id, alarm_id, [1] * 20)

        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        assert "answer" not in body
        assert "answer" not in body["engagement"]
        assert "answer" not in str(body["engagement"]).lower()

    def test_client_cannot_inject_an_engagement_bias(
        self, client, test_user, auth_headers, no_time_softening
    ):
        """Bias is server-derived; query params must not move it."""
        alarm_id = _make_alarm(client, auth_headers)
        body = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge",
            params={
                "engagement_bias": 1,
                "difficulty": "expert",
                "novelty_boost": 1.0,
            },
            headers=auth_headers,
        ).json()

        assert body["engagement"]["difficulty_bias"] == 0
        assert body["difficulty"] == "medium"

    def test_analyzers_survive_dirty_history_rows(self):
        """Legacy/dirty rows must not crash the engine at ring time."""
        dirty = [
            FakeLog(challenge_type=None, difficulty=None, created_at=None),
            FakeLog(is_correct=None, time_taken_seconds=-5, difficulty="bogus"),
            FakeLog(time_taken_seconds="not-a-number", challenge_type=""),
            FakeLog(difficulty="EXPERT", challenge_type="WORD"),
            FakeLog(failed_attempts=None),
        ] * 3

        patterns = LearningPatternService.analyze(dirty, tz_name="")
        engagement = EngagementService.analyze(dirty, [FakeWake(verified=None)])

        assert patterns["learning_state"] in {
            "insufficient_data", "improving", "declining",
            "plateaued", "volatile", "steady", "struggling",
        }
        assert "bogus" not in patterns["by_difficulty"]
        assert engagement["directives"]["difficulty_bias"] in (-1, 0, 1)
        assert 0.0 <= engagement["directives"]["novelty_boost"] <= MAX_NOVELTY_BOOST

    def test_underused_types_only_reference_real_challenge_types(self):
        result = EngagementService.analyze(
            _series([1] * 16, challenge_type="math"),
            [FakeWake(verified=True) for _ in range(4)],
        )
        valid = {ct.value for ct in SELECTABLE_CHALLENGE_TYPES}
        assert set(result["directives"]["underused_types"]) <= valid
