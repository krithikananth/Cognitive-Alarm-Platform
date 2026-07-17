"""Tests for the dedicated Analytics Data Ingestion layer."""

from datetime import datetime, timezone

import pytest

from app.models.analytics_event import AnalyticsEvent
from app.models.alarm import AlarmChallengeLog
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.services.analytics_ingestion_service import (
    AnalyticsEventType,
    AnalyticsIngestionService,
)
from app.services.attempt_log_service import AttemptLogService


class TestAnalyticsIngestionService:
    def test_emit_and_list(self, db_session, test_user):
        row = AnalyticsIngestionService.emit(
            db_session,
            user_id=test_user.id,
            event_type="recommendation.viewed",
            event_data={"recommendation_id": "sleep-1"},
            entity_type="recommendation",
            source="client",
        )
        assert row.id is not None
        assert row.event_type == "recommendation.viewed"
        assert row.event_data["recommendation_id"] == "sleep-1"

        listed = AnalyticsIngestionService.list_events(
            db_session, user_id=test_user.id
        )
        assert listed["total"] == 1
        assert listed["events"][0].id == row.id

    def test_sanitize_and_normalize(self, db_session, test_user):
        row = AnalyticsIngestionService.emit(
            db_session,
            user_id=test_user.id,
            event_type="  Alarm.Triggered ",
            event_data={"nested": {"ok": True}, "ts": datetime(2026, 7, 16, tzinfo=timezone.utc)},
            source="weird",
        )
        assert row.event_type == "alarm.triggered"
        assert row.source == "server"
        assert row.event_data["ts"].startswith("2026-07-16")

    def test_client_event_prefix_guard(self, db_session, test_user):
        with pytest.raises(ValueError, match="Unsupported"):
            AnalyticsIngestionService.ingest_many(
                db_session,
                user_id=test_user.id,
                events=[{"event_type": "admin.secrets.dump", "event_data": {}}],
                source="client",
            )

    def test_summary_counts(self, db_session, test_user):
        for _ in range(2):
            AnalyticsIngestionService.emit(
                db_session,
                user_id=test_user.id,
                event_type=AnalyticsEventType.ALARM_TRIGGERED,
                commit=True,
            )
        AnalyticsIngestionService.emit(
            db_session,
            user_id=test_user.id,
            event_type=AnalyticsEventType.RECOMMENDATION_VIEWED,
            commit=True,
        )
        summary = AnalyticsIngestionService.summarize(
            db_session, user_id=test_user.id
        )
        assert summary["total_events"] == 3
        by_type = {item["event_type"]: item["count"] for item in summary["by_event_type"]}
        assert by_type[AnalyticsEventType.ALARM_TRIGGERED] == 2
        assert by_type[AnalyticsEventType.RECOMMENDATION_VIEWED] == 1


class TestAnalyticsApi:
    def test_ingest_single_and_list(self, client, auth_headers):
        resp = client.post(
            "/api/v1/analytics/events",
            headers=auth_headers,
            json={
                "event_type": "ui.analytics_opened",
                "event_data": {"page": "Analytics"},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["accepted"] == 1
        assert body["events"][0]["source"] == "client"
        assert body["events"][0]["event_type"] == "ui.analytics_opened"

        listed = client.get("/api/v1/analytics/events", headers=auth_headers)
        assert listed.status_code == 200
        assert listed.json()["total"] >= 1

        summary = client.get("/api/v1/analytics/summary", headers=auth_headers)
        assert summary.status_code == 200
        assert summary.json()["total_events"] >= 1

    def test_ingest_batch(self, client, auth_headers):
        resp = client.post(
            "/api/v1/analytics/events/batch",
            headers=auth_headers,
            json={
                "events": [
                    {"event_type": "alarm.triggered", "entity_type": "alarm", "entity_id": 1},
                    {"event_type": "recommendation.acted", "event_data": {"id": "r1"}},
                ]
            },
        )
        assert resp.status_code == 201
        assert resp.json()["accepted"] == 2

    def test_rejects_disallowed_client_event(self, client, auth_headers):
        resp = client.post(
            "/api/v1/analytics/events",
            headers=auth_headers,
            json={"event_type": "system.internal"},
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/v1/analytics/events",
            json={"event_type": "ui.click"},
        )
        assert resp.status_code in (401, 403)


class TestAlarmFlowStillWritesDomainLogs:
    """Existing logging must continue; analytics is additive."""

    def test_record_attempt_writes_challenge_log_and_analytics(
        self, db_session, test_user
    ):
        from app.models.alarm import Alarm, AlarmType, ChallengeType

        alarm = Alarm(
            user_id=test_user.id,
            title="Morning",
            alarm_time=datetime.now(timezone.utc).time().replace(microsecond=0),
            alarm_type=AlarmType.ONE_TIME,
            challenge_type=ChallengeType.MATH,
            challenge_count=1,
            challenge_difficulty="medium",
            snooze_limit=3,
            snooze_interval_minutes=5,
            is_active=True,
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        log = AttemptLogService.record_attempt(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="math",
            difficulty="medium",
            challenge_prompt="2+2?",
            is_correct=True,
            time_taken_seconds=4,
            points_earned=10,
        )
        assert db_session.query(AlarmChallengeLog).count() == 1
        assert log.id is not None

        events = (
            db_session.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == test_user.id,
                AnalyticsEvent.event_type == AnalyticsEventType.CHALLENGE_ATTEMPTED,
            )
            .all()
        )
        assert len(events) == 1
        assert events[0].event_data["challenge_log_id"] == log.id

    def test_record_snooze_writes_snooze_and_analytics(
        self, db_session, test_user
    ):
        from app.models.alarm import Alarm, AlarmType, ChallengeType

        alarm = Alarm(
            user_id=test_user.id,
            title="Morning",
            alarm_time=datetime.now(timezone.utc).time().replace(microsecond=0),
            alarm_type=AlarmType.ONE_TIME,
            challenge_type=ChallengeType.MATH,
            challenge_count=1,
            challenge_difficulty="medium",
            snooze_limit=3,
            snooze_interval_minutes=5,
            is_active=True,
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        snooze = AttemptLogService.record_snooze(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            snooze_number=1,
            snooze_limit_at_event=3,
        )
        assert db_session.query(AlarmSnoozeEvent).count() == 1
        assert snooze.id is not None

        events = (
            db_session.query(AnalyticsEvent)
            .filter(
                AnalyticsEvent.user_id == test_user.id,
                AnalyticsEvent.event_type == AnalyticsEventType.ALARM_SNOOZED,
            )
            .all()
        )
        assert len(events) == 1
        assert events[0].event_data["snooze_event_id"] == snooze.id
