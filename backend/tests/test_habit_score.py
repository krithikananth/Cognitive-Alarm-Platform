"""Unit tests for the Habit Score single source of truth."""

from app.services.habit_score import HABIT_SCORE_WEIGHTS, calculate_habit_score
from app.services.profile_service import ProfileService


def test_weights_match_specification():
    assert HABIT_SCORE_WEIGHTS == {
        "wake_up_consistency": 0.35,
        "challenge_completion": 0.25,
        "snooze_reduction": 0.20,
        "sleep_adherence": 0.20,
    }
    assert abs(sum(HABIT_SCORE_WEIGHTS.values()) - 1.0) < 1e-9


def test_neutral_defaults_with_no_history():
    """No dismiss/snooze history → challenge & snooze components are 50."""
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 0.0,
            "total_alarms_dismissed": 0,
            "total_snoozes": 0,
            "streak_days": 0,
        }
    )
    assert result["breakdown"]["wake_up_consistency"] == 0.0
    assert result["breakdown"]["challenge_completion"] == 50.0
    assert result["breakdown"]["snooze_reduction"] == 50.0
    assert result["breakdown"]["sleep_adherence"] == 0.0
    # 0*0.35 + 50*0.25 + 50*0.20 + 0*0.20 = 22.5
    assert result["habit_score"] == 22.5
    assert result["weights"] == HABIT_SCORE_WEIGHTS


def test_known_weighted_total():
    """Hand-checked weighted total for a known profile snapshot."""
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 80.0,
            "total_alarms_dismissed": 8,
            "total_snoozes": 2,
            "streak_days": 15,
        }
    )
    # challenge = 8/10*100 = 80
    # snooze reduction = (1 - 0.2)*100 = 80
    # adherence = 15/30*100 = 50
    # overall = 80*0.35 + 80*0.25 + 80*0.20 + 50*0.20 = 74.0
    assert result["breakdown"] == {
        "wake_up_consistency": 80.0,
        "challenge_completion": 80.0,
        "snooze_reduction": 80.0,
        "sleep_adherence": 50.0,
    }
    assert result["habit_score"] == 74.0


def test_profile_service_delegates_to_ssot():
    """ProfileService must not use a divergent formula."""
    payload = {
        "wake_up_consistency_score": 60.0,
        "total_alarms_dismissed": 3,
        "total_snoozes": 1,
        "streak_days": 6,
    }
    assert ProfileService.calculate_habit_score(payload) == calculate_habit_score(
        payload
    )


def test_consistency_capped_at_100():
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 150.0,
            "total_alarms_dismissed": 1,
            "total_snoozes": 0,
            "streak_days": 30,
        }
    )
    assert result["breakdown"]["wake_up_consistency"] == 100.0
    assert result["breakdown"]["sleep_adherence"] == 100.0
    assert result["habit_score"] <= 100.0


def test_only_snoozes_zeroes_challenge_and_snooze_components():
    """Dismissed=0, snoozes>0 → challenge & snooze reduction both 0."""
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 50.0,
            "total_alarms_dismissed": 0,
            "total_snoozes": 10,
            "streak_days": 0,
        }
    )
    assert result["breakdown"]["challenge_completion"] == 0.0
    assert result["breakdown"]["snooze_reduction"] == 0.0
    # 50*0.35 + 0 + 0 + 0 = 17.5
    assert result["habit_score"] == 17.5


def test_streak_above_target_caps_adherence():
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 100.0,
            "total_alarms_dismissed": 5,
            "total_snoozes": 0,
            "streak_days": 60,
        }
    )
    assert result["breakdown"]["sleep_adherence"] == 100.0
    assert result["habit_score"] == 100.0


def test_equal_dismiss_and_snooze_midpoint():
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 70.0,
            "total_alarms_dismissed": 5,
            "total_snoozes": 5,
            "streak_days": 9,
        }
    )
    assert result["breakdown"] == {
        "wake_up_consistency": 70.0,
        "challenge_completion": 50.0,
        "snooze_reduction": 50.0,
        "sleep_adherence": 30.0,
    }
    # 70*0.35 + 50*0.25 + 50*0.20 + 30*0.20 = 53.0
    assert result["habit_score"] == 53.0


def test_fractional_rounding_to_two_decimals():
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 33.33,
            "total_alarms_dismissed": 1,
            "total_snoozes": 2,
            "streak_days": 1,
        }
    )
    assert result["breakdown"]["wake_up_consistency"] == 33.33
    assert result["breakdown"]["challenge_completion"] == 33.33
    assert result["breakdown"]["snooze_reduction"] == 33.33
    assert result["breakdown"]["sleep_adherence"] == 3.33
    assert result["habit_score"] == 27.33
