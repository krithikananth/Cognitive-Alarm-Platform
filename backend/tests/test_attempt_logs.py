"""
Tests for Week-2 attempt-log solidity.

Covers:
- Normalization helpers (type / difficulty / non-negative ints)
- Single write path (``AttemptLogService.record_attempt``)
- Audit report (clean vs dirty rows, queryability)
- Repair / backfill of legacy dirty rows
- Verify endpoint always produces clean, queryable logs
- ``GET /alarms/challenge/log-health`` endpoint
"""

from datetime import datetime, timezone

import pytest

from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.services.attempt_log_service import (
    AttemptLogService,
    VALID_CHALLENGE_TYPES,
)
from app.services.challenge_service import DIFFICULTY_LEVELS


def _make_alarm(db_session, user_id: int) -> Alarm:
    alarm = Alarm(
        user_id=user_id,
        title="Log Audit Alarm",
        alarm_time=datetime.now(timezone.utc).time().replace(microsecond=0),
        alarm_type=AlarmType.DAILY,
        challenge_type=ChallengeType.MATH,
        challenge_count=1,
        challenge_difficulty="medium",
    )
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)
    return alarm


def _session_answer(db_session, user_id: int, alarm_id: int) -> str:
    from app.models.challenge_session import ChallengeSession

    row = (
        db_session.query(ChallengeSession)
        .filter(
            ChallengeSession.user_id == user_id,
            ChallengeSession.alarm_id == alarm_id,
        )
        .first()
    )
    assert row is not None and row.answer
    return row.answer


class TestAttemptLogNormalization:
    def test_normalize_challenge_type_aliases(self):
        assert AttemptLogService.normalize_challenge_type("word") == "word_game"
        assert AttemptLogService.normalize_challenge_type("WORD") == "word_game"
        assert AttemptLogService.normalize_challenge_type("MATH") == "math"
        assert AttemptLogService.normalize_challenge_type(None) == "math"
        assert AttemptLogService.normalize_challenge_type("bogus") == "math"

    def test_normalize_difficulty(self):
        assert AttemptLogService.normalize_difficulty("hard") == "hard"
        assert AttemptLogService.normalize_difficulty(None) == "medium"
        assert AttemptLogService.normalize_difficulty("nope") == "medium"
        for level in DIFFICULTY_LEVELS:
            assert AttemptLogService.normalize_difficulty(level) == level

    def test_normalize_non_negative(self):
        assert AttemptLogService.normalize_non_negative(-5) == 0
        assert AttemptLogService.normalize_non_negative(None) == 0
        assert AttemptLogService.normalize_non_negative("12") == 12
        assert AttemptLogService.normalize_non_negative("x") == 0


