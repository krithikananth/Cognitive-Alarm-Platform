"""
Tests for the Cognitive Challenge Engine.

Covers:
- ChallengeService unit tests (generation, verification, difficulty, time-of-day)
- Challenge API endpoint integration tests (/challenge, /verify, /history, /stats)
- Multi-step challenge flow
- Time-limit enforcement
- Snooze restriction info endpoint
- Per-attempt logging (correct + incorrect)
"""

import pytest
from app.services.challenge_service import (
    ChallengeService,
    _adjust_for_time,
    _adaptive_streak_threshold,
    DIFFICULTY_LEVELS,
)
from app.models.alarm import ChallengeType, AlarmChallengeLog


# ═══════════════════════════════════════════════════════════════
# Unit Tests — ChallengeService
# ═══════════════════════════════════════════════════════════════

class TestChallengeGeneration:
    """Tests for ChallengeService.generate_challenge()."""

    def test_generate_math_returns_valid_structure(self):
        """Math challenge should have type, prompt, answer, options, difficulty, time_limit."""
        result = ChallengeService.generate_challenge(ChallengeType.MATH)
        assert result["type"] == "MATH"
        assert "prompt" in result
        assert "answer" in result
        assert "options" in result
        assert "difficulty" in result
        assert "time_limit_seconds" in result
        assert isinstance(result["options"], list)
        assert len(result["options"]) == 4

    def test_generate_pattern_returns_valid_structure(self):
        """Pattern challenge should have the correct structure."""
        result = ChallengeService.generate_challenge(ChallengeType.PATTERN)
        assert result["type"] == "PATTERN"
        assert "comes next" in result["prompt"].lower()
        assert result["answer"]
        assert isinstance(result["options"], list)
        assert len(result["options"]) == 4
        assert result["answer"] in result["options"]

    def test_generate_pattern_varies_across_categories(self):
        """Repeated generation should yield more than only digit answers."""
        answers = []
        for _ in range(40):
            result = ChallengeService.generate_challenge(
                ChallengeType.PATTERN, current_hour=10
            )
            assert result["type"] == "PATTERN"
            assert len(result["options"]) == 4
            assert result["answer"] in result["options"]
            answers.append(result["answer"])
        # At least one non-numeric answer across many draws (category variety)
        non_numeric = [
            a for a in answers
            if not (a.isdigit() or a.lstrip("-").isdigit())
        ]
        assert len(non_numeric) >= 1

    def test_generate_memory_returns_digit_sequence(self):
        """Memory challenge prompt should be all digits with no options."""
        result = ChallengeService.generate_challenge(ChallengeType.MEMORY)
        assert result["type"] == "MEMORY"
        assert result["prompt"].isdigit()
        assert result["answer"] == result["prompt"]
        assert result["options"] is None

    def test_generate_riddle_returns_question_with_options(self):
        """Riddle challenge should have a question and 4 options."""
        result = ChallengeService.generate_challenge(ChallengeType.RIDDLE)
        assert result["type"] == "RIDDLE"
        assert "?" in result["prompt"]
        assert len(result["options"]) == 4
        assert result["answer"] in result["options"]

    def test_generate_logic_returns_valid_structure(self):
        """Logic challenge should have a prompt, answer, and 4 options."""
        result = ChallengeService.generate_challenge(
            ChallengeType.LOGIC, current_hour=10
        )
        assert result["type"] == "LOGIC"
        assert result["prompt"]
        assert len(result["options"]) == 4
        assert result["answer"] in result["options"]

    def test_generate_word_game_returns_valid_structure(self):
        """Word game should return WORD_GAME with answer among options."""
        result = ChallengeService.generate_challenge(
            ChallengeType.WORD_GAME, current_hour=10
        )
        assert result["type"] == "WORD_GAME"
        assert result["prompt"]
        assert len(result["options"]) == 4
        assert result["answer"] in result["options"]

    def test_generate_word_alias_maps_to_word_game(self):
        """Frontend WORD alias should produce a WORD_GAME challenge."""
        result = ChallengeService.generate_challenge(
            ChallengeType.WORD, current_hour=10
        )
        assert result["type"] == "WORD_GAME"

    def test_generate_quiz_returns_valid_structure(self):
        """Quiz challenge should have a question and 4 options."""
        result = ChallengeService.generate_challenge(
            ChallengeType.QUIZ, current_hour=10
        )
        assert result["type"] == "QUIZ"
        assert "?" in result["prompt"]
        assert len(result["options"]) == 4
        assert result["answer"] in result["options"]

    def test_generate_random_resolves_to_real_type(self):
        """RANDOM type should resolve to an actual challenge type."""
        result = ChallengeService.generate_challenge(ChallengeType.RANDOM)
        assert result["type"] in [
            "MATH", "LOGIC", "PATTERN", "MEMORY", "WORD_GAME", "RIDDLE", "QUIZ",
        ]

    def test_random_uses_preferred_types_only(self):
        """RANDOM with preferred types should stay inside that pool."""
        preferred = ["math", "riddle"]
        for _ in range(20):
            result = ChallengeService.generate_challenge(
                ChallengeType.RANDOM,
                preferred_types=preferred,
                current_hour=10,
                apply_adaptive_difficulty=False,
            )
            assert result["type"] in ["MATH", "RIDDLE"]

    def test_random_covers_all_supported_types_fairly(self):
        """RANDOM without preferences should sample across every selectable type."""
        seen = set()
        for _ in range(120):
            result = ChallengeService.generate_challenge(
                ChallengeType.RANDOM,
                current_hour=10,
                apply_adaptive_difficulty=False,
            )
            seen.add(result["type"])
        assert seen == {
            "MATH", "LOGIC", "PATTERN", "MEMORY", "WORD_GAME", "RIDDLE", "QUIZ",
        }

    def test_select_challenge_type_avoids_recent_type_bias(self):
        """Recent types should be deprioritized, not dominate RANDOM selection."""
        class FakeLog:
            def __init__(self, ct):
                self.challenge_type = ct
                self.is_correct = True

        # Flood recent history with MATH — fair selector should still pick others
        logs = [FakeLog("math") for _ in range(7)]
        picks = [
            ChallengeService.select_challenge_type(
                ChallengeType.RANDOM, recent_logs=logs
            ).value
            for _ in range(80)
        ]
        non_math = sum(1 for p in picks if p != "math")
        assert non_math >= 40

    def test_exclude_prompts_avoids_recent_bank_question(self):
        """Bank challenges should skip recently shown prompts when alternatives exist."""
        banks = ChallengeService._riddle_banks()["easy"]
        first = banks[0]
        result = ChallengeService.generate_challenge(
            ChallengeType.RIDDLE,
            difficulty="beginner",
            current_hour=10,
            apply_adaptive_difficulty=False,
            exclude_prompts=[first["q"]],
        )
        assert result["prompt"].strip().lower() != first["q"].strip().lower()

    def test_generate_challenge_recovers_from_generator_failure(self):
        """Generation should regenerate instead of crashing on transient failures."""
        original = ChallengeService._generate_math
        calls = {"n": 0}

        def flaky(difficulty="medium"):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("simulated generation failure")
            return original(difficulty)

        ChallengeService._generate_math = staticmethod(flaky)
        try:
            result = ChallengeService.generate_challenge(
                ChallengeType.MATH,
                current_hour=10,
                apply_adaptive_difficulty=False,
            )
            assert result["type"] == "MATH"
            assert result["answer"]
            assert calls["n"] >= 3
        finally:
            ChallengeService._generate_math = original

    def test_validate_generated_challenge_rejects_inconsistent_mcq(self):
        """Pre-serve validation must reject inconsistent option sets."""
        with pytest.raises(ValueError):
            ChallengeService._validate_generated_challenge(
                {
                    "type": "QUIZ",
                    "prompt": "Sample question?",
                    "answer": "A",
                    "options": ["B", "C", "D", "E"],
                }
            )

    def test_resolve_baseline_prefers_profile(self):
        """Profile difficulty preference is the initial baseline."""
        class FakeProfile:
            class Pref:
                value = "hard"

            difficulty_preference = Pref()

        assert (
            ChallengeService.resolve_baseline_difficulty(FakeProfile(), "easy")
            == "hard"
        )
        assert (
            ChallengeService.resolve_baseline_difficulty(None, "expert")
            == "expert"
        )
        assert ChallengeService.resolve_baseline_difficulty(None, None) == "medium"

    def test_adapt_difficulty_raises_on_consecutive_success(self):
        """N consecutive successes should raise difficulty."""
        n = _adaptive_streak_threshold()

        class FakeLog:
            def __init__(self, correct):
                self.is_correct = correct
                self.time_taken_seconds = 8
                self.challenge_type = "math"

        logs = [FakeLog(True) for _ in range(n)]
        adapted = ChallengeService.adapt_difficulty("medium", logs)
        assert adapted["difficulty"] == "hard"
        assert adapted["adjustment"] == 1
        assert adapted["success_streak"] == n
        assert adapted["failure_streak"] == 0

    def test_adapt_difficulty_centers_on_preferred_level(self):
        """Adaptive ±1 should move around the user's preferred baseline."""
        n = _adaptive_streak_threshold()

        raised = ChallengeService.adapt_difficulty(
            "hard",
            success_streak=n,
            failure_streak=0,
        )
        assert raised["difficulty"] == "expert"
        assert raised["adjustment"] == 1

        lowered = ChallengeService.adapt_difficulty(
            "hard",
            success_streak=0,
            failure_streak=n,
        )
        assert lowered["difficulty"] == "medium"
        assert lowered["adjustment"] == -1

    def test_adapt_difficulty_lowers_on_consecutive_failure(self):
        """N consecutive failures should lower difficulty."""
        n = _adaptive_streak_threshold()

        class FakeLog:
            def __init__(self, correct):
                self.is_correct = correct
                self.time_taken_seconds = 40
                self.challenge_type = "math"

        logs = [FakeLog(False) for _ in range(n)]
        adapted = ChallengeService.adapt_difficulty("medium", logs)
        assert adapted["difficulty"] == "easy"
        assert adapted["adjustment"] == -1
        assert adapted["failure_streak"] == n
        assert adapted["success_streak"] == 0

    def test_adapt_difficulty_no_change_below_threshold(self):
        """Fewer than N consecutive outcomes must not adapt."""
        n = _adaptive_streak_threshold()

        adapted = ChallengeService.adapt_difficulty(
            "medium",
            success_streak=n - 1,
            failure_streak=0,
        )
        assert adapted["adjustment"] == 0
        assert adapted["difficulty"] == "medium"

    def test_adapt_difficulty_watermark_blocks_refire(self):
        """Already-consumed streak windows must not raise difficulty again."""
        n = _adaptive_streak_threshold()

        pending = ChallengeService.adapt_difficulty(
            "medium",
            success_streak=n,
            failure_streak=0,
            last_adapted_success_streak=0,
        )
        assert pending["adjustment"] == 1
        assert pending["effective_success_streak"] == n

        consumed = ChallengeService.adapt_difficulty(
            "hard",
            success_streak=n,
            failure_streak=0,
            last_adapted_success_streak=n,
        )
        assert consumed["adjustment"] == 0
        assert consumed["success_streak"] == n
        assert consumed["effective_success_streak"] == 0

        next_window = ChallengeService.adapt_difficulty(
            "hard",
            success_streak=n * 2,
            failure_streak=0,
            last_adapted_success_streak=n,
        )
        assert next_window["adjustment"] == 1
        assert next_window["effective_success_streak"] == n

    def test_adapt_difficulty_streak_reset_breaks_consecutive(self):
        """Opposite outcome in trailing logs must break the streak."""
        n = _adaptive_streak_threshold()

        class FakeLog:
            def __init__(self, correct):
                self.is_correct = correct

        # Newest-first: N-1 successes then a failure → success streak < N
        logs = [FakeLog(True) for _ in range(n - 1)] + [
            FakeLog(False)
        ] + [FakeLog(True) for _ in range(n)]
        adapted = ChallengeService.adapt_difficulty("medium", logs)
        assert adapted["success_streak"] == n - 1
        assert adapted["failure_streak"] == 0
        assert adapted["adjustment"] == 0

    def test_adapt_difficulty_stored_counters_override_logs(self):
        """Explicit streak counters take precedence over log derivation."""
        n = _adaptive_streak_threshold()

        class FakeLog:
            def __init__(self, correct):
                self.is_correct = correct

        # Logs alone would raise; stored counters say not yet.
        logs = [FakeLog(True) for _ in range(n)]
        adapted = ChallengeService.adapt_difficulty(
            "medium",
            logs,
            success_streak=2,
            failure_streak=0,
        )
        assert adapted["adjustment"] == 0
        assert adapted["success_streak"] == 2

    def test_adapt_difficulty_edge_ceiling_and_floor(self):
        """At expert/beginner the level clamps even when streak hits N."""
        n = _adaptive_streak_threshold()

        at_top = ChallengeService.adapt_difficulty(
            "expert",
            success_streak=n,
            failure_streak=0,
        )
        assert at_top["difficulty"] == "expert"
        assert at_top["adjustment"] == 0

        at_bottom = ChallengeService.adapt_difficulty(
            "beginner",
            success_streak=0,
            failure_streak=n,
        )
        assert at_bottom["difficulty"] == "beginner"
        assert at_bottom["adjustment"] == 0

    def test_compute_trailing_streaks_empty_and_mixed(self):
        """Trailing streak helper covers empty and mixed edge cases."""
        class FakeLog:
            def __init__(self, correct):
                self.is_correct = correct

        empty = ChallengeService.compute_trailing_streaks([])
        assert empty == {"success_streak": 0, "failure_streak": 0}

        mixed = ChallengeService.compute_trailing_streaks(
            [FakeLog(False), FakeLog(False), FakeLog(True)]
        )
        assert mixed == {"success_streak": 0, "failure_streak": 2}

    def test_analyze_completion_returns_recommendations(self):
        """Analysis should include summary, insights, and recommendations."""
        class FakeLog:
            def __init__(self, ct, correct, seconds=10, diff="medium", points=20):
                self.challenge_type = ct
                self.is_correct = correct
                self.time_taken_seconds = seconds
                self.difficulty = diff
                self.points_earned = points

        logs = (
            [FakeLog("math", True) for _ in range(6)]
            + [FakeLog("logic", False) for _ in range(5)]
            + [FakeLog("logic", True)]
        )
        analysis = ChallengeService.analyze_completion(logs)
        assert analysis["summary"]["total_attempts"] == 12
        assert "recommendations" in analysis
        assert len(analysis["recommendations"]) >= 1
        assert "insights" in analysis
        assert "by_type" in analysis
        assert "math" in analysis["by_type"]
        assert "logic" in analysis["by_type"]

    def test_all_types_return_difficulty_and_time_limit(self):
        """Every challenge type should include difficulty and time_limit_seconds."""
        for ct in ChallengeType:
            result = ChallengeService.generate_challenge(ct, difficulty="medium")
            assert "difficulty" in result, f"{ct.value} missing difficulty"
            assert "time_limit_seconds" in result, f"{ct.value} missing time_limit"


