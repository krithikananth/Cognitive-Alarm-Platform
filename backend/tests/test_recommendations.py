"""
Tests for the sleep / wake / productivity Recommendation Engine.
"""

from datetime import datetime, time, timedelta, timezone

from app.models.alarm import Alarm, AlarmType, ChallengeType, AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.profile import UserProfile
from app.schemas.recommendation import RecommendationCategory
from app.services.recommendation_service import RecommendationService


def _ensure_profile(db_session, user, **kwargs) -> UserProfile:
    profile = db_session.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if profile is None:
        profile = UserProfile(user_id=user.id, sleep_duration_hours=8.0, timezone="UTC")
        db_session.add(profile)
        db_session.commit()
        db_session.refresh(profile)
    for key, value in kwargs.items():
        setattr(profile, key, value)
    db_session.commit()
    db_session.refresh(profile)
    return profile


class TestRecommendationServiceUnit:
    """Unit tests for RecommendationService helpers and generation."""

    def test_bedtime_computation(self):
        bed = RecommendationService._compute_bedtime(time(7, 0), 8.0)
        assert bed == time(23, 0)

    def test_normalize_goals_from_list_and_string(self):
        assert RecommendationService._normalize_goals([" Exercise ", "Study"]) == [
            "Exercise",
            "Study",
        ]
        assert RecommendationService._normalize_goals("Read, Write") == ["Read", "Write"]
        assert RecommendationService._normalize_goals(None) == []

    def test_format_goals_list_capitalizes_and_joins(self):
        assert RecommendationService._format_goal_label("exercise daily") == (
            "Exercise daily"
        )
        assert RecommendationService._format_goals_list(
            ["exercise daily", "study algorithms", "read more"]
        ) == "Exercise daily, Study algorithms, Read more"
        assert RecommendationService._format_goals_list(
            ["a", "b", "c", "d", "e", "f"], limit=5
        ) == "A, B, C, D, E, …"

    def test_match_goal_template(self):
        matched = RecommendationService._match_goal_template("Morning exercise routine")
        assert matched is not None
        assert matched["key"] == "exercise"

    def test_generate_for_new_user(self, db_session, test_user):
        _ensure_profile(db_session, test_user)
        # Reload user with profile relationship
        db_session.refresh(test_user)
        result = RecommendationService.generate_recommendations(test_user, db_session)

        assert result.summary.goals_count == 0
        assert result.summary.suggested_bedtime is None
        ids = {r.id for r in result.recommendations}
        assert "sleep-set-wake-goal" in ids
        assert "productivity-set-goals" in ids
        assert "wake-getting-started" in ids
        assert result.daily_plan.morning_focus

    def test_sleep_and_productivity_personalization(self, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(6, 30),
            sleep_duration_hours=6.0,
            productivity_goals=["Study algorithms", "Morning exercise"],
            wake_up_consistency_score=55.0,
            streak_days=4,
            best_streak=10,
            total_alarms_dismissed=10,
            total_snoozes=2,
        )
        alarm = Alarm(
            user_id=test_user.id,
            title="Weekday",
            alarm_time=time(8, 0),
            alarm_type=AlarmType.DAILY,
            is_active=True,
            challenge_type=ChallengeType.MATH,
        )
        db_session.add(alarm)
        db_session.commit()

        result = RecommendationService.generate_recommendations(test_user, db_session)
        ids = {r.id for r in result.recommendations}

        assert result.summary.preferred_wake_time == "06:30"
        # 06:30 wake − 6h target → 00:30 bedtime
        assert result.summary.suggested_bedtime == "00:30"
        assert result.summary.goals_count == 2
        assert "sleep-extend-duration" in ids
        assert "sleep-align-alarm" in ids
        assert "productivity-goal-study" in ids or "productivity-goal-exercise" in ids
        assert any(r.category == RecommendationCategory.PRODUCTIVITY for r in result.recommendations)

    def test_wake_coaching_from_snooze_events(self, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
            wake_up_consistency_score=30.0,
            streak_days=0,
            best_streak=5,
        )
        alarm = Alarm(
            user_id=test_user.id,
            title="Main",
            alarm_time=time(7, 0),
            alarm_type=AlarmType.DAILY,
            is_active=True,
            challenge_type=ChallengeType.MATH,
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        now = datetime.now(timezone.utc)
        # Place successes several days ago so missed-day decay leaves streak at 0
        # while still providing snooze-heavy wake history for coaching signals.
        old = now - timedelta(days=5)
        for i in range(4):
            db_session.add(
                AlarmWakeEvent(
                    user_id=test_user.id,
                    alarm_id=alarm.id,
                    triggered_at=old,
                    dismissed_at=old,
                    dismiss_method="snooze_exhausted" if i < 3 else "challenge",
                    snooze_count_at_dismiss=3 if i < 3 else 0,
                    time_to_dismiss_seconds=240,
                    wakefulness_score=35.0,
                    wakefulness_level="groggy",
                    verified=True,
                )
            )
        db_session.commit()

        result = RecommendationService.generate_recommendations(test_user, db_session)
        ids = {r.id for r in result.recommendations}
        assert "wake-reduce-snooze" in ids or "wake-anti-snooze-harder" in ids
        assert "wake-build-consistency" in ids
        assert "wake-restart-streak" in ids
        assert result.summary.snooze_rate is not None
        assert result.summary.snooze_rate >= 50

    def test_category_filter_and_daily_digest(self, db_session, test_user):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(7, 0),
            productivity_goals=["Deep work"],
        )
        sleep_only = RecommendationService.generate_recommendations(
            test_user,
            db_session,
            categories=[RecommendationCategory.SLEEP],
        )
        assert all(
            r.category == RecommendationCategory.SLEEP
            for r in sleep_only.recommendations
        )

        digest = RecommendationService.generate_daily_digest(test_user, db_session)
        assert len(digest.recommendations) <= 5
        assert digest.daily_plan is not None

    def test_daily_digest_includes_productivity_when_goals_saved(
        self, db_session, test_user
    ):
        """Dashboard digest must surface goal-based productivity coaching."""
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(6, 30),
            sleep_duration_hours=6.0,
            productivity_goals=["Exercise", "Study Algorithms"],
            wake_up_consistency_score=25.0,
            streak_days=0,
            best_streak=8,
            total_alarms_dismissed=3,
            total_snoozes=8,
        )
        alarm = Alarm(
            user_id=test_user.id,
            title="Early",
            alarm_time=time(8, 30),
            alarm_type=AlarmType.DAILY,
            is_active=True,
            challenge_type=ChallengeType.MATH,
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        # Flood with high-priority wake signals so productivity would otherwise
        # fall outside the top-5 digest cut.
        now = datetime.now(timezone.utc)
        for i in range(5):
            db_session.add(
                AlarmWakeEvent(
                    user_id=test_user.id,
                    alarm_id=alarm.id,
                    triggered_at=now,
                    dismissed_at=now,
                    dismiss_method="snooze_exhausted",
                    snooze_count_at_dismiss=3,
                    time_to_dismiss_seconds=300,
                    wakefulness_score=30.0,
                    wakefulness_level="drowsy",
                    verified=True,
                )
            )
        db_session.commit()

        digest = RecommendationService.generate_daily_digest(test_user, db_session)
        assert len(digest.recommendations) <= 5
        assert digest.summary.goals_count == 2

        prod = [
            r
            for r in digest.recommendations
            if r.category == RecommendationCategory.PRODUCTIVITY
        ]
        assert len(prod) >= 1, "Daily digest must include productivity coaching when goals are saved"
        # Prefer personalized goal tips over the empty-state "set goals" card.
        assert all(r.id != "productivity-set-goals" for r in prod)
        assert any(
            r.id.startswith("productivity-goal-")
            or r.id
            in {
                "productivity-use-morning-window",
                "productivity-stabilize-first",
                "productivity-streak-leverage",
                "productivity-goals-active",
                "productivity-high-alertness",
            }
            for r in prod
        )


class TestRecommendationAPI:
    """Integration tests for /api/v1/recommendations endpoints."""

    def test_unauthorized(self, client):
        assert client.get("/api/v1/recommendations").status_code == 401
        assert client.get("/api/v1/recommendations/daily").status_code == 401

    def test_get_recommendations(self, client, test_user, auth_headers, db_session):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(6, 0),
            sleep_duration_hours=8.0,
            productivity_goals=["Exercise daily"],
        )
        response = client.get("/api/v1/recommendations", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "recommendations" in data
        assert "by_category" in data
        assert "daily_plan" in data
        assert "insights" in data
        assert data["summary"]["preferred_wake_time"] == "06:00"
        assert data["summary"]["suggested_bedtime"] == "22:00"
        assert data["summary"]["goals_count"] == 1
        assert len(data["recommendations"]) >= 1
        first = data["recommendations"][0]
        assert {"id", "category", "priority", "title", "detail"} <= set(first.keys())

    def test_daily_digest(self, client, test_user, auth_headers, db_session):
        _ensure_profile(db_session, test_user, preferred_wake_time=time(7, 0))
        response = client.get("/api/v1/recommendations/daily", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["recommendations"]) <= 5
        assert data["daily_plan"]["suggested_wake_time"] == "07:00"

    def test_daily_digest_includes_productivity_for_dashboard(
        self, client, test_user, auth_headers, db_session
    ):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=8.0,
            productivity_goals=["Exercise", "Study Algorithms"],
        )
        response = client.get("/api/v1/recommendations/daily", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["goals_count"] == 2
        categories = {r["category"] for r in data["recommendations"]}
        assert "productivity" in categories
        titles = " ".join(r["title"] + " " + r["detail"] for r in data["recommendations"])
        assert any(
            keyword in titles.lower()
            for keyword in ("exercise", "study", "goal", "focus", "morning")
        )

    def test_category_endpoints(self, client, test_user, auth_headers, db_session):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(7, 0),
            sleep_duration_hours=6.5,
            productivity_goals=["Study math"],
        )
        for path, category in [
            ("/api/v1/recommendations/sleep", "sleep"),
            ("/api/v1/recommendations/wake", "wake"),
            ("/api/v1/recommendations/productivity", "productivity"),
        ]:
            response = client.get(path, headers=auth_headers)
            assert response.status_code == 200, path
            data = response.json()
            assert data["category"] == category
            assert isinstance(data["recommendations"], list)

    def test_query_category_filter(self, client, test_user, auth_headers, db_session):
        _ensure_profile(
            db_session,
            test_user,
            preferred_wake_time=time(7, 0),
            productivity_goals=["Focus work"],
        )
        response = client.get(
            "/api/v1/recommendations",
            params=[("category", "productivity")],
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert all(r["category"] == "productivity" for r in data["recommendations"])

    def test_includes_challenge_recommendations(
        self, client, test_user, auth_headers, db_session
    ):
        _ensure_profile(db_session, test_user, preferred_wake_time=time(7, 0))
        alarm = Alarm(
            user_id=test_user.id,
            title="A",
            alarm_time=time(7, 0),
            alarm_type=AlarmType.DAILY,
            is_active=True,
            challenge_type=ChallengeType.MATH,
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        for i in range(6):
            db_session.add(
                AlarmChallengeLog(
                    user_id=test_user.id,
                    alarm_id=alarm.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt="1+1?",
                    is_correct=i < 2,
                    time_taken_seconds=35,
                    points_earned=10 if i < 2 else 0,
                )
            )
        db_session.commit()

        response = client.get(
            "/api/v1/recommendations",
            params=[("category", "challenge")],
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["recommendations"]) >= 1
        assert all(r["category"] == "challenge" for r in data["recommendations"])
