"""
Cognitive challenge generation latency, measured at runtime.

``perf/subsystems.py`` timed ``generate_challenge`` offline, which is useful
for a signed-off number but cannot fail a build: nothing ran it, and nothing
observed generation inside a live process. Generation sits on the critical path
of a ringing alarm — the user is standing there waiting for a puzzle — so it is
now instrumented in ``app/core/challenge_metrics.py`` and asserted here.

These are real wall-clock assertions. They stay stable because the budget has
enormous headroom: procedural generation measures well under a millisecond
against a 50 ms budget, so only a structural regression (a bank scan that grew
with history, a blocking call added to the hot path) can trip them.
"""

import time

import pytest

from app.core.challenge_metrics import (
    ChallengeGenerationRegistry,
    challenge_generation,
    measure_generation,
)
from app.core.config import settings
from app.core.request_metrics import percentile
from app.models.alarm import ChallengeType
from app.services.challenge_service import DIFFICULTY_LEVELS, ChallengeService

#: Generations per (type, difficulty) pair. Enough for a stable p95.
ITERATIONS = 25

#: Concrete types the alarm flow can serve. RANDOM resolves into one of these.
GENERATED_TYPES = [
    ChallengeType.MATH,
    ChallengeType.LOGIC,
    ChallengeType.MEMORY,
    ChallengeType.WORD_GAME,
    ChallengeType.PATTERN,
    ChallengeType.RIDDLE,
    ChallengeType.QUIZ,
]


@pytest.fixture(autouse=True)
def clean_registry():
    """The reservoir is process-global; isolate each test."""
    challenge_generation.reset()
    yield
    challenge_generation.reset()


def _generate(challenge_type, difficulty="medium", **kwargs):
    # current_hour is pinned so time-of-day softening cannot make a
    # measurement depend on when the suite happens to run.
    return ChallengeService.generate_challenge(
        challenge_type, difficulty=difficulty, current_hour=7, **kwargs
    )


class TestGenerationIsMeasured:
    def test_every_generation_is_recorded(self):
        for _ in range(5):
            _generate(ChallengeType.MATH)

        snapshot = challenge_generation.snapshot()
        assert snapshot["total_generations"] == 5
        assert snapshot["total_failures"] == 0
        assert snapshot["keys_tracked"] == 1
        assert snapshot["overall"]["sampled"] == 5

    def test_samples_are_keyed_by_type_difficulty_and_source(self):
        _generate(ChallengeType.MATH, difficulty="easy")
        _generate(ChallengeType.LOGIC, difficulty="hard")

        keys = {row["key"] for row in challenge_generation.snapshot()["by_key"]}
        assert keys == {"math/easy/procedural", "logic/hard/procedural"}

    def test_the_ai_path_is_not_averaged_into_the_procedural_path(self):
        """A slow provider must be visible, not diluted by fast fallbacks."""
        registry = ChallengeGenerationRegistry(sample_size=10)
        for _ in range(3):
            registry.record(
                challenge_type="math",
                difficulty="medium",
                source="procedural",
                duration_ms=0.4,
            )
        registry.record(
            challenge_type="math",
            difficulty="medium",
            source="ai",
            duration_ms=1800.0,
        )

        by_key = {row["key"]: row for row in registry.snapshot()["by_key"]}
        assert by_key["math/medium/procedural"]["p95_ms"] < 1.0
        assert by_key["math/medium/ai"]["p95_ms"] == 1800.0

    def test_a_failed_generation_is_still_timed(self):
        with pytest.raises(RuntimeError):
            with measure_generation() as timer:
                timer.describe("math", "medium", "ai")
                raise RuntimeError("provider timed out")

        snapshot = challenge_generation.snapshot()
        assert snapshot["total_generations"] == 1
        assert snapshot["total_failures"] == 1

    def test_instrumentation_can_be_switched_off(self, monkeypatch):
        monkeypatch.setattr(settings, "CHALLENGE_METRICS_ENABLED", False)
        _generate(ChallengeType.MATH)
        assert challenge_generation.snapshot()["total_generations"] == 0

    def test_the_reservoir_is_bounded(self):
        registry = ChallengeGenerationRegistry(sample_size=5)
        for i in range(50):
            registry.record(
                challenge_type="math",
                difficulty="medium",
                source="procedural",
                duration_ms=float(i),
            )

        snapshot = registry.snapshot()
        assert snapshot["total_generations"] == 50  # counters never roll off
        assert snapshot["by_key"][0]["sampled"] == 5  # durations do
        assert snapshot["by_key"][0]["min_ms"] == 45.0

    def test_percentiles_are_ordered(self):
        for difficulty in DIFFICULTY_LEVELS:
            for _ in range(ITERATIONS):
                _generate(ChallengeType.MATH, difficulty=difficulty)

        overall = challenge_generation.snapshot()["overall"]
        assert overall["min_ms"] <= overall["p50_ms"] <= overall["p95_ms"]
        assert overall["p95_ms"] <= overall["p99_ms"] <= overall["max_ms"]


