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
from app.services.challenge_service import ChallengeService, _adjust_for_time, DIFFICULTY_LEVELS
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
        assert result["answer"].isdigit() or result["answer"].lstrip("-").isdigit()

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

    def test_generate_random_resolves_to_real_type(self):
        """RANDOM type should resolve to an actual challenge type."""
        result = ChallengeService.generate_challenge(ChallengeType.RANDOM)
        assert result["type"] in ["MATH", "PATTERN", "MEMORY", "RIDDLE"]

    def test_all_types_return_difficulty_and_time_limit(self):
        """Every challenge type should include difficulty and time_limit_seconds."""
        for ct in ChallengeType:
            result = ChallengeService.generate_challenge(ct, difficulty="medium")
            assert "difficulty" in result, f"{ct.value} missing difficulty"
            assert "time_limit_seconds" in result, f"{ct.value} missing time_limit"


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
        """GET /challenge should return a challenge object."""
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "type" in data
        assert "prompt" in data
        assert "answer" in data
        assert "difficulty" in data
        assert "time_limit_seconds" in data

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

    def test_verify_correct_answer_dismisses(self, client, test_user, auth_headers):
        """Correct answer on single-step alarm should dismiss it."""
        alarm_id = self._create_alarm(client, auth_headers)
        # Get a challenge
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        # Verify with the correct answer
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
            "challenge_step": 1,
            "challenge_total_steps": 1,
        }, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is True
        assert data["status"] == "dismissed"

    def test_verify_incorrect_answer_returns_400(self, client, test_user, auth_headers):
        """Incorrect answer should return 400 with score.total_points == 0."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": "definitely_wrong_answer_xyz",
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        assert res.status_code == 400
        data = res.json()
        assert "Incorrect" in data["detail"]
        assert "score" in data
        assert data["score"]["total_points"] == 0
        assert data["score"]["base_points"] == 0
        assert data["score"]["time_bonus"] == 0
        assert "breakdown" in data["score"]

    def test_verify_timeout_returns_400(self, client, test_user, auth_headers, db_session):
        """Answer submitted after time limit should return 400."""
        from datetime import datetime, timezone, timedelta
        from app.models.challenge_session import ChallengeSession

        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()

        # Backdate the server session so the challenge appears expired
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

        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        assert res.status_code == 400
        assert "Time" in res.json()["detail"]

    def test_verify_client_reported_timeout_returns_400(self, client, test_user, auth_headers):
        """Client-reported time over the limit should return 400 Time's up."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "user_answer": ch["answer"],
            "time_taken_seconds": 999,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        assert res.status_code == 400
        assert "Time's up" in res.json()["detail"]

    def test_verify_ignores_spoofed_expected_answer(self, client, test_user, auth_headers):
        """Client-supplied expected_answer must not override the server session."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": "totally_wrong_spoof",
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
            "challenge_step": 1,
            "challenge_total_steps": 1,
        }, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["is_dismissed"] is True

    def test_verify_multi_step_returns_next_step(self, client, test_user, auth_headers):
        """Multi-step alarm: correct answer on step 1/3 should not dismiss."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=3)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
            "challenge_step": 1,
            "challenge_total_steps": 3,
        }, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is False
        assert data["status"] == "step_complete"
        assert data["next_step"] == 2

    def test_verify_multi_step_final_step_dismisses(self, client, test_user, auth_headers):
        """Multi-step alarm: correct answer on final step should dismiss."""
        alarm_id = self._create_alarm(client, auth_headers, challenge_count=2)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        # Step 2 of 2 (last step)
        res = client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
            "challenge_step": 2,
            "challenge_total_steps": 2,
        }, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["is_dismissed"] is True

    def test_verify_logs_correct_attempt(self, client, test_user, auth_headers, db_session):
        """Correct answer should create a log entry with is_correct=True."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
            "time_taken_seconds": 8,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        log = db_session.query(AlarmChallengeLog).filter_by(alarm_id=alarm_id).first()
        assert log is not None
        assert log.is_correct is True
        assert log.time_taken_seconds >= 0
        assert log.challenge_prompt == ch["prompt"]
        assert log.difficulty == ch["difficulty"]

    def test_verify_logs_incorrect_attempt(self, client, test_user, auth_headers, db_session):
        """Incorrect answer should still create a log entry with is_correct=False."""
        alarm_id = self._create_alarm(client, auth_headers)
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": "wrong_answer",
            "time_taken_seconds": 3,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        log = db_session.query(AlarmChallengeLog).filter_by(alarm_id=alarm_id).first()
        assert log is not None
        assert log.is_correct is False

    def test_verify_not_found(self, client, test_user, auth_headers):
        """Verifying non-existent alarm should return 404."""
        res = client.post("/api/v1/alarms/99999/verify", json={
            "expected_answer": "x",
            "user_answer": "x",
        }, headers=auth_headers)
        assert res.status_code == 404


class TestChallengeHistoryEndpoint:
    """Tests for GET /api/v1/alarms/{alarm_id}/challenge/history."""

    def _create_and_verify(self, client, auth_headers):
        """Create an alarm, get challenge, verify it, return alarm_id."""
        res = client.post("/api/v1/alarms/", json={
            "title": "History Test", "alarm_time": "07:00", "challenge_type": "math",
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
            "time_taken_seconds": 5,
            "challenge_prompt": ch["prompt"],
            "challenge_difficulty": ch["difficulty"],
        }, headers=auth_headers)
        return alarm_id

    def test_history_returns_attempts(self, client, test_user, auth_headers):
        """History should return logged challenge attempts."""
        alarm_id = self._create_and_verify(client, auth_headers)
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

    def test_stats_with_data(self, client, test_user, auth_headers):
        """Stats after attempts should compute accuracy and breakdown."""
        # Create alarm & do a correct verification
        res = client.post("/api/v1/alarms/", json={
            "title": "Stats Test", "alarm_time": "07:00", "challenge_type": "math",
        }, headers=auth_headers)
        alarm_id = res.json()["id"]
        ch = client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers).json()
        client.post(f"/api/v1/alarms/{alarm_id}/verify", json={
            "expected_answer": ch["answer"],
            "user_answer": ch["answer"],
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

    def test_snooze_info_not_found(self, client, test_user, auth_headers):
        res = client.get("/api/v1/alarms/99999/snooze-info", headers=auth_headers)
        assert res.status_code == 404
