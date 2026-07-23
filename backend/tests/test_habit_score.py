"""Unit, regression, and performance tests for Habit Score SSOT."""

import time
from datetime import datetime, timedelta, timezone

from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.services.habit_score import (
    HABIT_SCORE_WEIGHTS,
    calculate_habit_score,
    calculate_habit_score_for_user,
    calculate_habit_score_with_events,
    derive_habit_score_inputs_from_events,
    load_puzzle_attempt_stats,
    merge_puzzle_stats,
    resolve_habit_score_inputs,
)
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


def test_puzzle_accuracy_preferred_over_dismiss_share():
    """challenge_completion uses correct/attempts when puzzle stats exist."""
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 80.0,
            "total_alarms_dismissed": 8,
            "total_snoozes": 2,
            "streak_days": 15,
            "total_puzzle_correct": 3,
            "total_puzzle_attempts": 5,
        }
    )
    # Puzzle accuracy 60%, not dismiss share 80%
    assert result["breakdown"]["challenge_completion"] == 60.0
    # Snooze reduction still from dismiss/snooze share
    assert result["breakdown"]["snooze_reduction"] == 80.0
    # 80*0.35 + 60*0.25 + 80*0.20 + 50*0.20 = 69.0
    assert result["habit_score"] == 69.0


def test_zero_puzzle_attempts_keeps_legacy_dismiss_share():
    """No puzzle attempts → challenge_completion stays dismiss/(dismiss+snooze)."""
    result = calculate_habit_score(
        {
            "wake_up_consistency_score": 80.0,
            "total_alarms_dismissed": 8,
            "total_snoozes": 2,
            "streak_days": 15,
            "total_puzzle_correct": 0,
            "total_puzzle_attempts": 0,
        }
    )
    assert result["breakdown"]["challenge_completion"] == 80.0
    assert result["habit_score"] == 74.0


# ── Behavioral event derivation (unit) ──────────────────────────────────


def test_derive_inputs_replays_clean_wakes():
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert inputs["wake_up_consistency_score"] == 15.0
    assert inputs["total_alarms_dismissed"] == 3
    assert inputs["total_snoozes"] == 0
    # Undated fixtures map each verified wake to a synthetic consecutive day.
    assert inputs["streak_days"] == 3
    assert inputs["best_streak"] == 3
    assert inputs["last_successful_wake_date"] is not None


def test_derive_inputs_snooze_exhausted_keeps_calendar_streak():
    """Snooze quality affects consistency, not Day Streak (verified success)."""
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 3,
            "dismiss_method": "snooze_exhausted",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert inputs["total_alarms_dismissed"] == 4
    assert inputs["total_snoozes"] == 3
    # +5 +5 −10 +5 = 5
    assert inputs["wake_up_consistency_score"] == 5.0
    # Four verified successes on synthetic consecutive days → streak 4
    assert inputs["streak_days"] == 4


def test_derive_inputs_mid_cycle_snooze_keeps_calendar_streak():
    """Mid-cycle snoozes penalize consistency but still count as a success day."""
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 2,
            "dismiss_method": "challenge",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert inputs["total_alarms_dismissed"] == 2
    assert inputs["total_snoozes"] == 2
    # +5 then −5 mid-cycle penalty
    assert inputs["wake_up_consistency_score"] == 0.0
    assert inputs["streak_days"] == 2


def test_derive_same_calendar_day_counts_once():
    """Multiple verified wakes on the same local day increment streak only once."""
    from datetime import datetime, timezone

    day = datetime(2026, 7, 20, 7, 0, tzinfo=timezone.utc)
    same_day_later = datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc)
    next_day = datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc)
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "dismissed_at": day,
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 1,
            "dismiss_method": "challenge",
            "dismissed_at": same_day_later,
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "dismissed_at": next_day,
        },
    ]
    inputs = derive_habit_score_inputs_from_events(
        events, timezone_name="UTC", as_of=next_day.date()
    )
    assert inputs["total_alarms_dismissed"] == 3
    assert inputs["streak_days"] == 2
    assert inputs["last_successful_wake_date"] == next_day.date()


