"""
End-to-end integration test: full wake workflow.

Verifies the complete API path:

  login → alarm challenge (trigger) → solve → auto-dismiss
  → analytics updated → habit score recalculated
  → adaptive difficulty updated → recommendations updated
  → dashboard reflects latest values

Produces a step-by-step PASS/FAIL report on stdout and under
``tests/reports/e2e_wake_workflow_report.txt``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest

from app.models.analytics_event import AnalyticsEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import DifficultyPreference, UserProfile
from app.services.analytics_ingestion_service import AnalyticsEventType
from app.services.challenge_service import _adaptive_streak_threshold


REPORT_PATH = Path(__file__).resolve().parent / "reports" / "e2e_wake_workflow_report.txt"


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class WorkflowReport:
    steps: List[StepResult] = field(default_factory=list)

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.steps.append(StepResult(name=name, passed=passed, detail=detail))

    def run(self, name: str, fn: Callable[[], Any]) -> Any:
        """Execute a step, capture pass/fail, re-raise on failure after recording."""
        try:
            value = fn()
            self.record(name, True, detail=_short(value))
            return value
        except Exception as exc:  # noqa: BLE001 — report then re-raise
            self.record(name, False, detail=str(exc))
            raise

    @property
    def all_passed(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    def render(self) -> str:
        lines = [
            "E2E Wake Workflow — Pass/Fail Report",
            f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
            "=" * 60,
        ]
        for i, step in enumerate(self.steps, start=1):
            status = "PASS" if step.passed else "FAIL"
            lines.append(f"{i:02d}. [{status}] {step.name}")
            if step.detail:
                lines.append(f"     {step.detail}")
        lines.append("=" * 60)
        overall = "PASS" if self.all_passed else "FAIL"
        passed = sum(1 for s in self.steps if s.passed)
        lines.append(f"Overall: {overall} ({passed}/{len(self.steps)} steps)")
        return "\n".join(lines) + "\n"

    def write(self) -> Path:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(self.render(), encoding="utf-8")
        return REPORT_PATH


def _short(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    text = repr(value) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


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


def _event_counts(summary_json: dict) -> dict:
    return {
        item["event_type"]: item["count"]
        for item in summary_json.get("by_event_type", [])
    }


class TestE2EWakeWorkflow:
    """Complete login → wake → dashboard integration path."""

    def test_complete_wake_workflow_end_to_end(
        self, client, test_user, db_session
    ):
        report = WorkflowReport()
        headers: Optional[dict] = None
        user_id = test_user.id
        alarm_id: Optional[int] = None
        before_habit: Optional[float] = None
        before_difficulty: Optional[str] = None
        before_dismissed: Optional[int] = None
        before_analytics: Optional[dict] = None
        before_recs_score: Optional[float] = None
        before_dashboard_score: Optional[float] = None
        threshold = _adaptive_streak_threshold()

        try:
            # ── 1. Login ──────────────────────────────────────────────
            def step_login():
                nonlocal headers
                res = client.post(
                    "/api/v1/auth/login",
                    json={"email": "test@example.com", "password": "TestPass123"},
                )
                assert res.status_code == 200, res.text
                body = res.json()
                assert body.get("token_type") == "bearer"
                assert body.get("access_token")
                headers = {"Authorization": f"Bearer {body['access_token']}"}
                me = client.get("/api/v1/auth/me", headers=headers)
                assert me.status_code == 200
                assert me.json()["email"] == "test@example.com"
                return "login ok"

            report.run("User login", step_login)

            # ── Ensure profile exists (lazy create) ───────────────────
            def step_profile():
                res = client.get("/api/v1/profiles/me", headers=headers)
                assert res.status_code == 200, res.text
                profile = (
                    db_session.query(UserProfile)
                    .filter(UserProfile.user_id == user_id)
                    .one()
                )
                # Seed just below adaptive threshold so one full wake raises difficulty.
                profile.difficulty_preference = DifficultyPreference.MEDIUM
                profile.consecutive_success_streak = threshold - 1
                profile.consecutive_failure_streak = 0
                db_session.commit()
                db_session.refresh(profile)
                return {
                    "difficulty": profile.difficulty_preference.value,
                    "success_streak": profile.consecutive_success_streak,
                    "threshold": threshold,
                }

            seeded = report.run("Ensure profile + seed adaptive streak", step_profile)
            before_difficulty = seeded["difficulty"]

            # ── Create alarm ──────────────────────────────────────────
            def step_create_alarm():
                nonlocal alarm_id
                res = client.post(
                    "/api/v1/alarms/",
                    json={
                        "title": "E2E Wake Workflow",
                        "alarm_time": "07:00",
                        "alarm_type": "daily",
                        "challenge_type": "math",
                        "challenge_count": 1,
                        "snooze_limit": 3,
                    },
                    headers=headers,
                )
                assert res.status_code == 201, res.text
                alarm_id = res.json()["id"]
                return f"alarm_id={alarm_id}"

            report.run("Create alarm", step_create_alarm)

            # ── Capture before-state ──────────────────────────────────
            def step_baselines():
                nonlocal before_habit, before_dismissed
                nonlocal before_analytics, before_recs_score, before_dashboard_score

                habit = client.get(
                    "/api/v1/profiles/me/habit-score", headers=headers
                )
                assert habit.status_code == 200, habit.text
                before_habit = habit.json()["habit_score"]

                profile = client.get("/api/v1/profiles/me", headers=headers)
                assert profile.status_code == 200, profile.text
                before_dismissed = profile.json()["total_alarms_dismissed"]

                analytics = client.get(
                    "/api/v1/analytics/summary", headers=headers
                )
                assert analytics.status_code == 200, analytics.text
                before_analytics = _event_counts(analytics.json())

                recs = client.get("/api/v1/recommendations", headers=headers)
                assert recs.status_code == 200, recs.text
                before_recs_score = recs.json()["summary"]["habit_score"]

                stats = client.get(
                    "/api/v1/users/profile/stats", headers=headers
                )
                assert stats.status_code == 200, stats.text
                before_dashboard_score = stats.json()["current_habit_score"]

                assert before_habit == before_recs_score == before_dashboard_score
                return {
                    "habit_score": before_habit,
                    "dismissed": before_dismissed,
                    "analytics": before_analytics,
                }

            report.run("Capture pre-wake baselines", step_baselines)

            # ── 2. Alarm triggers / challenge starts ──────────────────
            def step_challenge_starts():
                res = client.get(
                    f"/api/v1/alarms/{alarm_id}/challenge", headers=headers
                )
                assert res.status_code == 200, res.text
                ch = res.json()
                assert "prompt" in ch
                assert "answer" not in ch
                assert ch.get("required_correct", 1) >= 1
                assert "difficulty" in ch
                return {
                    "type": ch.get("type"),
                    "difficulty": ch.get("difficulty"),
                    "prompt": ch.get("prompt"),
                }

            challenge = report.run(
                "Alarm triggers / challenge starts", step_challenge_starts
            )

            # ── 3–5. Challenge solved → alarm dismissed ───────────────
            def step_solve_and_dismiss():
                answer = _session_answer(db_session, user_id, alarm_id)
                res = client.post(
                    f"/api/v1/alarms/{alarm_id}/verify",
                    json={
                        "user_answer": answer,
                        "time_taken_seconds": 5,
                        "challenge_prompt": challenge["prompt"],
                        "challenge_difficulty": challenge["difficulty"],
                    },
                    headers=headers,
                )
                assert res.status_code == 200, res.text
                body = res.json()
                assert body["is_dismissed"] is True
                assert body["status"] == "dismissed"
                assert body["wake_confirmed"] is True
                assert "wakefulness" in body
                return {
                    "status": body["status"],
                    "wakefulness": body["wakefulness"].get("level"),
                }

            report.run("Challenge solved → alarm dismissed", step_solve_and_dismiss)

            # ── 6. Analytics updated ──────────────────────────────────
            def step_analytics():
                summary = client.get(
                    "/api/v1/analytics/summary", headers=headers
                )
                assert summary.status_code == 200, summary.text
                counts = _event_counts(summary.json())

                dismissed_events = (
                    db_session.query(AnalyticsEvent)
                    .filter(
                        AnalyticsEvent.user_id == user_id,
                        AnalyticsEvent.event_type
                        == AnalyticsEventType.ALARM_DISMISSED,
                    )
                    .count()
                )
                attempted_events = (
                    db_session.query(AnalyticsEvent)
                    .filter(
                        AnalyticsEvent.user_id == user_id,
                        AnalyticsEvent.event_type
                        == AnalyticsEventType.CHALLENGE_ATTEMPTED,
                    )
                    .count()
                )
                wake_events = (
                    db_session.query(AlarmWakeEvent)
                    .filter(
                        AlarmWakeEvent.user_id == user_id,
                        AlarmWakeEvent.verified.is_(True),
                    )
                    .count()
                )

                assert dismissed_events >= 1, "Expected alarm.dismissed analytics event"
                assert attempted_events >= 1, "Expected challenge.attempted analytics event"
                assert wake_events >= 1, "Expected verified AlarmWakeEvent"

                before_dismissed_count = before_analytics.get(
                    AnalyticsEventType.ALARM_DISMISSED, 0
                )
                after_dismissed_count = counts.get(
                    AnalyticsEventType.ALARM_DISMISSED, 0
                )
                assert after_dismissed_count > before_dismissed_count

                behavioral = client.get(
                    "/api/v1/analytics/behavioral", headers=headers
                )
                assert behavioral.status_code == 200, behavioral.text

                return {
                    "alarm.dismissed": after_dismissed_count,
                    "challenge.attempted": counts.get(
                        AnalyticsEventType.CHALLENGE_ATTEMPTED, 0
                    ),
                    "wake_events": wake_events,
                }

            report.run("Analytics updated", step_analytics)

            # ── 7. Habit score recalculated ───────────────────────────
            def step_habit_score():
                res = client.get(
                    "/api/v1/profiles/me/habit-score", headers=headers
                )
                assert res.status_code == 200, res.text
                body = res.json()
                after = body["habit_score"]
                assert after != before_habit, (
                    f"Habit score should change after wake "
                    f"(before={before_habit}, after={after})"
                )
                assert "breakdown" in body
                return {"before": before_habit, "after": after}

            habit_after = report.run("Habit score recalculated", step_habit_score)

            # ── 8. Adaptive difficulty updated ────────────────────────
            def step_adaptive():
                profile = (
                    db_session.query(UserProfile)
                    .filter(UserProfile.user_id == user_id)
                    .one()
                )
                db_session.refresh(profile)
                api_profile = client.get(
                    "/api/v1/profiles/me", headers=headers
                )
                assert api_profile.status_code == 200, api_profile.text
                pref = api_profile.json()["difficulty_preference"]

                assert pref == DifficultyPreference.HARD.value, (
                    f"Expected difficulty raise {before_difficulty}→hard, got {pref}"
                )
                assert profile.difficulty_preference == DifficultyPreference.HARD
                # Streaks reset after persistence at threshold
                assert profile.consecutive_success_streak == 0
                assert profile.consecutive_failure_streak == 0
                assert api_profile.json()["total_alarms_dismissed"] == before_dismissed + 1
                return {
                    "before": before_difficulty,
                    "after": pref,
                    "success_streak": profile.consecutive_success_streak,
                }

            report.run("Adaptive difficulty updated", step_adaptive)

            # ── 9. Recommendations updated ────────────────────────────
            def step_recommendations():
                res = client.get("/api/v1/recommendations", headers=headers)
                assert res.status_code == 200, res.text
                body = res.json()
                summary_score = body["summary"]["habit_score"]
                assert summary_score == habit_after["after"], (
                    f"Recommendations summary habit_score={summary_score} "
                    f"!= habit-score API {habit_after['after']}"
                )
                assert summary_score != before_recs_score
                assert isinstance(body.get("recommendations"), list)
                assert len(body["recommendations"]) >= 1
                return {
                    "summary_habit_score": summary_score,
                    "recommendation_count": len(body["recommendations"]),
                }

            report.run("Recommendations updated", step_recommendations)

            # ── 10. Dashboard reflects latest values ──────────────────
            def step_dashboard():
                stats = client.get(
                    "/api/v1/users/profile/stats", headers=headers
                )
                assert stats.status_code == 200, stats.text
                body = stats.json()
                assert body["current_habit_score"] == habit_after["after"]
                assert body["current_habit_score"] != before_dashboard_score

                behavioral_habits = client.get(
                    "/api/v1/analytics/behavioral/habits", headers=headers
                )
                assert behavioral_habits.status_code == 200, behavioral_habits.text
                assert (
                    behavioral_habits.json()["current_habit_score"]
                    == habit_after["after"]
                )

                profile = client.get("/api/v1/profiles/me", headers=headers)
                assert profile.status_code == 200
                assert profile.json()["difficulty_preference"] == "hard"
                assert profile.json()["total_alarms_dismissed"] == before_dismissed + 1

                return {
                    "current_habit_score": body["current_habit_score"],
                    "current_streak": body.get("current_streak"),
                    "wakeup_success_rate": body.get("wakeup_success_rate"),
                }

            report.run("Dashboard reflects latest values", step_dashboard)

        finally:
            path = report.write()
            rendered = report.render()
            print("\n" + rendered)
            print(f"Report written to: {path}")

        assert report.all_passed, "E2E workflow had failing steps — see report"
