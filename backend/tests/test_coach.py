"""Tests for the Wellness Coach APIs.

Covers three things that matter most for this surface:

1. **Role restriction** — only ``wellness_coach`` (and ``admin``) may call the
   coach endpoints.
2. **Assignment scoping** — a coach can reach data for assigned clients only,
   and an unassigned client is indistinguishable from a missing one.
3. **Real data** — roster figures are computed from wake events, snooze events,
   and challenge logs actually present in the database.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.coach_assignment import CoachAssignment
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole
from app.core.security import create_access_token
from app.utils.hashing import get_password_hash

# Every client-scoped coach route, used to assert restrictions uniformly.
CLIENT_SUBRESOURCES = (
    "",
    "/behavioral",
    "/sleep-trends",
    "/wake-consistency",
    "/habit-score",
    "/challenge-performance",
    "/productivity",
    "/recommendations",
)


# ── Helpers ──────────────────────────────────────────────────────────────


def make_user(db, *, username, email, role=UserRole.USER, is_active=True):
    """Create a user with a profile and return it."""
    user = User(
        email=email,
        username=username,
        hashed_password=get_password_hash("ClientPass123"),
        full_name=f"{username.title()} Name",
        role=role,
        is_active=is_active,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    profile = UserProfile(
        user_id=user.id,
        sleep_duration_hours=8.0,
        timezone="UTC",
        difficulty_preference=DifficultyPreference.MEDIUM,
        adapted_difficulty=DifficultyPreference.MEDIUM,
    )
    db.add(profile)
    db.commit()
    db.refresh(user)
    return user


def assign(db, coach, client, *, is_active=True):
    """Create a coach/client assignment row."""
    row = CoachAssignment(
        coach_id=coach.id,
        client_id=client.id,
        is_active=is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def headers_for(user):
    """Build Authorization headers for an arbitrary user."""
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


def seed_activity(
    db,
    user,
    *,
    verified_wakes=3,
    snoozes_per_wake=0,
    challenge_attempts=4,
    challenge_correct=3,
    snooze_events=2,
):
    """Seed real wake / snooze / challenge rows for a user."""
    alarm = Alarm(
        user_id=user.id,
        title="Morning",
        alarm_time=datetime.now(timezone.utc).time(),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        is_active=True,
    )
    db.add(alarm)
    db.flush()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(verified_wakes):
        moment = now - timedelta(days=verified_wakes - i - 1, hours=1)
        db.add(
            AlarmWakeEvent(
                user_id=user.id,
                alarm_id=alarm.id,
                triggered_at=moment,
                dismissed_at=moment + timedelta(minutes=5),
                dismiss_method="challenge",
                challenges_required=1,
                challenges_completed=1,
                snooze_count_at_dismiss=snoozes_per_wake,
                time_to_dismiss_seconds=300,
                wakefulness_score=80.0,
                wakefulness_level="alert",
                verified=True,
            )
        )

    for i in range(snooze_events):
        db.add(
            AlarmSnoozeEvent(
                user_id=user.id,
                alarm_id=alarm.id,
                snooze_number=i + 1,
                snooze_limit_at_event=3,
                created_at=now - timedelta(days=i),
            )
        )

    for i in range(challenge_attempts):
        db.add(
            AlarmChallengeLog(
                user_id=user.id,
                alarm_id=alarm.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt="2 + 2",
                is_correct=i < challenge_correct,
                time_taken_seconds=10,
                failed_attempts=0,
                points_earned=10 if i < challenge_correct else 0,
                created_at=now - timedelta(days=i),
            )
        )

    db.commit()
    return alarm


@pytest.fixture
def roster(db_session, coach_user):
    """A coach with two assigned clients and one unassigned outsider."""
    assigned_a = make_user(db_session, username="clienta", email="a@example.com")
    assigned_b = make_user(db_session, username="clientb", email="b@example.com")
    outsider = make_user(db_session, username="outsider", email="out@example.com")

    assign(db_session, coach_user, assigned_a)
    assign(db_session, coach_user, assigned_b)

    # assigned_a: 5 verified wakes, 3 of 4 challenges correct (75% accuracy).
    seed_activity(db_session, assigned_a, verified_wakes=5, challenge_correct=3)
    # assigned_b is deliberately left without activity to exercise empty states.
    seed_activity(
        db_session, outsider, verified_wakes=9, challenge_attempts=9, challenge_correct=9
    )

    return {
        "coach": coach_user,
        "assigned_a": assigned_a,
        "assigned_b": assigned_b,
        "outsider": outsider,
    }


# ── Role restriction ─────────────────────────────────────────────────────


class TestCoachRoleRestriction:
    """Only wellness coaches and admins may reach the coach APIs."""

    def test_regular_user_forbidden_on_roster(self, client, auth_headers):
        for path in ("/api/v1/coach/overview", "/api/v1/coach/clients"):
            response = client.get(path, headers=auth_headers)
            assert response.status_code == 403, path
            assert "Wellness coach" in response.json()["detail"]

    def test_regular_user_forbidden_on_client_routes(
        self, client, auth_headers, roster
    ):
        client_id = roster["assigned_a"].id
        for suffix in CLIENT_SUBRESOURCES:
            response = client.get(
                f"/api/v1/coach/clients/{client_id}{suffix}", headers=auth_headers
            )
            assert response.status_code == 403, suffix

    def test_unauthenticated_rejected(self, client):
        response = client.get("/api/v1/coach/clients")
        assert response.status_code == 401

    def test_coach_role_allowed(self, client, coach_headers):
        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        assert response.status_code == 200

    def test_admin_role_allowed(self, client, admin_headers):
        response = client.get("/api/v1/coach/clients", headers=admin_headers)
        assert response.status_code == 200

    def test_inactive_coach_rejected(self, client, db_session, coach_user):
        coach_user.is_active = False
        db_session.commit()
        response = client.get(
            "/api/v1/coach/clients", headers=headers_for(coach_user)
        )
        assert response.status_code == 403

    def test_coach_cannot_manage_assignments(self, client, coach_headers, roster):
        response = client.post(
            "/api/v1/admin/coach-assignments",
            headers=coach_headers,
            json={
                "coach_id": roster["coach"].id,
                "client_id": roster["outsider"].id,
            },
        )
        assert response.status_code == 403


# ── Assignment scoping ───────────────────────────────────────────────────


class TestAssignmentScoping:
    """A coach sees assigned clients only."""

    def test_roster_contains_only_assigned_clients(
        self, client, coach_headers, roster
    ):
        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        assert response.status_code == 200
        body = response.json()

        returned_ids = {row["client_id"] for row in body["clients"]}
        assert returned_ids == {roster["assigned_a"].id, roster["assigned_b"].id}
        assert roster["outsider"].id not in returned_ids
        assert body["total"] == 2
        assert body["total_assigned"] == 2

    def test_unassigned_client_returns_404_everywhere(
        self, client, coach_headers, roster
    ):
        outsider_id = roster["outsider"].id
        for suffix in CLIENT_SUBRESOURCES:
            response = client.get(
                f"/api/v1/coach/clients/{outsider_id}{suffix}",
                headers=coach_headers,
            )
            assert response.status_code == 404, suffix

    def test_nonexistent_client_matches_unassigned_response(
        self, client, coach_headers, roster
    ):
        """Same 404 for both so existence outside the roster stays hidden."""
        unassigned = client.get(
            f"/api/v1/coach/clients/{roster['outsider'].id}", headers=coach_headers
        )
        missing = client.get("/api/v1/coach/clients/999999", headers=coach_headers)
        assert unassigned.status_code == missing.status_code == 404
        assert unassigned.json()["detail"] == missing.json()["detail"]

    def test_other_coach_cannot_see_first_coachs_clients(
        self, client, db_session, roster
    ):
        other_coach = make_user(
            db_session,
            username="coach2",
            email="coach2@example.com",
            role=UserRole.WELLNESS_COACH,
        )
        response = client.get(
            "/api/v1/coach/clients", headers=headers_for(other_coach)
        )
        assert response.status_code == 200
        assert response.json()["clients"] == []

        detail = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}",
            headers=headers_for(other_coach),
        )
        assert detail.status_code == 404

    def test_deactivated_assignment_revokes_access(
        self, client, db_session, coach_headers, roster
    ):
        assignment = (
            db_session.query(CoachAssignment)
            .filter(CoachAssignment.client_id == roster["assigned_a"].id)
            .first()
        )
        assignment.is_active = False
        db_session.commit()

        listing = client.get("/api/v1/coach/clients", headers=coach_headers)
        ids = {row["client_id"] for row in listing.json()["clients"]}
        assert roster["assigned_a"].id not in ids

        detail = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/behavioral",
            headers=coach_headers,
        )
        assert detail.status_code == 404


# ── Empty states ─────────────────────────────────────────────────────────


class TestEmptyStates:
    """A coach with no assignments gets empty payloads, not errors."""

    def test_empty_client_list(self, client, coach_headers):
        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["clients"] == []
        assert body["total"] == 0
        assert body["total_assigned"] == 0
        assert body["total_pages"] == 1

    def test_empty_overview_flags_is_empty(self, client, coach_headers):
        response = client.get("/api/v1/coach/overview", headers=coach_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["is_empty"] is True
        assert body["total_clients"] == 0
        assert body["avg_habit_score"] == 0.0
        assert body["attention_clients"] == []

    def test_client_without_activity_still_listed(
        self, client, coach_headers, roster
    ):
        """assigned_b has no seeded rows — it must appear with zeroed metrics."""
        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        row = next(
            r
            for r in response.json()["clients"]
            if r["client_id"] == roster["assigned_b"].id
        )
        assert row["verified_wakes"] == 0
        assert row["challenge_attempts"] == 0
        assert row["has_activity"] is False
        assert row["last_wake_at"] is None
        assert row["needs_attention"] is True


# ── Real data ────────────────────────────────────────────────────────────


class TestRealDataAggregation:
    """Roster figures are derived from rows in the database."""

    def test_overview_habit_average_matches_client_scores(
        self, db_session, client, coach_headers, roster
    ):
        target = roster["assigned_a"]
        alarm = db_session.query(Alarm).filter(Alarm.user_id == target.id).first()
        moment = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
        db_session.add(
            AlarmWakeEvent(
                user_id=target.id,
                alarm_id=alarm.id,
                triggered_at=moment,
                dismissed_at=moment + timedelta(minutes=5),
                dismiss_method="snooze_exhausted",
                challenges_required=1,
                challenges_completed=0,
                snooze_count_at_dismiss=3,
                time_to_dismiss_seconds=300,
                wakefulness_score=30.0,
                wakefulness_level="drowsy",
                verified=True,
            )
        )
        db_session.add(
            AlarmChallengeLog(
                user_id=target.id,
                alarm_id=alarm.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt="2 + 2",
                is_correct=False,
                time_taken_seconds=20,
                failed_attempts=1,
                points_earned=0,
                created_at=moment,
            )
        )
        db_session.commit()

        seven_days = client.get(
            "/api/v1/coach/overview?days=7", headers=coach_headers
        ).json()
        ninety_days = client.get(
            "/api/v1/coach/overview?days=90", headers=coach_headers
        ).json()
        clients = client.get(
            "/api/v1/coach/clients?page_size=100", headers=coach_headers
        ).json()["clients"]

        active_scores = [row["habit_score"] for row in clients if row["is_active"]]
        expected = round(sum(active_scores) / len(active_scores), 1)

        assert seven_days["avg_habit_score"] == expected
        assert ninety_days["avg_habit_score"] == expected

    def test_headline_kpis_use_active_clients_and_challenge_engagement(
        self, db_session, client, coach_headers, roster
    ):
        roster["assigned_a"].is_active = False
        seed_activity(
            db_session,
            roster["assigned_b"],
            verified_wakes=0,
            challenge_attempts=2,
            challenge_correct=1,
            snooze_events=0,
        )
        db_session.commit()

        body = client.get(
            "/api/v1/coach/overview?days=7", headers=coach_headers
        ).json()

        assert body["total_clients"] == 2
        assert body["active_clients"] == 1
        assert body["engaged_clients"] == 1
        assert body["engagement_rate"] == 100.0
        assert body["needs_attention_count"] == 1
        assert body["total_verified_wakes"] == 0

    def test_reporting_windows_recalculate_period_metrics(
        self, db_session, client, coach_headers, roster
    ):
        target = roster["assigned_a"]
        alarm = (
            db_session.query(Alarm)
            .filter(Alarm.user_id == target.id)
            .first()
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        for age_days in (20, 60):
            moment = now - timedelta(days=age_days)
            db_session.add(
                AlarmWakeEvent(
                    user_id=target.id,
                    alarm_id=alarm.id,
                    triggered_at=moment,
                    dismissed_at=moment + timedelta(minutes=5),
                    dismiss_method="challenge",
                    challenges_required=1,
                    challenges_completed=1,
                    snooze_count_at_dismiss=0,
                    time_to_dismiss_seconds=300,
                    wakefulness_score=80.0,
                    wakefulness_level="alert",
                    verified=True,
                )
            )
            db_session.add(
                AlarmChallengeLog(
                    user_id=target.id,
                    alarm_id=alarm.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt="2 + 2",
                    is_correct=True,
                    time_taken_seconds=10,
                    failed_attempts=0,
                    points_earned=10,
                    created_at=moment,
                )
            )
        db_session.commit()

        expected = {
            7: (5, 4),
            30: (6, 5),
            90: (7, 6),
        }
        for days, (wake_count, challenge_count) in expected.items():
            overview = client.get(
                f"/api/v1/coach/overview?days={days}", headers=coach_headers
            )
            behavioral = client.get(
                f"/api/v1/coach/clients/{target.id}/behavioral?days={days}",
                headers=coach_headers,
            )
            challenges = client.get(
                f"/api/v1/coach/clients/{target.id}/challenge-performance?days={days}",
                headers=coach_headers,
            )

            assert overview.status_code == 200
            assert behavioral.status_code == 200
            assert challenges.status_code == 200
            assert overview.json()["total_verified_wakes"] == wake_count
            assert behavioral.json()["days"] == days
            assert (
                behavioral.json()["data"]["wake_up_consistency"]["verified_wakes"]
                == wake_count
            )
            assert challenges.json()["data"]["total_attempts"] == challenge_count

    def test_client_metrics_reflect_seeded_rows(
        self, client, coach_headers, roster
    ):
        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        row = next(
            r
            for r in response.json()["clients"]
            if r["client_id"] == roster["assigned_a"].id
        )
        assert row["verified_wakes"] == 5
        assert row["challenge_attempts"] == 4
        assert row["challenge_accuracy"] == 75.0
        assert row["snoozes"] == 2
        assert row["active_alarms"] == 1
        assert row["habit_score"] > 0
        assert row["last_wake_at"] is not None
        assert set(row["habit_breakdown"]) == {
            "wake_up_consistency",
            "challenge_completion",
            "snooze_reduction",
            "sleep_adherence",
        }

    def test_habit_score_matches_canonical_service(
        self, db_session, client, coach_headers, roster
    ):
        from app.services.habit_score import calculate_habit_score_for_user

        target = roster["assigned_a"]
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == target.id)
            .first()
        )
        expected = calculate_habit_score_for_user(db_session, target.id, profile)

        response = client.get(
            f"/api/v1/coach/clients/{target.id}/habit-score", headers=coach_headers
        )
        assert response.status_code == 200
        assert response.json()["data"]["habit_score"] == expected["habit_score"]

    def test_overview_aggregates_across_roster(self, client, coach_headers, roster):
        response = client.get("/api/v1/coach/overview", headers=coach_headers)
        body = response.json()
        assert body["is_empty"] is False
        assert body["total_clients"] == 2
        assert body["total_verified_wakes"] == 5
        assert body["challenge_attempts"] == 4
        assert body["engaged_clients"] == 1
        assert body["engagement_rate"] == 50.0
        assert len(body["habit_score_distribution"]) == 4
        # The outsider's 9 wakes must not leak into roster totals.
        assert body["total_verified_wakes"] == 5

    def test_detail_exposes_profile_context_and_goals(
        self, db_session, client, coach_headers, roster
    ):
        target = roster["assigned_a"]
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == target.id)
            .first()
        )
        profile.productivity_goals = ["Wake up by 6 AM", "Exercise daily"]
        db_session.commit()

        body = client.get(
            f"/api/v1/coach/clients/{target.id}", headers=coach_headers
        ).json()

        assert body["goals"] == ["Wake up by 6 AM", "Exercise daily"]
        assert body["client"]["timezone"] == "UTC"
        assert body["client"]["last_wake_at"] is not None
        assert body["client"]["email"] == target.email

    def test_detail_normalizes_legacy_string_goals(
        self, db_session, client, coach_headers, roster
    ):
        """Legacy rows store a comma-separated string instead of a list."""
        target = roster["assigned_a"]
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == target.id)
            .first()
        )
        profile.productivity_goals = "Sleep by 10 PM, Read nightly"
        db_session.commit()

        body = client.get(
            f"/api/v1/coach/clients/{target.id}", headers=coach_headers
        ).json()

        assert body["goals"] == ["Sleep by 10 PM", "Read nightly"]

    def test_behavioral_payload_is_client_scoped(
        self, client, coach_headers, roster
    ):
        response = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/behavioral",
            headers=coach_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["client_id"] == roster["assigned_a"].id
        assert body["data"]["wake_up_consistency"]["verified_wakes"] == 5
        for key in (
            "sleep_schedule_adherence",
            "wake_up_consistency",
            "habit_trends",
            "snooze_pattern",
            "weekly_trends",
            "monthly_trends",
        ):
            assert key in body["data"], key

    def test_behaviour_insight_blocks_expose_their_fields(
        self, client, coach_headers, roster
    ):
        """The three coach insight blocks render only real payload fields."""
        data = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/behavioral",
            headers=coach_headers,
        ).json()["data"]

        for key in (
            "total_snoozes",
            "avg_snoozes_per_wake",
            "limit_hit_rate",
            "peak_weekday",
            "peak_hour",
        ):
            assert key in data["snooze_pattern"], key

        for key in (
            "consistency_score",
            "verified_wakes",
            "mean_wake_time",
            "std_wake_minutes",
            "on_time_rate",
            "tolerance_minutes",
        ):
            assert key in data["wake_up_consistency"], key

        for key in (
            "preferred_wake_time",
            "target_sleep_hours",
            "suggested_bedtime",
            "adherence_rate",
            "adherent_days",
            "observed_days",
            "avg_deviation_minutes",
        ):
            assert key in data["sleep_schedule_adherence"], key

    def test_challenge_and_productivity_payloads(
        self, client, coach_headers, roster
    ):
        client_id = roster["assigned_a"].id

        challenge = client.get(
            f"/api/v1/coach/clients/{client_id}/challenge-performance",
            headers=coach_headers,
        )
        assert challenge.status_code == 200
        assert challenge.json()["data"]["total_attempts"] == 4
        assert challenge.json()["data"]["correct_answers"] == 3

        productivity = client.get(
            f"/api/v1/coach/clients/{client_id}/productivity",
            headers=coach_headers,
        )
        assert productivity.status_code == 200
        assert "morning_routine_score" in productivity.json()["data"]
        assert productivity.json()["data"]["verified_wakes"] == 5

    def test_recommendations_are_generated_for_the_client(
        self, client, coach_headers, roster
    ):
        response = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/recommendations",
            headers=coach_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "recommendations" in body
        assert "summary" in body
        assert "daily_plan" in body

    def test_sleep_and_wake_endpoints_return_their_sections(
        self, client, coach_headers, roster
    ):
        client_id = roster["assigned_a"].id

        sleep = client.get(
            f"/api/v1/coach/clients/{client_id}/sleep-trends", headers=coach_headers
        )
        assert sleep.status_code == 200
        assert "sleep_schedule_adherence" in sleep.json()["data"]
        assert "habit_trends" in sleep.json()["data"]

        wake = client.get(
            f"/api/v1/coach/clients/{client_id}/wake-consistency",
            headers=coach_headers,
        )
        assert wake.status_code == 200
        assert "wake_up_consistency" in wake.json()["data"]
        assert "snooze_pattern" in wake.json()["data"]

    def test_sleep_trends_carry_all_three_adherence_views(
        self, client, coach_headers, roster
    ):
        """Sleep Trends needs sleep adherence, wake consistency, and schedule."""
        response = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/sleep-trends",
            params={"days": 7},
            headers=coach_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["sleep_schedule_adherence"]["adherence_rate"] is not None
        assert "consistency_score" in data["wake_up_consistency"]
        assert "on_time_rate" in data["window_trends"]["totals"]

    def test_series_span_the_selected_reporting_period(
        self, client, coach_headers, roster
    ):
        """7 / 30 / 90 selection sizes the charted series, not a fixed month."""
        client_id = roster["assigned_a"].id
        for days in (7, 30, 90):
            response = client.get(
                f"/api/v1/coach/clients/{client_id}/behavioral",
                params={"days": days},
                headers=coach_headers,
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data["habit_trends"]["series"]) == days, days
            assert len(data["window_trends"]["series"]) == days, days

    def test_habit_score_reuses_canonical_weights_and_exposes_movement(
        self, client, coach_headers, roster
    ):
        response = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/habit-score",
            headers=coach_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["weights"] == {
            "wake_up_consistency": 0.35,
            "challenge_completion": 0.25,
            "snooze_reduction": 0.20,
            "sleep_adherence": 0.20,
        }
        detail = data["habit_trends"]["trend_detail"]
        assert detail["direction"] == data["habit_trends"]["trend"]
        assert detail["change"] == pytest.approx(
            detail["recent_avg"] - detail["previous_avg"], abs=0.01
        )

    def test_recent_attempts_carry_every_coaching_field(
        self, client, coach_headers, roster
    ):
        response = client.get(
            f"/api/v1/coach/clients/{roster['assigned_a'].id}/challenge-performance",
            headers=coach_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert len(data["recent_activity"]) == data["total_attempts"]
        for attempt in data["recent_activity"]:
            for key in (
                "created_at",
                "challenge_type",
                "difficulty",
                "is_correct",
                "time_taken_seconds",
                "points_earned",
            ):
                assert key in attempt, key

    def test_coach_read_does_not_mutate_client_streak(
        self, db_session, client, coach_headers, roster
    ):
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == roster["assigned_a"].id)
            .first()
        )
        profile.streak_days = 12
        profile.last_successful_wake_date = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).date()
        db_session.commit()

        response = client.get("/api/v1/coach/clients", headers=coach_headers)
        row = next(
            r
            for r in response.json()["clients"]
            if r["client_id"] == roster["assigned_a"].id
        )
        # Display applies missed-day decay …
        assert row["streak_days"] == 0
        # … without writing it back to the client's row.
        db_session.refresh(profile)
        assert profile.streak_days == 12


# ── Pagination, search, sorting ──────────────────────────────────────────


class TestPaginationAndFiltering:
    """Server-side pagination, search, and sort behave predictably."""

    @pytest.fixture
    def big_roster(self, db_session, coach_user):
        clients = []
        for i in range(7):
            user = make_user(
                db_session,
                username=f"bulk{i}",
                email=f"bulk{i}@example.com",
            )
            assign(db_session, coach_user, user)
            seed_activity(
                db_session,
                user,
                verified_wakes=i,
                challenge_attempts=i,
                challenge_correct=i,
                snooze_events=i,
            )
            clients.append(user)
        return clients

    def test_pagination_splits_roster_without_overlap(
        self, client, coach_headers, big_roster
    ):
        first = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"per_page": 3, "page": 1},
        ).json()
        second = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"per_page": 3, "page": 2},
        ).json()
        third = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"per_page": 3, "page": 3},
        ).json()

        assert first["total"] == 7
        assert first["total_pages"] == 3
        assert len(first["clients"]) == 3
        assert len(second["clients"]) == 3
        assert len(third["clients"]) == 1

        ids = (
            [r["client_id"] for r in first["clients"]]
            + [r["client_id"] for r in second["clients"]]
            + [r["client_id"] for r in third["clients"]]
        )
        assert len(ids) == len(set(ids)) == 7

    def test_page_beyond_end_is_empty_not_an_error(
        self, client, coach_headers, big_roster
    ):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"per_page": 3, "page": 99},
        )
        assert response.status_code == 200
        assert response.json()["clients"] == []

    def test_search_filters_but_reports_full_roster_size(
        self, client, coach_headers, roster
    ):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"search": "clienta"},
        )
        body = response.json()
        assert body["total"] == 1
        assert body["total_assigned"] == 2
        assert body["clients"][0]["client_id"] == roster["assigned_a"].id

    def test_search_cannot_reach_unassigned_users(
        self, client, coach_headers, roster
    ):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"search": "outsider"},
        )
        assert response.json()["clients"] == []

    def test_sort_by_habit_score_desc(self, client, coach_headers, big_roster):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"sort_by": "habit_score", "sort_order": "desc", "per_page": 100},
        )
        scores = [r["habit_score"] for r in response.json()["clients"]]
        assert scores == sorted(scores, reverse=True)

    def test_sort_by_verified_wakes_asc(self, client, coach_headers, big_roster):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={
                "sort_by": "verified_wakes",
                "sort_order": "asc",
                "per_page": 100,
            },
        )
        wakes = [r["verified_wakes"] for r in response.json()["clients"]]
        assert wakes == sorted(wakes)

    def test_status_filter_needs_attention(self, client, coach_headers, roster):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"status": "needs_attention"},
        )
        assert response.status_code == 200
        assert all(r["needs_attention"] for r in response.json()["clients"])

    @pytest.fixture
    def mixed_roster(self, db_session, big_roster):
        """``bulk6`` clears every alert threshold; ``bulk0`` has no activity."""
        profile = (
            db_session.query(UserProfile)
            .filter(UserProfile.user_id == big_roster[6].id)
            .first()
        )
        profile.wake_up_consistency_score = 85.0
        db_session.commit()
        return big_roster

    def test_status_chips_partition_the_roster(
        self, client, coach_headers, mixed_roster
    ):
        def ids_for(status):
            response = client.get(
                "/api/v1/coach/clients",
                headers=coach_headers,
                params={"status": status, "per_page": 100},
            )
            assert response.status_code == 200
            return {r["client_id"] for r in response.json()["clients"]}

        every = ids_for("all")
        attention = ids_for("needs_attention")
        on_track = ids_for("on_track")
        inactive = ids_for("inactive")

        assert every == {user.id for user in mixed_roster}
        # "On track" and "needs attention" are complements, never overlapping.
        assert on_track == {mixed_roster[6].id}
        assert attention | on_track == every
        assert attention & on_track == set()
        # Only the client with no seeded wake or challenge rows is inactive.
        assert inactive == {mixed_roster[0].id}
        assert inactive <= attention

    def test_search_filter_and_sort_combine(
        self, client, coach_headers, mixed_roster
    ):
        response = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={
                "search": "bulk",
                "status": "needs_attention",
                "sort_by": "habit_score",
                "sort_order": "desc",
                "per_page": 100,
            },
        )
        assert response.status_code == 200
        body = response.json()
        ids = [r["client_id"] for r in body["clients"]]
        scores = [r["habit_score"] for r in body["clients"]]

        assert mixed_roster[6].id not in ids
        assert body["total"] == 6
        assert body["total_assigned"] == 7
        assert all(r["needs_attention"] for r in body["clients"])
        assert scores == sorted(scores, reverse=True)

    def test_filtered_results_paginate_on_the_filtered_set(
        self, client, coach_headers, mixed_roster
    ):
        first = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"status": "needs_attention", "per_page": 4, "page": 1},
        ).json()
        second = client.get(
            "/api/v1/coach/clients",
            headers=coach_headers,
            params={"status": "needs_attention", "per_page": 4, "page": 2},
        ).json()

        assert first["total"] == 6
        assert first["total_pages"] == 2
        assert len(first["clients"]) == 4
        assert len(second["clients"]) == 2
        assert mixed_roster[6].id not in [
            r["client_id"] for r in first["clients"] + second["clients"]
        ]

    def test_invalid_sort_and_status_rejected(self, client, coach_headers):
        assert (
            client.get(
                "/api/v1/coach/clients",
                headers=coach_headers,
                params={"sort_by": "; DROP TABLE users"},
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/coach/clients",
                headers=coach_headers,
                params={"status": "bogus"},
            ).status_code
            == 422
        )


# ── Admin assignment management ──────────────────────────────────────────


class TestAdminAssignmentManagement:
    """Admins create and revoke the assignments that scope coach access."""

    def test_create_assignment_grants_coach_access(
        self, client, db_session, admin_headers, coach_user
    ):
        target = make_user(db_session, username="fresh", email="fresh@example.com")

        before = client.get(
            "/api/v1/coach/clients", headers=headers_for(coach_user)
        )
        assert before.json()["clients"] == []

        created = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": coach_user.id, "client_id": target.id},
        )
        assert created.status_code == 201
        assert created.json()["client_id"] == target.id
        assert created.json()["is_active"] is True

        after = client.get(
            "/api/v1/coach/clients", headers=headers_for(coach_user)
        )
        assert [r["client_id"] for r in after.json()["clients"]] == [target.id]

    def test_delete_assignment_revokes_access_and_keeps_history(
        self, client, db_session, admin_headers, coach_user, roster
    ):
        target = roster["assigned_a"]
        response = client.delete(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            params={"coach_id": coach_user.id, "client_id": target.id},
        )
        assert response.status_code == 204

        detail = client.get(
            f"/api/v1/coach/clients/{target.id}", headers=headers_for(coach_user)
        )
        assert detail.status_code == 404

        row = (
            db_session.query(CoachAssignment)
            .filter(
                CoachAssignment.coach_id == coach_user.id,
                CoachAssignment.client_id == target.id,
            )
            .first()
        )
        assert row is not None
        assert row.is_active is False

    def test_reassign_reactivates_existing_row(
        self, client, db_session, admin_headers, coach_user, roster
    ):
        target = roster["assigned_a"]
        client.delete(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            params={"coach_id": coach_user.id, "client_id": target.id},
        )
        recreated = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": coach_user.id, "client_id": target.id},
        )
        assert recreated.status_code == 201
        assert recreated.json()["is_active"] is True

        rows = (
            db_session.query(CoachAssignment)
            .filter(
                CoachAssignment.coach_id == coach_user.id,
                CoachAssignment.client_id == target.id,
            )
            .all()
        )
        assert len(rows) == 1

    def test_delete_missing_assignment_returns_404(
        self, client, admin_headers, coach_user, roster
    ):
        response = client.delete(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            params={"coach_id": coach_user.id, "client_id": roster["outsider"].id},
        )
        assert response.status_code == 404

    def test_coach_must_hold_coach_role(
        self, client, db_session, admin_headers, test_user
    ):
        other = make_user(db_session, username="other", email="other@example.com")
        response = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": test_user.id, "client_id": other.id},
        )
        assert response.status_code == 400
        assert "wellness_coach" in response.json()["detail"]

    def test_client_must_hold_user_role(
        self, client, db_session, admin_headers, coach_user
    ):
        second_coach = make_user(
            db_session,
            username="coach3",
            email="coach3@example.com",
            role=UserRole.WELLNESS_COACH,
        )
        response = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": coach_user.id, "client_id": second_coach.id},
        )
        assert response.status_code == 400

    def test_self_assignment_rejected(self, client, admin_headers, coach_user):
        response = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": coach_user.id, "client_id": coach_user.id},
        )
        assert response.status_code == 400

    def test_missing_users_rejected(self, client, admin_headers, coach_user):
        response = client.post(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            json={"coach_id": coach_user.id, "client_id": 999999},
        )
        assert response.status_code == 400
        assert "Client not found" in response.json()["detail"]

    def test_list_assignments_is_paginated(self, client, admin_headers, roster):
        response = client.get(
            "/api/v1/admin/coach-assignments",
            headers=admin_headers,
            params={"per_page": 1, "page": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["total_pages"] == 2
        assert len(body["assignments"]) == 1
        assert body["assignments"][0]["coach_username"] == "coachuser"

    def test_deleting_a_user_purges_their_assignments(
        self, client, db_session, admin_headers, roster
    ):
        target = roster["assigned_a"]
        response = client.delete(
            f"/api/v1/users/{target.id}", headers=admin_headers
        )
        assert response.status_code == 204

        remaining = (
            db_session.query(CoachAssignment)
            .filter(CoachAssignment.client_id == target.id)
            .count()
        )
        assert remaining == 0