def test_derive_missed_day_resets_streak():
    """A gap between success dates resets Day Streak; next success starts at 1."""
    from datetime import datetime, timezone

    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "dismissed_at": datetime(2026, 7, 18, 7, 0, tzinfo=timezone.utc),
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "dismissed_at": datetime(2026, 7, 19, 7, 0, tzinfo=timezone.utc),
        },
        # gap on 2026-07-20
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "dismissed_at": datetime(2026, 7, 21, 7, 0, tzinfo=timezone.utc),
        },
    ]
    inputs = derive_habit_score_inputs_from_events(
        events,
        timezone_name="UTC",
        as_of=datetime(2026, 7, 21).date(),
    )
    assert inputs["streak_days"] == 1
    assert inputs["best_streak"] == 2
    assert inputs["last_successful_wake_date"] == datetime(2026, 7, 21).date()


def test_derive_ignores_unverified_events():
    events = [
        {
            "verified": False,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert inputs["total_alarms_dismissed"] == 1
    assert inputs["streak_days"] == 1

def test_derive_inputs_includes_puzzle_stats_from_wake_snapshots():
    """Wake-event challenge snapshots feed puzzle completion when present."""
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "challenges_completed": 3,
            "failed_attempts": 1,
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
            "challenges_completed": 2,
            "failed_attempts": 2,
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert inputs["total_puzzle_correct"] == 5
    assert inputs["total_puzzle_attempts"] == 8
    result = calculate_habit_score(inputs)
    assert result["breakdown"]["challenge_completion"] == 62.5


def test_derive_omits_puzzle_fields_when_wake_snapshots_empty():
    """Legacy wake rows with zero challenge fields keep dismiss fallback."""
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 1,
            "dismiss_method": "challenge",
            "challenges_completed": 0,
            "failed_attempts": 0,
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert "total_puzzle_correct" not in inputs
    assert "total_puzzle_attempts" not in inputs
    result = calculate_habit_score(inputs)
    # 1 dismiss + 1 snooze → 50%
    assert result["breakdown"]["challenge_completion"] == 50.0


def test_score_from_events_uses_same_weighted_formula():
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 1,
            "dismiss_method": "challenge",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    assert calculate_habit_score_with_events(None, events) == calculate_habit_score(
        inputs
    )


def test_resolve_falls_back_to_profile_when_no_verified_events():
    profile = {
        "wake_up_consistency_score": 80.0,
        "total_alarms_dismissed": 8,
        "total_snoozes": 2,
        "streak_days": 15,
    }
    resolved = resolve_habit_score_inputs(
        profile,
        [
            {
                "verified": False,
                "snooze_count_at_dismiss": 0,
                "dismiss_method": "challenge",
            }
        ],
    )
    assert resolved is profile
    assert calculate_habit_score_with_events(profile, []) == calculate_habit_score(
        profile
    )


# ── Regression: API shape + stale counter correction ────────────────────


def _seed_alarm(db_session, user_id: int) -> Alarm:
    from datetime import time as time_cls

    alarm = Alarm(
        user_id=user_id,
        title="Habit Score Alarm",
        alarm_time=time_cls(7, 0),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        challenge_count=1,
        challenge_difficulty="medium",
        snooze_limit=3,
    )
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)
    return alarm


def test_for_user_prefers_events_over_stale_profile_counters(
    db_session, test_user
):
    """Event counters refresh consistency/dismiss/snooze; Day Streak stays stored."""
    profile = UserProfile(
        user_id=test_user.id,
        wake_up_consistency_score=99.0,
        total_alarms_dismissed=99,
        total_snoozes=0,
        streak_days=30,
    )
    db_session.add(profile)
    alarm = _seed_alarm(db_session, test_user.id)
    now = datetime.now(timezone.utc)
    for i in range(4):
        dismissed = now - timedelta(days=i + 1)
        db_session.add(
            AlarmWakeEvent(
                user_id=test_user.id,
                alarm_id=alarm.id,
                triggered_at=dismissed - timedelta(minutes=5),
                dismissed_at=dismissed,
                dismiss_method="challenge",
                snooze_count_at_dismiss=0,
                verified=True,
            )
        )
    db_session.commit()

    stale = calculate_habit_score(profile)
    live = calculate_habit_score_for_user(db_session, test_user.id, profile)
    # Events refresh consistency/dismiss/snooze; stored Day Streak (30) is SSOT.
    expected = calculate_habit_score(
        {
            "wake_up_consistency_score": 20.0,
            "total_alarms_dismissed": 4,
            "total_snoozes": 0,
            "streak_days": 30,
        }
    )
    assert live == expected
    assert live["habit_score"] != stale["habit_score"]
    assert set(live.keys()) == {
        "habit_score",
        "breakdown",
        "weights",
        "success_streak",
        "failure_streak",
        "streak_days",
    }
    assert set(live["breakdown"].keys()) == {
        "wake_up_consistency",
        "challenge_completion",
        "snooze_reduction",
        "sleep_adherence",
    }


def test_habit_score_api_reflects_behavioral_events(
    client, auth_headers, db_session, test_user
):
    """GET /profiles/me/habit-score recalculates from wake events."""
    profile = (
        db_session.query(UserProfile)
        .filter(UserProfile.user_id == test_user.id)
        .first()
    )
    if profile is None:
        profile = UserProfile(user_id=test_user.id)
        db_session.add(profile)
    profile.wake_up_consistency_score = 0.0
    profile.total_alarms_dismissed = 0
    profile.total_snoozes = 0
    profile.streak_days = 0
    alarm = _seed_alarm(db_session, test_user.id)
    now = datetime.now(timezone.utc)
    db_session.add(
        AlarmWakeEvent(
            user_id=test_user.id,
            alarm_id=alarm.id,
            triggered_at=now - timedelta(minutes=10),
            dismissed_at=now - timedelta(minutes=5),
            dismiss_method="challenge",
            snooze_count_at_dismiss=0,
            verified=True,
        )
    )
    db_session.add(
        AlarmWakeEvent(
            user_id=test_user.id,
            alarm_id=alarm.id,
            triggered_at=now - timedelta(days=1, minutes=10),
            dismissed_at=now - timedelta(days=1, minutes=5),
            dismiss_method="snooze_exhausted",
            snooze_count_at_dismiss=3,
            verified=True,
        )
    )
    db_session.commit()

    expected = calculate_habit_score_for_user(db_session, test_user.id, profile)
    res = client.get("/api/v1/profiles/me/habit-score", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["habit_score"] == expected["habit_score"]
    assert body["breakdown"] == expected["breakdown"]
    assert body["weights"] == HABIT_SCORE_WEIGHTS

    stats = client.get("/api/v1/users/profile/stats", headers=auth_headers)
    assert stats.status_code == 200
    assert stats.json()["current_habit_score"] == expected["habit_score"]
    # Event-derived: 2 dismissals + 3 snoozes → 40% (not stale profile 0%)
    assert stats.json()["wakeup_success_rate"] == 40.0

    profile_res = client.get("/api/v1/profiles/me", headers=auth_headers)
    assert profile_res.status_code == 200
    assert profile_res.json()["habit_score"] == expected["habit_score"]


def test_synced_counters_and_events_agree(db_session, test_user):
    """When counters match the event replay, both paths yield the same score."""
    events = [
        {
            "verified": True,
            "snooze_count_at_dismiss": 0,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 2,
            "dismiss_method": "challenge",
        },
        {
            "verified": True,
            "snooze_count_at_dismiss": 3,
            "dismiss_method": "snooze_exhausted",
        },
    ]
    inputs = derive_habit_score_inputs_from_events(events)
    profile = UserProfile(user_id=test_user.id, **inputs)
    db_session.add(profile)
    alarm = _seed_alarm(db_session, test_user.id)
    now = datetime.now(timezone.utc)
    for i, ev in enumerate(events):
        dismissed = now - timedelta(days=len(events) - i)
        db_session.add(
            AlarmWakeEvent(
                user_id=test_user.id,
                alarm_id=alarm.id,
                triggered_at=dismissed - timedelta(minutes=5),
                dismissed_at=dismissed,
                dismiss_method=ev["dismiss_method"],
                snooze_count_at_dismiss=ev["snooze_count_at_dismiss"],
                verified=True,
            )
        )
    db_session.commit()

    from_profile = calculate_habit_score(profile)
    from_events = calculate_habit_score_for_user(db_session, test_user.id, profile)
    assert from_events == from_profile


def test_no_events_keeps_legacy_counter_score(db_session, test_user):
    """Backward compatible: no wake events → use stored counters."""
    profile = UserProfile(
        user_id=test_user.id,
        wake_up_consistency_score=80.0,
        total_alarms_dismissed=8,
        total_snoozes=2,
        streak_days=15,
    )
    db_session.add(profile)
    db_session.commit()
    assert calculate_habit_score_for_user(
        db_session, test_user.id, profile
    ) == calculate_habit_score(profile)


def test_for_user_uses_challenge_log_accuracy(db_session, test_user):
    """Challenge logs drive challenge_completion over dismiss/snooze share."""
    profile = UserProfile(
        user_id=test_user.id,
        wake_up_consistency_score=80.0,
        total_alarms_dismissed=8,
        total_snoozes=2,
        streak_days=15,
    )
    db_session.add(profile)
    alarm = _seed_alarm(db_session, test_user.id)
    # 3 correct / 5 attempts = 60% (dismiss share would be 80%)
    for i, correct in enumerate([True, True, True, False, False]):
        db_session.add(
            AlarmChallengeLog(
                alarm_id=alarm.id,
                user_id=test_user.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt=f"q{i}",
                is_correct=correct,
                time_taken_seconds=5,
                failed_attempts=0,
                points_earned=10 if correct else 0,
            )
        )
    db_session.commit()

    stats = load_puzzle_attempt_stats(db_session, test_user.id)
    assert stats == {"total_puzzle_correct": 3, "total_puzzle_attempts": 5}

    live = calculate_habit_score_for_user(db_session, test_user.id, profile)
    expected = calculate_habit_score(
        merge_puzzle_stats(
            {
                "wake_up_consistency_score": 80.0,
                "total_alarms_dismissed": 8,
                "total_snoozes": 2,
                "streak_days": 15,
            },
            stats,
        )
    )
    assert live == expected
    assert live["breakdown"]["challenge_completion"] == 60.0
    assert set(live.keys()) == {
        "habit_score",
        "breakdown",
        "weights",
        "success_streak",
        "failure_streak",
        "streak_days",
    }


def test_challenge_logs_override_wake_event_puzzle_snapshots(
    db_session, test_user
):
    """Attempt logs are preferred over wake-event challenge snapshots."""
    profile = UserProfile(user_id=test_user.id)
    db_session.add(profile)
    alarm = _seed_alarm(db_session, test_user.id)
    now = datetime.now(timezone.utc)
    db_session.add(
        AlarmWakeEvent(
            user_id=test_user.id,
            alarm_id=alarm.id,
            triggered_at=now - timedelta(minutes=10),
            dismissed_at=now - timedelta(minutes=5),
            dismiss_method="challenge",
            challenges_required=3,
            challenges_completed=3,
            failed_attempts=0,
            snooze_count_at_dismiss=0,
            verified=True,
        )
    )
    # Logs: 2/4 = 50%, wake snapshot alone would be 3/3 = 100%
    for i, correct in enumerate([True, True, False, False]):
        db_session.add(
            AlarmChallengeLog(
                alarm_id=alarm.id,
                user_id=test_user.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt=f"q{i}",
                is_correct=correct,
                time_taken_seconds=4,
                failed_attempts=0,
                points_earned=10 if correct else 0,
            )
        )
    db_session.commit()

    live = calculate_habit_score_for_user(db_session, test_user.id, profile)
    assert live["breakdown"]["challenge_completion"] == 50.0

    # In-memory path without logs still uses wake snapshots
    wake_only = calculate_habit_score_with_events(
        None,
        [
            {
                "verified": True,
                "snooze_count_at_dismiss": 0,
                "dismiss_method": "challenge",
                "challenges_completed": 3,
                "failed_attempts": 0,
            }
        ],
    )
    assert wake_only["breakdown"]["challenge_completion"] == 100.0


# ── Performance check ───────────────────────────────────────────────────


def test_habit_score_recalculation_performance(db_session, test_user):
    """Recalculating from a large wake history stays within a tight budget."""
    profile = UserProfile(user_id=test_user.id)
    db_session.add(profile)
    alarm = _seed_alarm(db_session, test_user.id)
    now = datetime.now(timezone.utc)
    n = 500
    for i in range(n):
        dismissed = now - timedelta(hours=i + 1)
        exhausted = i % 7 == 0
        snoozes = 3 if exhausted else (1 if i % 3 == 0 else 0)
        db_session.add(
            AlarmWakeEvent(
                user_id=test_user.id,
                alarm_id=alarm.id,
                triggered_at=dismissed - timedelta(minutes=5),
                dismissed_at=dismissed,
                dismiss_method=(
                    "snooze_exhausted" if exhausted else "challenge"
                ),
                snooze_count_at_dismiss=snoozes,
                verified=True,
            )
        )
    db_session.commit()

    # Warm-up
    calculate_habit_score_for_user(db_session, test_user.id, profile)

    started = time.perf_counter()
    for _ in range(20):
        result = calculate_habit_score_for_user(db_session, test_user.id, profile)
    elapsed = time.perf_counter() - started

    assert result["habit_score"] >= 0.0
    assert result["habit_score"] <= 100.0
    # 20 recalculations over 500 events should finish well under 2s locally
    assert elapsed < 2.0, f"habit score recalc too slow: {elapsed:.3f}s for 20 runs"