class TestChallengeAnswerUniqueness:
    """Every MCQ must expose exactly one unambiguous correct option."""

    def _assert_valid_mcq(self, result):
        assert result["answer"]
        assert isinstance(result["options"], list)
        assert len(result["options"]) == 4
        assert len({o.strip().lower() for o in result["options"]}) == 4
        assert result["answer"] in result["options"]
        ChallengeService.validate_mcq_item(
            result["prompt"], result["answer"], result["options"]
        )

    def test_static_riddle_bank_items_are_unambiguous(self):
        """Every curated riddle must validate with one clear correct option."""
        banks = ChallengeService._riddle_banks()
        for tier, items in banks.items():
            for item in items:
                options = ChallengeService.validate_mcq_item(
                    item["q"], item["a"], item["opts"]
                )
                assert item["a"] in options
                assert len(options) == 4, f"riddle/{tier}: {item['q']}"

    def test_static_logic_and_quiz_banks_are_unambiguous(self):
        """Logic and quiz banks must each have one factual/correct option."""
        for name, banks in (
            ("logic", ChallengeService._logic_banks()),
            ("quiz", ChallengeService._quiz_banks()),
        ):
            for tier, items in banks.items():
                for item in items:
                    ChallengeService.validate_mcq_item(
                        item["q"], item["a"], item["opts"]
                    )

    def test_generated_mcq_types_always_have_one_correct_option(self):
        """Generated challenges should never present duplicate or missing answers."""
        mcq_types = [
            ChallengeType.MATH,
            ChallengeType.LOGIC,
            ChallengeType.PATTERN,
            ChallengeType.WORD_GAME,
            ChallengeType.RIDDLE,
            ChallengeType.QUIZ,
        ]
        for ct in mcq_types:
            for difficulty in DIFFICULTY_LEVELS:
                for _ in range(8):
                    result = ChallengeService.generate_challenge(
                        ct,
                        difficulty=difficulty,
                        current_hour=10,
                        apply_adaptive_difficulty=False,
                    )
                    self._assert_valid_mcq(result)
                    # Distractors must not equal the correct answer
                    distractors = [
                        o for o in result["options"] if o != result["answer"]
                    ]
                    assert len(distractors) == 3
                    assert all(
                        o.strip().lower() != result["answer"].strip().lower()
                        for o in distractors
                    )

    def test_validate_mcq_rejects_duplicate_and_missing_answers(self):
        """Validator should reject ambiguous or inconsistent option sets."""
        with pytest.raises(ValueError):
            ChallengeService.validate_mcq_item(
                "Sample?", "A", ["A", "A", "B", "C"]
            )
        with pytest.raises(ValueError):
            ChallengeService.validate_mcq_item(
                "Sample?", "A", ["B", "C", "D", "E"]
            )
        with pytest.raises(ValueError):
            ChallengeService.validate_mcq_item(
                "Sample?", "A", ["A", "B", "C"]
            )


