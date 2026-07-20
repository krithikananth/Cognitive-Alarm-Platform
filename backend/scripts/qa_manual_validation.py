"""Manual expected-vs-actual validation for Habit Score and analytics helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from app.services.behavioral_analytics_service import (
    ON_TIME_TOLERANCE_MINUTES,
    BehavioralAnalyticsService,
)
from app.services.habit_score import calculate_habit_score


def manual_habit_score(payload: dict) -> float:
    wu = min(float(payload["wake_up_consistency_score"]), 100.0)
    d = int(payload["total_alarms_dismissed"])
    s = int(payload["total_snoozes"])
    te = d + s
    if te > 0:
        ch = (d / te) * 100.0
        sn = max(0.0, (1.0 - s / te) * 100.0)
    else:
        ch = sn = 50.0
    ad = min((int(payload["streak_days"]) / 30.0) * 100.0, 100.0)
    return round(min(wu * 0.35 + ch * 0.25 + sn * 0.20 + ad * 0.20, 100.0), 2)


def validate_habit_score() -> list[dict]:
    cases = [
        (
            "neutral_new_user",
            dict(
                wake_up_consistency_score=0,
                total_alarms_dismissed=0,
                total_snoozes=0,
                streak_days=0,
            ),
            22.5,
        ),
        (
            "known_74",
            dict(
                wake_up_consistency_score=80,
                total_alarms_dismissed=8,
                total_snoozes=2,
                streak_days=15,
            ),
            74.0,
        ),
        (
            "perfect",
            dict(
                wake_up_consistency_score=100,
                total_alarms_dismissed=10,
                total_snoozes=0,
                streak_days=30,
            ),
            100.0,
        ),
        (
            "only_snoozes",
            dict(
                wake_up_consistency_score=50,
                total_alarms_dismissed=0,
                total_snoozes=10,
                streak_days=0,
            ),
            None,
        ),
        (
            "cap_consistency",
            dict(
                wake_up_consistency_score=150,
                total_alarms_dismissed=1,
                total_snoozes=0,
                streak_days=30,
            ),
            None,
        ),
        (
            "streak_over_30",
            dict(
                wake_up_consistency_score=100,
                total_alarms_dismissed=5,
                total_snoozes=0,
                streak_days=60,
            ),
            None,
        ),
        (
            "equal_dismiss_snooze",
            dict(
                wake_up_consistency_score=70,
                total_alarms_dismissed=5,
                total_snoozes=5,
                streak_days=9,
            ),
            None,
        ),
        (
            "fractional_rounding",
            dict(
                wake_up_consistency_score=33.33,
                total_alarms_dismissed=1,
                total_snoozes=2,
                streak_days=1,
            ),
            None,
        ),
    ]
    rows = []
    for name, payload, expected in cases:
        actual = calculate_habit_score(payload)
        manual = manual_habit_score(payload)
        ok = actual["habit_score"] == manual and (
            expected is None or actual["habit_score"] == expected
        )
        rows.append(
            {
                "case": name,
                "actual": actual["habit_score"],
                "manual": manual,
                "expected": expected,
                "pass": ok,
                "breakdown": actual["breakdown"],
            }
        )
    return rows


def validate_analytics() -> list[dict]:
    rows = []
    # Wake consistency: 3 wakes at 07:00, 07:10, 07:20 → mean 07:10, std known.
    # Service rounds std first, then derives score so displayed std reconstructs it.
    minutes = np.array([7 * 60, 7 * 60 + 10, 7 * 60 + 20], dtype=float)
    mean_m = float(np.mean(minutes))
    std_m = float(np.round(float(np.std(minutes)), 2))
    consistency = float(
        np.round(float(np.clip(100.0 - (std_m * (100.0 / 60.0)), 0.0, 100.0)), 2)
    )
    preferred = 7 * 60.0
    deviations = BehavioralAnalyticsService._circular_minute_delta(minutes, preferred)
    on_time = int((np.abs(deviations) <= ON_TIME_TOLERANCE_MINUTES).sum())
    on_time_rate = round((on_time / len(minutes)) * 100.0, 2)

    now = pd.Timestamp.now(tz="UTC")
    wake_rows = []
    for i, m in enumerate(minutes):
        # Distinct calendar days so sleep adherence observes one wake per day
        day = now - pd.Timedelta(days=i + 1)
        dismissed = day.replace(
            hour=int(m // 60), minute=int(m % 60), second=0, microsecond=0
        )
        wake_rows.append(
            {
                "id": i + 1,
                "alarm_id": 1,
                "triggered_at": dismissed - pd.Timedelta(minutes=5),
                "dismissed_at": dismissed,
                "dismiss_method": "challenge",
                "snooze_count_at_dismiss": 0,
                "time_to_dismiss_seconds": 300,
                "verified": True,
                "wake_minutes": float(m),
            }
        )
    wake_df = pd.DataFrame(wake_rows)
    wake_df["triggered_at"] = pd.to_datetime(wake_df["triggered_at"], utc=True)
    wake_df["dismissed_at"] = pd.to_datetime(wake_df["dismissed_at"], utc=True)
    snooze_df = pd.DataFrame(
        columns=["id", "alarm_id", "snooze_number", "snooze_limit_at_event", "created_at"]
    )

    class _P:
        wake_up_consistency_score = 80.0
        sleep_duration_hours = 8.0
        streak_days = 15
        total_alarms_dismissed = 8
        total_snoozes = 2
        preferred_wake_time = None

    result = BehavioralAnalyticsService.analyze_wake_consistency(
        wake_df, preferred, _P()
    )
    rows.append(
        {
            "metric": "wake_consistency_score",
            "expected": consistency,
            "actual": result["consistency_score"],
            "pass": result["consistency_score"] == consistency,
        }
    )
    rows.append(
        {
            "metric": "wake_on_time_rate",
            "expected": on_time_rate,
            "actual": result["on_time_rate"],
            "pass": result["on_time_rate"] == on_time_rate,
        }
    )
    rows.append(
        {
            "metric": "wake_std_minutes",
            "expected": std_m,
            "actual": result["std_wake_minutes"],
            "pass": result["std_wake_minutes"] == std_m,
        }
    )

    # Snooze pattern: 4 snoozes, numbers 1,2,3,3 with limit 3 → 2 limit hits
    snooze_times = [now - pd.Timedelta(hours=h) for h in (1, 2, 3, 26)]
    snooze_df = pd.DataFrame(
        [
            {
                "id": i + 1,
                "alarm_id": 1,
                "snooze_number": n,
                "snooze_limit_at_event": 3,
                "created_at": t,
            }
            for i, (n, t) in enumerate(zip([1, 2, 3, 3], snooze_times))
        ]
    )
    snooze_df["created_at"] = pd.to_datetime(snooze_df["created_at"], utc=True)
    wake_for_snooze = wake_df.copy()
    wake_for_snooze["snooze_count_at_dismiss"] = [1, 2, 0]
    snooze_result = BehavioralAnalyticsService.analyze_snooze_pattern(
        snooze_df, wake_for_snooze
    )
    expected_limit_hits = 2
    expected_limit_rate = round((2 / 4) * 100.0, 2)
    expected_avg_number = round(float(np.mean([1, 2, 3, 3])), 2)
    expected_avg_per_wake = round(float(np.mean([1, 2, 0])), 2)
    rows.append(
        {
            "metric": "snooze_limit_hit_count",
            "expected": expected_limit_hits,
            "actual": snooze_result["limit_hit_count"],
            "pass": snooze_result["limit_hit_count"] == expected_limit_hits,
        }
    )
    rows.append(
        {
            "metric": "snooze_limit_hit_rate",
            "expected": expected_limit_rate,
            "actual": snooze_result["limit_hit_rate"],
            "pass": snooze_result["limit_hit_rate"] == expected_limit_rate,
        }
    )
    rows.append(
        {
            "metric": "avg_snooze_number",
            "expected": expected_avg_number,
            "actual": snooze_result["avg_snooze_number"],
            "pass": snooze_result["avg_snooze_number"] == expected_avg_number,
        }
    )
    rows.append(
        {
            "metric": "avg_snoozes_per_wake",
            "expected": expected_avg_per_wake,
            "actual": snooze_result["avg_snoozes_per_wake"],
            "pass": snooze_result["avg_snoozes_per_wake"] == expected_avg_per_wake,
        }
    )

    # Sleep adherence: 2 of 3 days within 15 min of preferred (distinct days)
    sleep = BehavioralAnalyticsService.analyze_sleep_adherence(
        wake_df, preferred, _P()
    )
    expected_adherence = on_time_rate
    rows.append(
        {
            "metric": "sleep_adherence_rate",
            "expected": expected_adherence,
            "actual": sleep["adherence_rate"],
            "pass": sleep["adherence_rate"] == expected_adherence,
            "note": f"observed_days={sleep['observed_days']} adherent_days={sleep['adherent_days']}",
        }
    )
    habit = calculate_habit_score(
        {
            "wake_up_consistency_score": 80,
            "total_alarms_dismissed": 8,
            "total_snoozes": 2,
            "streak_days": 15,
        }
    )
    rows.append(
        {
            "metric": "sleep_profile_adherence_score",
            "expected": habit["breakdown"]["sleep_adherence"],
            "actual": sleep["profile_adherence_score"],
            "pass": sleep["profile_adherence_score"]
            == habit["breakdown"]["sleep_adherence"],
        }
    )

    # Habit trends current must match SSOT
    habit_trends = BehavioralAnalyticsService.analyze_habit_trends(
        snooze_df, wake_df, pd.DataFrame(), preferred, _P()
    )
    rows.append(
        {
            "metric": "habit_trends_current_ssot",
            "expected": habit["habit_score"],
            "actual": habit_trends["current_habit_score"],
            "pass": habit_trends["current_habit_score"] == habit["habit_score"],
        }
    )
    return rows


def main() -> int:
    print("=== HABIT SCORE MANUAL VALIDATION ===")
    habit_rows = validate_habit_score()
    habit_fail = 0
    for r in habit_rows:
        status = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            habit_fail += 1
        print(
            f"[{status}] {r['case']}: actual={r['actual']} manual={r['manual']} "
            f"expected={r['expected']} breakdown={r['breakdown']}"
        )

    print("\n=== ANALYTICS MANUAL VALIDATION ===")
    analytics_rows = validate_analytics()
    analytics_fail = 0
    for r in analytics_rows:
        status = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            analytics_fail += 1
        note = f" ({r['note']})" if r.get("note") else ""
        print(
            f"[{status}] {r['metric']}: expected={r['expected']} actual={r['actual']}{note}"
        )

    print(
        f"\nSUMMARY: habit {len(habit_rows)-habit_fail}/{len(habit_rows)} pass; "
        f"analytics {len(analytics_rows)-analytics_fail}/{len(analytics_rows)} pass"
    )
    return 1 if (habit_fail or analytics_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