class TestAttemptLogWritePath:
    def test_record_attempt_normalizes_and_persists(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        log = AttemptLogService.record_attempt(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="word",
            difficulty="HARD",
            challenge_prompt=" Spell this ",
            is_correct=True,
            time_taken_seconds=-3,
            failed_attempts=-1,
            points_earned=-9,
        )
        assert log.id is not None
        assert log.challenge_type == "word_game"
        assert log.difficulty == "hard"
        assert log.challenge_prompt == "Spell this"
        assert log.time_taken_seconds == 0
        assert log.failed_attempts == 0
        assert log.points_earned == 0
        assert log.created_at is not None

    def test_record_incorrect_attempt(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        log = AttemptLogService.record_attempt(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="math",
            difficulty="easy",
            challenge_prompt="2+2?",
            is_correct=False,
            time_taken_seconds=4,
        )
        assert log.is_correct is False
        assert (
            db_session.query(AlarmChallengeLog)
            .filter_by(alarm_id=alarm.id, is_correct=False)
            .count()
            == 1
        )


class TestAttemptLogAuditAndRepair:
    def test_audit_clean_logs(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        AttemptLogService.record_attempt(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="math",
            difficulty="medium",
            challenge_prompt="1+1",
            is_correct=True,
            time_taken_seconds=5,
            points_earned=10,
        )
        AttemptLogService.record_attempt(
            db_session,
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="logic",
            difficulty="easy",
            challenge_prompt="?",
            is_correct=False,
            time_taken_seconds=3,
        )
        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is True
        assert report["queryable"] is True
        assert report["total_attempts"] == 2
        assert report["correct_attempts"] == 1
        assert report["incorrect_attempts"] == 1
        assert report["issue_count"] == 0

    def test_audit_detects_dirty_rows_and_repair_fixes(
        self, db_session, test_user
    ):
        alarm = _make_alarm(db_session, test_user.id)
        # Simulate legacy / corrupt rows still allowed by SQLite storage
        dirty = AlarmChallengeLog(
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="word",  # alias — invalid until normalized
            difficulty="",  # missing
            challenge_prompt="",
            is_correct=True,
            time_taken_seconds=-2,
            failed_attempts=-1,
            points_earned=-4,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(dirty)
        db_session.commit()

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is False
        assert report["issue_count"] > 0
        assert any(
            code in report["issue_counts"]
            for code in (
                "missing_difficulty",
                "invalid_challenge_type",
                "invalid_time_taken",
            )
        )

        repaired = AttemptLogService.repair_logs(
            db_session, user_id=test_user.id, commit=True
        )
        assert repaired["repaired_rows"] >= 1

        clean = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert clean["is_clean"] is True
        assert clean["issue_count"] == 0

        row = db_session.query(AlarmChallengeLog).filter_by(id=dirty.id).one()
        assert row.challenge_type == "word_game"
        assert row.difficulty == "medium"
        assert row.time_taken_seconds == 0
        assert row.failed_attempts == 0
        assert row.points_earned == 0

    def test_audit_detects_orphan_alarm(self, db_session, test_user):
        # Insert a log pointing at a non-existent alarm_id
        orphan = AlarmChallengeLog(
            alarm_id=999999,
            user_id=test_user.id,
            challenge_type="math",
            difficulty="medium",
            challenge_prompt="x",
            is_correct=False,
            time_taken_seconds=1,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(orphan)
        db_session.commit()

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is False
        assert report["issue_counts"].get("orphan_alarm_id", 0) >= 1


class TestVerifyProducesCleanLogs:
    def _create_alarm(self, client, auth_headers, **overrides):
        data = {
            "title": "Verify Log Alarm",
            "alarm_time": "07:00",
            "challenge_type": "math",
            "challenge_count": 1,
            **overrides,
        }
        res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
        assert res.status_code == 201
        return res.json()["id"]

    def test_verify_correct_and_incorrect_are_clean_and_queryable(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = self._create_alarm(client, auth_headers)

        # Incorrect attempt must still be logged
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": "definitely_wrong", "time_taken_seconds": 2},
            headers=auth_headers,
        )

        # Correct attempt
        ch = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        ).json()
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": answer,
                "time_taken_seconds": 6,
                "challenge_prompt": ch["prompt"],
                "challenge_difficulty": ch["difficulty"],
                "failed_attempts": -5,  # client junk must be clamped
            },
            headers=auth_headers,
        )

        logs = (
            db_session.query(AlarmChallengeLog)
            .filter_by(user_id=test_user.id)
            .order_by(AlarmChallengeLog.created_at.desc())
            .all()
        )
        assert len(logs) >= 2
        assert any(not log.is_correct for log in logs)
        assert any(log.is_correct for log in logs)

        for log in logs:
            assert log.challenge_type in VALID_CHALLENGE_TYPES
            assert log.difficulty in DIFFICULTY_LEVELS
            assert log.challenge_prompt is not None
            assert log.time_taken_seconds >= 0
            assert log.failed_attempts >= 0
            assert log.points_earned >= 0
            assert log.created_at is not None

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is True
        assert report["queryable"] is True

        # History / stats endpoints must return the logged attempts
        history = client.get(
            "/api/v1/alarms/challenge/history", headers=auth_headers
        )
        assert history.status_code == 200
        assert history.json()["total"] >= 2

        stats = client.get(
            "/api/v1/alarms/challenge/stats", headers=auth_headers
        )
        assert stats.status_code == 200
        assert stats.json()["total_attempts"] >= 2

    def test_log_health_endpoint(self, client, test_user, auth_headers, db_session):
        alarm_id = self._create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 4},
            headers=auth_headers,
        )

        res = client.get(
            "/api/v1/alarms/challenge/log-health", headers=auth_headers
        )
        assert res.status_code == 200
        data = res.json()
        assert data["queryable"] is True
        assert data["is_clean"] is True
        assert data["total_attempts"] >= 1
        assert "valid_challenge_types" in data
        assert "valid_difficulties" in data

    def test_log_health_repair_flag(
        self, client, test_user, auth_headers, db_session
    ):
        alarm = _make_alarm(db_session, test_user.id)
        dirty = AlarmChallengeLog(
            alarm_id=alarm.id,
            user_id=test_user.id,
            challenge_type="word",
            difficulty="",
            challenge_prompt="",
            is_correct=False,
            time_taken_seconds=-1,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(dirty)
        db_session.commit()

        res = client.get(
            "/api/v1/alarms/challenge/log-health?repair=true",
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["repaired"] is True
        assert data["is_clean"] is True


class TestSnoozeLogging:
    def _create_alarm(self, client, auth_headers, **overrides):
        data = {
            "title": "Snooze Log Alarm",
            "alarm_time": "07:00",
            "challenge_type": "math",
            "challenge_count": 1,
            "snooze_limit": 3,
            **overrides,
        }
        res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
        assert res.status_code == 201
        return res.json()["id"]

    def test_snooze_creates_audit_event(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = self._create_alarm(client, auth_headers)
        res = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert res.status_code == 200
        assert res.json()["total_snoozes"] == 1

        events = (
            db_session.query(AlarmSnoozeEvent)
            .filter_by(user_id=test_user.id, alarm_id=alarm_id)
            .all()
        )
        assert len(events) == 1
        assert events[0].snooze_number == 1
        assert events[0].snooze_limit_at_event == 3
        assert events[0].next_trigger_at is not None

        history = client.get(
            "/api/v1/alarms/snooze-history", headers=auth_headers
        )
        assert history.status_code == 200
        body = history.json()
        assert body["total"] >= 1
        assert body["events"][0]["snooze_number"] == 1

        health = client.get(
            "/api/v1/alarms/challenge/log-health", headers=auth_headers
        )
        assert health.status_code == 200
        assert health.json()["total_snoozes"] >= 1
        assert health.json()["is_clean"] is True

    def test_multiple_snoozes_increment_number(
        self, client, test_user, auth_headers, db_session
    ):
        alarm_id = self._create_alarm(client, auth_headers)
        client.post(f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers)
        client.post(f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers)
        numbers = sorted(
            e.snooze_number
            for e in db_session.query(AlarmSnoozeEvent)
            .filter_by(alarm_id=alarm_id)
            .all()
        )
        assert numbers == [1, 2]


class TestDuplicateAndInconsistencyAudit:
    def test_detects_duplicate_attempts(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)
        for _ in range(2):
            db_session.add(
                AlarmChallengeLog(
                    alarm_id=alarm.id,
                    user_id=test_user.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt="same prompt",
                    is_correct=False,
                    time_taken_seconds=3,
                    created_at=now,
                )
            )
        db_session.commit()

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is False
        assert report["issue_counts"].get("duplicate_attempt", 0) >= 1

    def test_detects_duplicate_snoozes(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)
        for _ in range(2):
            db_session.add(
                AlarmSnoozeEvent(
                    alarm_id=alarm.id,
                    user_id=test_user.id,
                    snooze_number=1,
                    snooze_limit_at_event=3,
                    created_at=now,
                )
            )
        db_session.commit()

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is False
        assert report["issue_counts"].get("duplicate_snooze", 0) >= 1

    def test_detects_owner_mismatch(self, db_session, test_user, admin_user):
        # Alarm owned by admin, log attributed to test_user
        alarm = Alarm(
            user_id=admin_user.id,
            title="Other Owner",
            alarm_time=datetime.now(timezone.utc).time().replace(microsecond=0),
            alarm_type=AlarmType.DAILY,
            challenge_type=ChallengeType.MATH,
            challenge_count=1,
            challenge_difficulty="medium",
        )
        db_session.add(alarm)
        db_session.commit()
        db_session.refresh(alarm)

        db_session.add(
            AlarmChallengeLog(
                alarm_id=alarm.id,
                user_id=test_user.id,
                challenge_type="math",
                difficulty="medium",
                challenge_prompt="x",
                is_correct=True,
                time_taken_seconds=1,
                created_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()

        report = AttemptLogService.audit_logs(db_session, user_id=test_user.id)
        assert report["is_clean"] is False
        assert report["issue_counts"].get("inconsistent_user_alarm_owner", 0) >= 1

    def test_repair_does_not_delete_duplicates(self, db_session, test_user):
        alarm = _make_alarm(db_session, test_user.id)
        now = datetime.now(timezone.utc)
        for _ in range(2):
            db_session.add(
                AlarmChallengeLog(
                    alarm_id=alarm.id,
                    user_id=test_user.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt="dup",
                    is_correct=True,
                    time_taken_seconds=1,
                    created_at=now,
                )
            )
        db_session.commit()
        before = db_session.query(AlarmChallengeLog).count()
        AttemptLogService.repair_logs(db_session, user_id=test_user.id, commit=True)
        after = db_session.query(AlarmChallengeLog).count()
        assert after == before