class TestDifficultyPersonalization:
    """Tests for difficulty-based challenge scaling."""

    @pytest.mark.parametrize("difficulty", DIFFICULTY_LEVELS)
    def test_math_respects_difficulty(self, difficulty):
        """Math challenges should respect the requested difficulty level."""
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, difficulty=difficulty, current_hour=10
        )
        assert result["difficulty"] == difficulty

    @pytest.mark.parametrize("difficulty,expected_limit", [
        ("beginner", 60), ("easy", 45), ("medium", 30), ("hard", 20), ("expert", 15),
    ])
    def test_time_limits_per_difficulty(self, difficulty, expected_limit):
        """Each difficulty level should have the correct time limit."""
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, difficulty=difficulty, current_hour=10
        )
        assert result["time_limit_seconds"] == expected_limit

    def test_memory_length_scales_with_difficulty(self):
        """Memory sequence length should increase with difficulty."""
        lengths = {}
        # Run multiple times to get average
        for diff in DIFFICULTY_LEVELS:
            total = 0
            for _ in range(10):
                c = ChallengeService.generate_challenge(
                    ChallengeType.MEMORY, difficulty=diff, current_hour=10
                )
                total += len(c["prompt"])
            lengths[diff] = total / 10

        # beginner average should be less than expert average
        assert lengths["beginner"] < lengths["expert"], (
            f"beginner avg {lengths['beginner']} should be < expert avg {lengths['expert']}"
        )

    def test_default_difficulty_is_medium(self):
        """Calling without difficulty should default to medium."""
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, current_hour=10
        )
        assert result["difficulty"] == "medium"

    def test_invalid_difficulty_defaults_to_medium(self):
        """Invalid difficulty string should clamp to medium."""
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, difficulty="impossible", current_hour=10
        )
        assert result["difficulty"] == "medium"