class TestGenerationBudget:
    """The whole point: a regression in generation cost fails the build."""

    @pytest.mark.parametrize("challenge_type", GENERATED_TYPES, ids=lambda t: t.value)
    def test_each_type_generates_inside_the_budget(self, challenge_type):
        budget = settings.CHALLENGE_GENERATION_BUDGET_MS
        for i in range(ITERATIONS):
            _generate(
                challenge_type,
                difficulty=DIFFICULTY_LEVELS[i % len(DIFFICULTY_LEVELS)],
            )

        durations = challenge_generation.all_durations()
        assert len(durations) == ITERATIONS
        p95 = percentile(durations, 95)
        assert p95 <= budget, (
            f"{challenge_type.value} generation p95 is {p95:.2f}ms "
            f"against a {budget}ms budget"
        )

    def test_random_type_selection_stays_inside_the_budget(self):
        """RANDOM adds fair-rotation weighting on top of generation."""
        for _ in range(ITERATIONS):
            _generate(ChallengeType.RANDOM)

        p95 = percentile(challenge_generation.all_durations(), 95)
        assert p95 <= settings.CHALLENGE_GENERATION_BUDGET_MS

    def test_the_anti_repeat_window_does_not_scale_generation_cost(self):
        """Prompt exclusion is the one input that grows with user history."""
        def measure(exclude):
            challenge_generation.reset()
            for _ in range(ITERATIONS):
                _generate(ChallengeType.MATH, exclude_prompts=exclude)
            return percentile(challenge_generation.all_durations(), 95)

        small = measure([f"stale prompt {i}" for i in range(5)])
        large = measure([f"stale prompt {i}" for i in range(500)])

        assert large <= settings.CHALLENGE_GENERATION_BUDGET_MS
        # Generous ratio: this catches O(n) rescans, not measurement noise.
        assert large <= max(small * 20.0, 5.0), (
            f"100x more excluded prompts moved p95 from {small:.2f}ms to {large:.2f}ms"
        )

    def test_a_ringing_alarm_serves_a_challenge_inside_the_budget(
        self, client, auth_headers, db_session, test_user
    ):
        """End to end through the endpoint that a ringing alarm calls."""
        from datetime import time as time_cls

        from app.models.alarm import Alarm, AlarmType

        alarm = Alarm(
            user_id=test_user.id,
            title="Latency Alarm",
            alarm_time=time_cls(7, 0),
            alarm_type=AlarmType.DAILY,
            challenge_type=ChallengeType.MATH,
            challenge_count=1,
            challenge_difficulty="medium",
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        challenge_generation.reset()
        for _ in range(5):
            res = client.get(
                f"/api/v1/alarms/{alarm.id}/challenge", headers=auth_headers
            )
            assert res.status_code == 200

        durations = challenge_generation.all_durations()
        assert len(durations) >= 5, "the request path must go through generation"
        assert percentile(durations, 95) <= settings.CHALLENGE_GENERATION_BUDGET_MS


class TestGenerationMetricsEndpoint:
    def test_admin_can_read_generation_latency(self, client, admin_headers):
        for _ in range(5):
            _generate(ChallengeType.MATH, difficulty="medium")

        body = client.get("/api/v1/system/metrics", headers=admin_headers).json()
        block = body["challenge_generation"]

        assert block["total_generations"] == 5
        assert block["budget_ms"] == settings.CHALLENGE_GENERATION_BUDGET_MS
        assert block["overall"]["p95_ms"] <= block["budget_ms"]
        row = next(r for r in block["by_key"] if r["key"] == "math/medium/procedural")
        assert row["calls"] == 5
        assert row["challenge_type"] == "math"
        assert row["source"] == "procedural"

    def test_generation_latency_is_admin_only(self, client, auth_headers):
        assert client.get("/api/v1/system/metrics").status_code == 401
        assert (
            client.get("/api/v1/system/metrics", headers=auth_headers).status_code
            == 403
        )


def test_measurement_reflects_real_elapsed_time():
    """Guard the instrumentation itself: a slow call must read as slow."""
    with measure_generation() as timer:
        timer.describe("math", "medium", "procedural")
        time.sleep(0.05)

    durations = challenge_generation.durations_for("math", "medium", "procedural")
    assert len(durations) == 1
    assert 40.0 <= durations[0] <= 500.0
