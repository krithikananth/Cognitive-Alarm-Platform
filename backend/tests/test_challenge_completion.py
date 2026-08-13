"""
Challenge completion rate — served vs finished.

Completion rate is not accuracy. Accuracy only sees submitted answers, so a
challenge the user walked away from or let expire is invisible to it. These
tests exercise the whole lifecycle through the real API:

    served -> completed | timed_out | abandoned

and pin the rate that falls out of it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.challenge_delivery import (
    OUTCOME_ABANDONED,
    OUTCOME_COMPLETED,
    OUTCOME_PENDING,
    OUTCOME_TIMED_OUT,
    ChallengeDelivery,
)
from app.models.challenge_session import ChallengeSession
from app.services.challenge_delivery_service import ChallengeDeliveryService
from app.services.challenge_service import VERIFY_TIME_GRACE_SECONDS
from app.services.dashboard_aggregations import compute_challenge_performance


def _create_alarm(client, auth_headers, **overrides):
    data = {
        "title": "Completion Alarm",
        "alarm_time": "07:00",
        "challenge_type": "math",
        "challenge_count": 1,
        **overrides,
    }
    res = client.post("/api/v1/alarms/", json=data, headers=auth_headers)
    assert res.status_code == 201
    return res.json()["id"]


def _session_answer(db_session, user_id, alarm_id):
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


def _deliveries(db_session, user_id):
    return (
        db_session.query(ChallengeDelivery)
        .filter(ChallengeDelivery.user_id == user_id)
        .order_by(ChallengeDelivery.id)
        .all()
    )


def _age_open_delivery(db_session, user_id, seconds):
    """Push the open delivery back in time so its deadline has passed."""
    delivery = (
        db_session.query(ChallengeDelivery)
        .filter(
            ChallengeDelivery.user_id == user_id,
            ChallengeDelivery.outcome == OUTCOME_PENDING,
        )
        .order_by(ChallengeDelivery.id.desc())
        .first()
    )
    assert delivery is not None
    delivery.issued_at = delivery.issued_at - timedelta(seconds=seconds)
    session = (
        db_session.query(ChallengeSession)
        .filter(
            ChallengeSession.user_id == user_id,
            ChallengeSession.alarm_id == delivery.alarm_id,
        )
        .first()
    )
    if session is not None:
        session.issued_at = session.issued_at - timedelta(seconds=seconds)
    db_session.commit()
    return delivery


class TestDeliveryLifecycle:
    """Every served challenge lands in challenge_deliveries and gets settled."""

    def test_serving_a_challenge_records_a_pending_delivery(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        res = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        assert res.status_code == 200

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].outcome == OUTCOME_PENDING
        assert rows[0].alarm_id == alarm_id
        assert rows[0].resolved_at is None
        assert rows[0].is_correct is None
        assert rows[0].time_limit_seconds > 0

    def test_answering_in_time_marks_the_delivery_completed(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 3},
            headers=auth_headers,
        )
        assert res.status_code == 200

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].outcome == OUTCOME_COMPLETED
        assert rows[0].is_correct is True
        assert rows[0].resolved_at is not None

    def test_a_wrong_but_timely_answer_is_still_a_completion(
        self, client, db_session, test_user, auth_headers
    ):
        """Completion measures finishing, not being right — that is accuracy."""
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": "definitely-wrong", "time_taken_seconds": 2},
            headers=auth_headers,
        )
        assert res.status_code == 400

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].outcome == OUTCOME_COMPLETED
        assert rows[0].is_correct is False

    def test_answering_past_the_limit_marks_the_delivery_timed_out(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        delivery = _age_open_delivery(
            db_session, test_user.id, seconds=600 + VERIFY_TIME_GRACE_SECONDS
        )

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 0},
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert "Time's up" in res.json()["detail"]

        db_session.refresh(delivery)
        assert delivery.outcome == OUTCOME_TIMED_OUT
        # A timed-out delivery carries no correctness verdict
        assert delivery.is_correct is None

    def test_requesting_a_new_challenge_abandons_the_unanswered_one(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 2
        assert rows[0].outcome == OUTCOME_ABANDONED
        assert rows[0].resolved_at is not None
        assert rows[1].outcome == OUTCOME_PENDING

    def test_an_expired_unanswered_challenge_is_a_timeout_not_an_abandon(
        self, client, db_session, test_user, auth_headers
    ):
        """The user did not walk away early — the clock ran out on them."""
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        first = _age_open_delivery(
            db_session, test_user.id, seconds=600 + VERIFY_TIME_GRACE_SECONDS
        )

        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        db_session.refresh(first)
        assert first.outcome == OUTCOME_TIMED_OUT

    def test_snoozing_abandons_the_open_challenge(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers, snooze_limit=3)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/snooze", headers=auth_headers
        )
        assert res.status_code == 200

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].outcome == OUTCOME_ABANDONED

    def test_failing_the_wake_abandons_the_open_challenge(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        res = client.post(
            f"/api/v1/alarms/{alarm_id}/fail-wake", headers=auth_headers
        )
        assert res.status_code == 200

        rows = _deliveries(db_session, test_user.id)
        assert len(rows) == 1
        assert rows[0].outcome == OUTCOME_ABANDONED

    def test_deleting_an_alarm_removes_its_deliveries(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        assert _deliveries(db_session, test_user.id)

        assert (
            client.delete(
                f"/api/v1/alarms/{alarm_id}", headers=auth_headers
            ).status_code
            == 204
        )
        assert _deliveries(db_session, test_user.id) == []


class TestCompletionStats:
    """compute_completion_stats over hand-placed deliveries."""

    def _seed(self, db_session, user_id, alarm_id, outcomes, *, issued_at=None):
        base = issued_at or datetime.now(timezone.utc).replace(tzinfo=None)
        for i, outcome in enumerate(outcomes):
            db_session.add(
                ChallengeDelivery(
                    user_id=user_id,
                    alarm_id=alarm_id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt="2 + 2",
                    time_limit_seconds=30,
                    issued_at=base - timedelta(minutes=i),
                    resolved_at=None if outcome == OUTCOME_PENDING else base,
                    outcome=outcome,
                    is_correct=True if outcome == OUTCOME_COMPLETED else None,
                )
            )
        db_session.commit()

    def test_rate_counts_completed_over_every_settled_delivery(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        self._seed(
            db_session,
            test_user.id,
            alarm_id,
            [OUTCOME_COMPLETED] * 6 + [OUTCOME_TIMED_OUT] * 2 + [OUTCOME_ABANDONED] * 2,
        )

        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["served"] == 10
        assert stats["completed"] == 6
        assert stats["timed_out"] == 2
        assert stats["abandoned"] == 2
        assert stats["completion_rate"] == 60.0
        assert stats["timeout_rate"] == 20.0
        assert stats["abandonment_rate"] == 20.0
        assert stats["status"] == "ok"

    def test_a_challenge_still_on_screen_is_excluded_from_the_rate(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        # Pending row first so it keeps the freshest issued_at and is still
        # inside its 30s limit.
        self._seed(
            db_session,
            test_user.id,
            alarm_id,
            [OUTCOME_PENDING, OUTCOME_COMPLETED, OUTCOME_COMPLETED],
        )

        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["in_flight"] == 1
        assert stats["served"] == 2
        assert stats["completion_rate"] == 100.0

    def test_a_stale_pending_delivery_reads_as_a_timeout(
        self, client, db_session, test_user, auth_headers
    ):
        """A session that died mid-challenge must not inflate the rate."""
        alarm_id = _create_alarm(client, auth_headers)
        self._seed(
            db_session,
            test_user.id,
            alarm_id,
            [OUTCOME_COMPLETED, OUTCOME_PENDING],
            issued_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=2),
        )

        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["in_flight"] == 0
        assert stats["served"] == 2
        assert stats["timed_out"] == 1
        assert stats["completion_rate"] == 50.0

    def test_deliveries_outside_the_window_are_ignored(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self._seed(db_session, test_user.id, alarm_id, [OUTCOME_COMPLETED])
        self._seed(
            db_session,
            test_user.id,
            alarm_id,
            [OUTCOME_ABANDONED],
            issued_at=now - timedelta(days=60),
        )

        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["served"] == 1
        assert stats["completion_rate"] == 100.0

    def test_no_history_reports_no_data_rather_than_a_perfect_score(
        self, db_session, test_user
    ):
        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["status"] == "no_data"
        assert stats["served"] == 0
        assert stats["completion_rate"] == 0.0

    def test_stats_are_scoped_to_the_user(
        self, client, db_session, test_user, admin_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        self._seed(db_session, test_user.id, alarm_id, [OUTCOME_COMPLETED])
        self._seed(
            db_session, admin_user.id, alarm_id, [OUTCOME_ABANDONED] * 5
        )

        stats = ChallengeDeliveryService.compute_completion_stats(
            db_session, test_user.id, days=30
        )
        assert stats["served"] == 1
        assert stats["completion_rate"] == 100.0


class TestCompletionRateIsNotAccuracy:
    """The whole point: the two metrics must be able to disagree."""

    def test_all_correct_answers_can_still_be_a_low_completion_rate(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)

        # Three challenges served and walked away from
        for _ in range(3):
            client.get(
                f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
            )
        # A fourth served and answered correctly
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 2},
            headers=auth_headers,
        )

        perf = compute_challenge_performance(db_session, test_user.id, days=30)
        assert perf["total_attempts"] == 1
        assert perf["accuracy"] == 100.0
        assert perf["completion"]["served"] == 4
        assert perf["completion"]["completed"] == 1
        assert perf["completion"]["abandoned"] == 3
        assert perf["completion"]["completion_rate"] == 25.0

    def test_challenge_performance_endpoint_exposes_completion(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        res = client.get(
            "/api/v1/dashboard/challenge-performance?days=30",
            headers=auth_headers,
        )
        assert res.status_code == 200
        completion = res.json()["completion"]
        assert completion["served"] == 1
        assert completion["abandoned"] == 1
        assert completion["completion_rate"] == 0.0

    def test_completion_block_is_present_even_with_zero_attempts(
        self, client, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)

        body = client.get(
            "/api/v1/dashboard/challenge-performance?days=30",
            headers=auth_headers,
        ).json()
        assert body["total_attempts"] == 0
        assert body["completion"]["status"] == "no_data"
        assert body["completion"]["in_flight"] == 1

    def test_challenge_analysis_no_longer_mirrors_accuracy(
        self, client, db_session, test_user, auth_headers
    ):
        alarm_id = _create_alarm(client, auth_headers)
        # One abandoned, one answered correctly -> accuracy 100, completion 50
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        answer = _session_answer(db_session, test_user.id, alarm_id)
        client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": answer, "time_taken_seconds": 2},
            headers=auth_headers,
        )

        summary = client.get(
            "/api/v1/alarms/challenge/analysis", headers=auth_headers
        ).json()["summary"]
        assert summary["accuracy_percentage"] == 100.0
        assert summary["completion_rate"] == 50.0
        assert summary["completion"]["abandoned"] == 1
        assert summary["completion"]["completed"] == 1