class TestTimeOfDayAdjustment:
    """Tests for _adjust_for_time() function."""

    def test_4am_reduces_by_two(self):
        """3-5 AM should reduce difficulty by 2 levels."""
        assert _adjust_for_time("hard", 4) == "easy"
        assert _adjust_for_time("expert", 3) == "medium"
        assert _adjust_for_time("medium", 5) == "beginner"

    def test_6am_reduces_by_one(self):
        """6 AM should reduce difficulty by 1 level."""
        assert _adjust_for_time("hard", 6) == "medium"
        assert _adjust_for_time("expert", 6) == "hard"

    def test_7am_plus_keeps_difficulty(self):
        """7+ AM should keep difficulty as-is."""
        assert _adjust_for_time("hard", 7) == "hard"
        assert _adjust_for_time("hard", 8) == "hard"
        assert _adjust_for_time("expert", 14) == "expert"

    def test_late_night_reduces_by_one(self):
        """0-2 AM should reduce difficulty by 1 level."""
        assert _adjust_for_time("hard", 1) == "medium"
        assert _adjust_for_time("expert", 0) == "hard"

    def test_floor_at_beginner(self):
        """Difficulty should never go below beginner."""
        assert _adjust_for_time("beginner", 4) == "beginner"
        assert _adjust_for_time("easy", 4) == "beginner"

    def test_challenge_generation_with_time(self):
        """generate_challenge should accept and apply current_hour."""
        result = ChallengeService.generate_challenge(
            ChallengeType.MATH, difficulty="hard", current_hour=4
        )
        assert result["difficulty"] == "easy"  # hard -2 = easy at 4 AM


class TestAnswerVerification:
    """Tests for ChallengeService.verify_answer()."""

    def test_correct_answer(self):
        assert ChallengeService.verify_answer("42", "42") is True

    def test_case_insensitive(self):
        assert ChallengeService.verify_answer("Piano", "piano") is True
        assert ChallengeService.verify_answer("CLOCK", "clock") is True

    def test_whitespace_trimmed(self):
        assert ChallengeService.verify_answer("42", "  42  ") is True

    def test_incorrect_answer(self):
        assert ChallengeService.verify_answer("42", "43") is False

    def test_empty_answer_returns_false(self):
        assert ChallengeService.verify_answer("42", "") is False
        assert ChallengeService.verify_answer("", "42") is False

    def test_none_answer_returns_false(self):
        assert ChallengeService.verify_answer(None, "42") is False
        assert ChallengeService.verify_answer("42", None) is False

    def test_numeric_equivalence(self):
        """Integer and float string forms of the same number should match."""
        assert ChallengeService.verify_answer("38", "38.0") is True
        assert ChallengeService.verify_answer("19", "19.00") is True
        assert ChallengeService.verify_answer("38", "39") is False

    def test_verify_against_generated_answer(self):
        """Generated answer should verify correctly."""
        challenge = ChallengeService.generate_challenge(ChallengeType.MATH)
        assert ChallengeService.verify_answer(challenge["answer"], challenge["answer"]) is True


# ═══════════════════════════════════════════════════════════════
# Integration Tests — Challenge API Endpoints
# ═══════════════════════════════════════════════════════════════

def _session_answer(db_session, user_id: int, alarm_id: int) -> str:
    """Read the server-stored challenge answer (not exposed in API response)."""
    from app.models.challenge_session import ChallengeSession

    row = (
        db_session.query(ChallengeSession)
        .filter(
            ChallengeSession.user_id == user_id,
            ChallengeSession.alarm_id == alarm_id,
        )
        .first()
    )
    assert row is not None and row.answer, "Expected an active challenge session"
    return row.answer


class TestGetChallengeEndpoint:
    """Tests for GET /api/v1/alarms/{alarm_id}/challenge."""

    def _create_alarm(self, client, auth_headers, **overrides):
        """Helper to create an alarm and return its ID."""
        data = {
            "title": "Test Alarm",
            "alarm_time": "07:00",
            "challenge_type": "math",
            "challenge_count": 1,
            **overrides,
        }
        res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
        assert res.status_code == 201
        return res.json()["id"]

    def test_get_challenge_returns_challenge(self, client, test_user, auth_headers):
        """GET /challenge should return a challenge object without the answer."""
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "type" in data
        assert "prompt" in data
        assert "answer" not in data
        assert "difficulty" in data
        assert "time_limit_seconds" in data
        assert "required_correct" in data
        assert "consecutive_correct" in data

    def test_get_challenge_returns_difficulty_field(self, client, test_user, auth_headers):
        """Challenge response should include the effective difficulty."""
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        data = res.json()
        assert data["difficulty"] in DIFFICULTY_LEVELS

    def test_get_challenge_not_found(self, client, test_user, auth_headers):
        """Non-existent alarm should return 404."""
        res = client.get("/api/v1/alarms/99999/challenge", headers=auth_headers)
        assert res.status_code == 404

    def test_get_challenge_unauthorized(self, client):
        """No auth token should return 401."""
        res = client.get("/api/v1/alarms/1/challenge")
        assert res.status_code == 401


class TestVerifyChallengeEndpoint:
    """Tests for POST /api/v1/alarms/{alarm_id}/verify."""

    def _create_alarm(self, client, auth_headers, **overrides):
        data = {
            "title": "Verify Test",
            "alarm_time": "07:00",
            "challenge_type": "math",
            "challenge_count": 1,
            **overrides,
        }
        res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
        assert res.status_code == 201
        return res.json()["id"]

    def test_verify_correct_answer_dismisses(
        self, client, test_user, auth_headers, db_session
    ):
        """Correct answer on single-step alarm should dismiss it."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is True
        assert data["status"] == "dismissed"
        assert data["wake_confirmed"] is True
        assert "wakefulness" in data

    def test_verify_message_uses_adaptive_success_streak(
        self, client, test_user, auth_headers, db_session
    ):
        """Dismiss toast must report adaptive wake streak, not challenge_count."""
        from app.models.profile import UserProfile

        alarm_id = self._create_alarm(client, auth_headers, challenge_count=1)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )

        messages = []
        for expected in (1, 2, 3):
            ch = client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            ).json()
            answer = _session_answer(db_session, test_user.id, alarm_id)
            res = client.post(
                f"/api/v1/alarms/{alarm_id}/verify",
                json={
                    "user_answer": answer,
                    "time_taken_seconds": 5,
                    "challenge_prompt": ch["prompt"],
                    "challenge_difficulty": ch["difficulty"],
                },
                headers=auth_headers,
            )
            assert res.status_code == 200
            data = res.json()
            assert data["is_dismissed"] is True
            assert data["success_streak"] == expected
            word = "alarm" if expected == 1 else "alarms"
            assert (
                data["message"]
                == (
                    f"Wake-up verified! {expected} consecutive "
                    f"{word} solved. Alarm dismissed."
                )
            )
            messages.append(data["message"])
            db_session.refresh(profile)
            assert profile.consecutive_success_streak == expected

        assert messages[0] == (
            "Wake-up verified! 1 consecutive alarm solved. "
            "Alarm dismissed."
        )
        assert "2 consecutive alarms solved" in messages[1]
        assert "3 consecutive alarms solved" in messages[2]

    def test_verify_updates_adaptive_streak_and_persists_on_threshold(
        self, client, test_user, auth_headers, db_session
    ):
        """N consecutive full wake dismissals should raise and persist difficulty."""
        from app.models.profile import DifficultyPreference, UserProfile

        alarm_id = self._create_alarm(client, auth_headers, challenge_count=1)
        client.get("/api/v1/profiles/me", headers=auth_headers)

        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM

        for i in range(_adaptive_streak_threshold()):
            ch = client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            ).json()
            answer = _session_answer(db_session, test_user.id, alarm_id)
            res = client.post(
                f"/api/v1/alarms/{alarm_id}/verify",
                json={
                    "user_answer": answer,
                    "time_taken_seconds": 5,
                    "challenge_prompt": ch["prompt"],
                    "challenge_difficulty": ch["difficulty"],
                },
                headers=auth_headers,
            )
            assert res.status_code == 200
            body = res.json()
            assert body["is_dismissed"] is True
            expected_streak = i + 1
            assert body["success_streak"] == expected_streak
            word = "alarm" if expected_streak == 1 else "alarms"
            assert (
                f"{expected_streak} consecutive {word} solved" in body["message"]
            )

        db_session.refresh(profile)
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM
        assert profile.adapted_difficulty == DifficultyPreference.HARD
        # Streak keeps climbing past the adapt threshold.
        assert profile.consecutive_success_streak == _adaptive_streak_threshold()
        assert profile.consecutive_failure_streak == 0
        assert (
            profile.last_adapted_success_streak == _adaptive_streak_threshold()
        )

        # Next success continues the display streak (6, not reset to 1).
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        cont = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert cont.status_code == 200
        cont_body = cont.json()
        assert cont_body["success_streak"] == _adaptive_streak_threshold() + 1
        assert (
            f"{_adaptive_streak_threshold() + 1} consecutive alarms solved"
            in cont_body["message"]
        )
        db_session.refresh(profile)
        assert (
            profile.consecutive_success_streak
            == _adaptive_streak_threshold() + 1
        )

        # Opposite mid-cycle wrong must NOT reset Success Streak — only a
        # final wake failure may. Wrong answers only reset in-session
        # consecutive challenge progress.
        profile.consecutive_success_streak = 3
        profile.consecutive_failure_streak = 0
        db_session.commit()

        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        bad = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "definitely_wrong_answer_xyz",
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert bad.status_code == 400
        assert bad.json().get("streak_reset") is True
        assert bad.json().get("success_streak") == 3
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 3
        assert profile.consecutive_failure_streak == 0

        # Recovering from the wrong answer and completing the wake continues
        # the Success Streak (3 → 4), it does not restart at 1.
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        recovered = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert recovered.status_code == 200
        assert recovered.json()["success_streak"] == 4
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 4
        assert profile.consecutive_failure_streak == 0

        # Explicit final wake failure resets Success Streak via fail-wake.
        # Prior verify dismissed the cycle, so open a new active session first.
        client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        fail = client.post(
            f"/api/v1/alarms/{alarm_id}/fail-wake",
            headers=auth_headers,
        )
        assert fail.status_code == 200
        fail_body = fail.json()
        assert fail_body["status"] == "failed"
        assert fail_body["success_streak"] == 0
        assert fail_body["failure_streak"] == 1
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 0
        assert profile.consecutive_failure_streak == 1

    def test_multi_step_intermediate_correct_skips_adaptive_success(
        self, client, test_user, auth_headers, db_session
    ):
        """Mid multi-step corrects must not increment adaptive success streak."""
        from app.models.profile import UserProfile

        alarm_id = self._create_alarm(client, auth_headers, challenge_count=3)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        assert profile.consecutive_success_streak == 0

        # Complete first of three steps — progress only, not a wake dismissal.
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        step = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert step.status_code == 200
        assert step.json()["status"] == "step_complete"
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 0
        assert profile.consecutive_failure_streak == 0

        # Finish remaining steps → one adaptive success for the full wake.
        for _ in range(2):
            ch = client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            ).json()
            answer = _session_answer(db_session, test_user.id, alarm_id)
            res = client.post(
                f"/api/v1/alarms/{alarm_id}/verify",
                json={
                    "user_answer": answer,
                    "time_taken_seconds": 5,
                    "challenge_prompt": ch["prompt"],
                    "challenge_difficulty": ch["difficulty"],
                },
                headers=auth_headers,
            )
            assert res.status_code == 200

        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 1
        assert profile.consecutive_failure_streak == 0

    def test_verify_incorrect_answer_returns_400(
        self, client, test_user, auth_headers, db_session
    ):
        """Incorrect answer should return 400 and reset consecutive streak."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "definitely_wrong_answer_xyz",
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert res.status_code == 400
        data = res.json()
        assert "Incorrect" in data["detail"]
        assert data.get("streak_reset") is True
        assert data["consecutive_correct"] == 0
        assert "score" in data
        assert data["score"]["total_points"] == 0
        assert data["score"]["base_points"] == 0
        assert data["score"]["time_bonus"] == 0
        assert "breakdown" in data["score"]

    def test_verify_timeout_returns_400(
        self, client, test_user, auth_headers, db_session
    ):
        """Answer submitted after time limit should return 400."""
        from datetime import datetime, timezone, timedelta
        from app.models.challenge_session import ChallengeSession

        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)

        session = (
            db_session.query(ChallengeSession)
            .filter(
                ChallengeSession.user_id == test_user.id,
                ChallengeSession.alarm_id == alarm_id,
            )
            .first()
        )
        assert session is not None
        session.issued_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        db_session.commit()

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert "Time" in res.json()["detail"]

    def test_verify_client_reported_timeout_returns_400(
        self, client, test_user, auth_headers, db_session
    ):
        """Client-reported time over the limit should return 400 Time's up."""
        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 999},
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert "Time's up" in res.json()["detail"]

    def test_verify_ignores_spoofed_expected_answer(
        self, client, test_user, auth_headers, db_session
    ):
        """Client-supplied expected_answer must not override the server session."""
        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "expected_answer": "totally_wrong_spoof",
                "user_answer": answer,
                "time_taken_seconds": 5,
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        assert res.json()["is_dismissed"] is True

    def test_verify_multi_step_returns_next_step(
        self, client, test_user, auth_headers, db_session
    ):
        """Multi-step: first correct answer should not dismiss."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=3)
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
                "challenge_step": 99,  # spoofed — server ignores
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is False
        assert data["status"] == "step_complete"
        assert data["next_step"] == 2
        assert data["consecutive_correct"] == 1

    def test_verify_ignores_client_step_spoof(
        self, client, test_user, auth_headers, db_session
    ):
        """Client cannot skip to final step by spoofing challenge_step."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=2)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_step": 2,
                "challenge_total_steps": 2,
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is False
        assert data["consecutive_correct"] == 1

    def test_verify_multi_step_final_step_dismisses(
        self, client, test_user, auth_headers, db_session
    ):
        """Two consecutive correct answers dismiss a challenge_count=2 alarm."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=2)

        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer1 = _session_answer(db_session, test_user.id, alarm_id)
        res1 = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer1, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert res1.status_code == 200
        assert res1.json()["is_dismissed"] is False

        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer2 = _session_answer(db_session, test_user.id, alarm_id)
        res2 = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer2, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert res2.status_code == 200
        data = res2.json()
        assert data["is_dismissed"] is True
        assert data["wake_confirmed"] is True

    def test_consecutive_wrong_answer_resets_streak(
        self, client, test_user, auth_headers, db_session
    ):
        """Wrong answer after a correct step resets consecutive progress."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=3)

        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        res1 = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert res1.json()["consecutive_correct"] == 1

        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        res2 = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": "wrong", "time_taken_seconds": 5},
            headers=auth_headers,
        )
        assert res2.status_code == 400
        assert res2.json()["streak_reset"] is True
        assert res2.json()["consecutive_correct"] == 0

    def test_verify_logs_correct_attempt(
        self, client, test_user, auth_headers, db_session
    ):
        """Correct answer should create a log entry with is_correct=True."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 8,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        log = db_session.query(AlarmChallengeLog).filter_by(alarm_id=alarm_id).first()
        assert log is not None
        assert log.is_correct is True
        assert log.time_taken_seconds >= 0
        assert log.challenge_prompt == ch["prompt"]
        assert log.difficulty == ch["difficulty"]

    def test_verify_logs_incorrect_attempt(
        self, client, test_user, auth_headers, db_session
    ):
        """Incorrect answer should still create a log entry with is_correct=False."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "wrong_answer",
                "time_taken_seconds": 3,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        log = db_session.query(AlarmChallengeLog).filter_by(alarm_id=alarm_id).first()
        assert log is not None
        assert log.is_correct is False

    def test_verify_not_found(self, client, test_user, auth_headers):
        """Verifying non-existent alarm should return 404."""
        res = client.post(
            "/api/v1/alarms/99999/verify",
            json={"expected_answer": "x", "user_answer": "x"},
            headers=auth_headers,
        )
        assert res.status_code == 404

    def test_dismiss_without_verification_forbidden(
        self, client, test_user, auth_headers
    ):
        """POST /dismiss must not bypass wake-up verification."""
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss", headers=auth_headers
        )
        assert res.status_code == 403
        assert "verification" in res.json()["detail"].lower()

    def test_wake_confirmations_after_dismiss(
        self, client, test_user, auth_headers, db_session
    ):
        """Successful verify should create a wake confirmation event."""
        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 4},
            headers=auth_headers,
        )
        res = client.get("/api/v1/alarms/wake-confirmations", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        assert data["events"][0]["verified"] is True
        assert data["events"][0]["wakefulness_score"] is not None

    def test_dismiss_after_snooze_exhaustion_records_method(
        self, client, test_user, auth_headers, db_session
    ):
        """When snooze limit is exhausted, wake event uses snooze_exhausted."""
        alarm_id = self._create_alarm(client, auth_headers, snooze_limit=1)
        client.post(f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 4},
            headers=auth_headers,
        )
        res = client.get("/api/v1/alarms/wake-confirmations", headers=auth_headers)
        assert res.status_code == 200
        event = res.json()["events"][0]
        assert event["dismiss_method"] == "snooze_exhausted"
        assert event["snooze_count_at_dismiss"] == 1

    def test_wakefulness_endpoint(self, client, test_user, auth_headers, db_session):
        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 4},
            headers=auth_headers,
        )
        res = client.get("/api/v1/alarms/wakefulness", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "score" in data
        assert "level" in data
        assert data["recent_wake_events"] >= 1

    def test_snooze_escalates_difficulty(
        self, client, test_user, auth_headers, db_session
    ):
        """After snooze, next challenge difficulty should escalate."""
        alarm_id = self._create_alarm(client, auth_headers, snooze_limit=3)
        client.post(f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers)
        info = client.get(
            f"/api/v1/alarms/{alarm_id}/snooze-info", headers=auth_headers
        ).json()
        assert info["escalation_level"] == 1
        assert info["snooze_count"] == 1
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        assert ch["escalation_level"] == 1


class TestChallengeHistoryEndpoint:
    """Tests for GET /api/v1/alarms/{alarm_id}/challenge/history."""

    def _create_and_verify(self, client, auth_headers, db_session, user_id):
        """Create an alarm, get challenge, verify it, return alarm_id."""
        res = client.post("/api/v1/alarms/", json={
            "title": "History Test", "alarm_time": "07:00", "challenge_type": "math",
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        answer = _session_answer(db_session, user_id, alarm_id)
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "user_answer": answer,
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        return alarm_id

    def test_history_returns_attempts(self, client, test_user, auth_headers, db_session):
        """History should return logged challenge attempts."""
        alarm_id = self._create_and_verify(
            client, auth_headers, db_session, test_user.id
        )
        res = client.get(f"/api/v1/alarms/{alarm_id}/challenge/history", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        assert len(data["history"]) >= 1
        entry = data["history"][0]
        assert "challenge_type" in entry
        assert "is_correct" in entry
        assert "time_taken_seconds" in entry
        assert "difficulty" in entry

    def test_history_not_found_for_bad_alarm(self, client, test_user, auth_headers):
        """History for non-existent alarm should return 404."""
        res = client.get("/api/v1/alarms/99999/challenge/history", headers=auth_headers)
        assert res.status_code == 404


class TestChallengeStatsEndpoint:
    """Tests for GET /api/v1/alarms/challenge/stats."""

    def test_stats_empty_returns_zeros(self, client, test_user, auth_headers):
        """Stats with no history should return zeroed stats."""
        res = client.get("/api/v1/alarms/challenge/stats", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total_attempts"] == 0
        assert data["accuracy_percentage"] == 0.0

    def test_stats_with_data(self, client, test_user, auth_headers, db_session):
        """Stats after attempts should compute accuracy and breakdown."""
        res = client.post("/api/v1/alarms/", json={
            "title": "Stats Test", "alarm_time": "07:00", "challenge_type": "math",
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "user_answer": answer,
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)

        res = client.get("/api/v1/alarms/challenge/stats", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total_attempts"] >= 1
        assert data["correct_answers"] >= 1
        assert "by_type" in data
        assert "by_difficulty" in data


class TestChallengeAnalysisEndpoint:
    """Tests for GET /api/v1/alarms/challenge/analysis."""

    def test_analysis_empty(self, client, test_user, auth_headers):
        res = client.get("/api/v1/alarms/challenge/analysis", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["total_attempts"] == 0
        assert len(data["recommendations"]) >= 1
        assert "personalization" in data

    def test_analysis_after_attempts(self, client, test_user, auth_headers, db_session):
        res = client.post("/api/v1/alarms/", json={
            "title": "Analysis Test", "alarm_time": "07:00", "challenge_type": "math",
            "challenge_count": 3,
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        for _ in range(3):
            ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
            answer = _session_answer(db_session, test_user.id, alarm_id)
            client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
                "user_answer": answer,
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            }, headers=auth_headers)

        res = client.get("/api/v1/alarms/challenge/analysis", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["summary"]["total_attempts"] >= 3
        assert "insights" in data
        assert "by_type" in data


class TestUserChallengeHistoryEndpoint:
    """Tests for GET /api/v1/alarms/challenge/history."""

    def test_user_history(self, client, test_user, auth_headers, db_session):
        res = client.post("/api/v1/alarms/", json={
            "title": "Hist", "alarm_time": "07:00", "challenge_type": "quiz",
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "user_answer": answer,
            "time_taken_seconds": 4,
        }, headers=auth_headers)

        res = client.get("/api/v1/alarms/challenge/history", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1
        assert len(data["history"]) >= 1
        # Resolved type should be logged (quiz), not blank
        assert data["history"][0]["challenge_type"] in {
            "quiz", "math", "logic", "memory", "word_game", "pattern", "riddle"
        }


class TestSnoozeInfoEndpoint:
    """Tests for GET /api/v1/alarms/{alarm_id}/snooze-info."""

    def test_snooze_info_returns_status(self, client, test_user, auth_headers):
        """Snooze info should return count, limit, and can_snooze flag."""
        res = client.post("/api/v1/alarms/", json={
            "title": "Snooze Test", "alarm_time": "07:00", "snooze_limit": 3,
        }, headers=auth_headers)
        alarm_id = res.json()["id"]

        res = client.get(f"/api/v1/alarms/{alarm_id}/snooze-info", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["snooze_count"] == 0
        assert data["snooze_limit"] == 3
        assert data["can_snooze"] is True
        assert data["anti_snooze_enforced"] is False
        assert "escalation_level" in data
        assert "next_challenge_difficulty" in data

    def test_snooze_info_after_snoozing(self, client, test_user, auth_headers):
        """After snoozing, snooze_count should increment."""
        res = client.post("/api/v1/alarms/", json={
            "title": "Snooze Twice", "alarm_time": "07:00", "snooze_limit": 2,
        }, headers=auth_headers)
        alarm_id = res.json()["id"]

        # Snooze once
        client.post(f"/api/v1/alarms/{alarm_id}/snooze", json={}, headers=auth_headers)

        res = client.get(f"/api/v1/alarms/{alarm_id}/snooze-info", headers=auth_headers)
        data = res.json()
        assert data["snooze_count"] == 1
        assert data["can_snooze"] is True

    def test_snooze_info_limit_reached(self, client, test_user, auth_headers):
        """After max snoozes, can_snooze should be False."""
        res = client.post("/api/v1/alarms/", json={
            "title": "Max Snooze", "alarm_time": "07:00", "snooze_limit": 1,
        }, headers=auth_headers)
        alarm_id = res.json()["id"]

        client.post(f"/api/v1/alarms/{alarm_id}/snooze", json={}, headers=auth_headers)

        res = client.get(f"/api/v1/alarms/{alarm_id}/snooze-info", headers=auth_headers)
        data = res.json()
        assert data["can_snooze"] is False
        assert data["anti_snooze_enforced"] is True

    def test_snooze_info_not_found(self, client, test_user, auth_headers):
        res = client.get("/api/v1/alarms/99999/snooze-info", headers=auth_headers)
        assert res.status_code == 404


class TestFailWakeEndpoint:
    """Tests for POST /api/v1/alarms/{alarm_id}/fail-wake."""

    def _create_alarm(self, client, auth_headers, **overrides):
        data = {
            "title": "Fail Wake Test",
            "alarm_time": "07:00",
            "challenge_type": "math",
            "challenge_count": 1,
            **overrides,
        }
        res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
        assert res.status_code == 201
        return res.json()["id"]

    def test_fail_wake_requires_active_session(
        self, client, test_user, auth_headers
    ):
        """Without an open challenge session, fail-wake is rejected."""
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/fail-wake", headers=auth_headers
        )
        assert res.status_code == 400

    def test_fail_wake_increments_failure_streak(
        self, client, test_user, auth_headers, db_session
    ):
        """Abandoning an active cycle +1 failure streak and clears success."""
        from app.models.profile import UserProfile
        from app.models.alarm_wake_event import AlarmWakeEvent

        alarm_id = self._create_alarm(client, auth_headers)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        profile.consecutive_success_streak = 3
        profile.consecutive_failure_streak = 0
        db_session.commit()

        client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/fail-wake", headers=auth_headers
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "failed"
        assert body["success_streak"] == 0
        assert body["failure_streak"] == 1
        assert body["dismiss_method"] == "abandoned"

        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 0
        assert profile.consecutive_failure_streak == 1

        event = (
            db_session.query(AlarmWakeEvent)
            .filter(
                AlarmWakeEvent.user_id == test_user.id,
                AlarmWakeEvent.alarm_id == alarm_id,
            )
            .order_by(AlarmWakeEvent.id.desc())
            .first()
        )
        assert event is not None
        assert event.verified is False
        assert event.dismiss_method == "abandoned"

        # Second call without a new session must not double-count.
        again = client.post(
            f"/api/v1/alarms/{alarm_id}/fail-wake", headers=auth_headers
        )
        assert again.status_code == 400
        db_session.refresh(profile)
        assert profile.consecutive_failure_streak == 1

    def test_wrong_answer_does_not_increment_failure_streak(
        self, client, test_user, auth_headers, db_session
    ):
        """Mid-cycle wrong answers must not touch Failure Streak."""
        from app.models.profile import UserProfile

        alarm_id = self._create_alarm(client, auth_headers)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        profile.consecutive_success_streak = 2
        profile.consecutive_failure_streak = 0
        db_session.commit()

        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        bad = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "definitely_wrong_answer_xyz",
                "time_taken_seconds": 5,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
            },
            headers=auth_headers,
        )
        assert bad.status_code == 400
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 2
        assert profile.consecutive_failure_streak == 0

    def test_snooze_does_not_increment_failure_streak(
        self, client, test_user, auth_headers, db_session
    ):
        """Snooze continues the cycle and must not count as final failure."""
        from app.models.profile import UserProfile

        alarm_id = self._create_alarm(client, auth_headers, snooze_limit=3)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        profile.consecutive_success_streak = 1
        profile.consecutive_failure_streak = 0
        db_session.commit()

        client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        snooze = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert snooze.status_code == 200
        db_session.refresh(profile)
        assert profile.consecutive_success_streak == 1
        assert profile.consecutive_failure_streak == 0

    def test_fail_wake_lowers_difficulty_at_threshold(
        self, client, test_user, auth_headers, db_session
    ):
        """N consecutive final failures should lower adapted difficulty."""
        from app.models.profile import UserProfile, DifficultyPreference

        alarm_id = self._create_alarm(client, auth_headers)
        client.get("/api/v1/profiles/me", headers=auth_headers)
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == test_user.id)
            .one()
        )
        profile.difficulty_preference = DifficultyPreference.MEDIUM
        profile.adapted_difficulty = DifficultyPreference.MEDIUM
        profile.consecutive_success_streak = 0
        profile.consecutive_failure_streak = 0
        profile.last_adapted_failure_streak = 0
        db_session.commit()

        threshold = _adaptive_streak_threshold()
        for n in range(1, threshold + 1):
            client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            )
            res = client.post(
                f"/api/v1/alarms/{alarm_id}/fail-wake", headers=auth_headers
            )
            assert res.status_code == 200
            assert res.json()["failure_streak"] == n
            db_session.refresh(profile)
            assert profile.consecutive_failure_streak == n

        assert profile.adapted_difficulty == DifficultyPreference.EASY
        assert profile.difficulty_preference == DifficultyPreference.MEDIUM
        assert profile.last_adapted_failure_streak == threshold

        # Personalization analysis surfaces the updated Failure Streak.
        analysis = client.get(
            "/api/v1/alarms/challenge/analysis", headers=auth_headers
        )
        assert analysis.status_code == 200
        adaptive = analysis.json()["personalization"]["adaptive_difficulty"]
        assert adaptive["failure_streak"] == threshold
        assert adaptive["success_streak"] == 0
