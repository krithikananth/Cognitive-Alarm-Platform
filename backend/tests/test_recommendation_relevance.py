"""
Recommendation relevance — measured from user feedback, not asserted.

The engine ships a hard-coded ``confidence`` on every card. These tests pin
that relevance is computed only from what users actually said, that dismissals
are kept out of the ratio, that the engine's claimed confidence is contrasted
against the measured figure, and that recording feedback does not change what
the engine recommends or in what order.
"""

import pytest

from app.models.recommendation_feedback import (
    RATING_DISMISSED,
    RATING_HELPFUL,
    RATING_NOT_HELPFUL,
    RecommendationFeedback,
)
from app.services.recommendation_relevance_service import (
    MIN_RELEVANCE_RESPONSES,
    RecommendationRelevanceService,
)


def _feed(client, auth_headers):
    res = client.get("/api/v1/recommendations", headers=auth_headers)
    assert res.status_code == 200
    return res.json()


def _first_ids(client, auth_headers, count=1):
    items = _feed(client, auth_headers)["recommendations"]
    assert len(items) >= count, "engine produced too few recommendations to test"
    return [i["id"] for i in items[:count]]


def _rate(client, auth_headers, rec_id, rating):
    return client.put(
        f"/api/v1/recommendations/{rec_id}/feedback",
        json={"rating": rating},
        headers=auth_headers,
    )


def _relevance(client, auth_headers, params=""):
    res = client.get(
        f"/api/v1/recommendations/relevance{params}", headers=auth_headers
    )
    assert res.status_code == 200
    return res.json()


class TestFeedbackEndpoint:
    def test_rating_a_real_recommendation_stores_the_engine_context(
        self, client, db_session, test_user, auth_headers
    ):
        item = _feed(client, auth_headers)["recommendations"][0]

        res = _rate(client, auth_headers, item["id"], RATING_HELPFUL)
        assert res.status_code == 200
        body = res.json()
        assert body["recommendation_id"] == item["id"]
        assert body["rating"] == RATING_HELPFUL
        # Category / priority / confidence come from the engine, not the client
        assert body["category"] == item["category"]
        assert body["priority"] == item["priority"]
        assert body["stated_confidence"] == pytest.approx(item["confidence"])

        row = (
            db_session.query(RecommendationFeedback)
            .filter(RecommendationFeedback.user_id == test_user.id)
            .one()
        )
        assert row.recommendation_id == item["id"]

    def test_rating_an_unknown_recommendation_is_rejected(
        self, client, db_session, test_user, auth_headers
    ):
        res = _rate(client, auth_headers, "not-a-real-recommendation", RATING_HELPFUL)
        assert res.status_code == 404
        assert (
            db_session.query(RecommendationFeedback)
            .filter(RecommendationFeedback.user_id == test_user.id)
            .count()
            == 0
        )

    def test_an_invalid_rating_is_rejected(self, client, auth_headers):
        rec_id = _first_ids(client, auth_headers)[0]
        assert _rate(client, auth_headers, rec_id, "amazing").status_code == 422

    def test_re_rating_updates_instead_of_stacking(
        self, client, db_session, test_user, auth_headers
    ):
        rec_id = _first_ids(client, auth_headers)[0]
        _rate(client, auth_headers, rec_id, RATING_HELPFUL)
        _rate(client, auth_headers, rec_id, RATING_NOT_HELPFUL)

        rows = (
            db_session.query(RecommendationFeedback)
            .filter(RecommendationFeedback.user_id == test_user.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].rating == RATING_NOT_HELPFUL

    def test_clearing_feedback_makes_the_card_unrated_again(
        self, client, auth_headers
    ):
        rec_id = _first_ids(client, auth_headers)[0]
        _rate(client, auth_headers, rec_id, RATING_HELPFUL)

        res = client.delete(
            f"/api/v1/recommendations/{rec_id}/feedback", headers=auth_headers
        )
        assert res.status_code == 204
        assert _relevance(client, auth_headers)["responses"] == 0

    def test_clearing_unrated_feedback_is_a_no_op(self, client, auth_headers):
        res = client.delete(
            "/api/v1/recommendations/never-rated/feedback", headers=auth_headers
        )
        assert res.status_code == 204

    def test_feedback_endpoints_require_authentication(self, client):
        assert (
            client.put(
                "/api/v1/recommendations/x/feedback", json={"rating": "helpful"}
            ).status_code
            == 401
        )
        assert client.get("/api/v1/recommendations/relevance").status_code == 401


class TestFeedAnnotation:
    def test_the_feed_reports_the_users_stored_verdict(
        self, client, auth_headers
    ):
        rec_id = _first_ids(client, auth_headers)[0]
        assert all(
            r["feedback"] is None for r in _feed(client, auth_headers)["recommendations"]
        )

        _rate(client, auth_headers, rec_id, RATING_HELPFUL)
        feed = _feed(client, auth_headers)
        rated = next(r for r in feed["recommendations"] if r["id"] == rec_id)
        assert rated["feedback"] == RATING_HELPFUL
        # by_category holds the same verdict, not a stale copy
        bucket = feed["by_category"][rated["category"]]
        assert next(r for r in bucket if r["id"] == rec_id)["feedback"] == RATING_HELPFUL

    def test_feedback_does_not_change_what_or_how_the_engine_recommends(
        self, client, auth_headers
    ):
        before = _feed(client, auth_headers)["recommendations"]
        ids_before = [r["id"] for r in before]
        confidences_before = [r["confidence"] for r in before]
        priorities_before = [r["priority"] for r in before]

        for rec_id in ids_before[:3]:
            _rate(client, auth_headers, rec_id, RATING_NOT_HELPFUL)

        after = _feed(client, auth_headers)["recommendations"]
        assert [r["id"] for r in after] == ids_before
        assert [r["confidence"] for r in after] == confidences_before
        assert [r["priority"] for r in after] == priorities_before

    def test_one_users_feedback_never_leaks_into_another_feed(
        self, client, db_session, test_user, admin_user, auth_headers, admin_headers
    ):
        rec_id = _first_ids(client, auth_headers)[0]
        _rate(client, auth_headers, rec_id, RATING_HELPFUL)

        other = client.get(
            "/api/v1/recommendations", headers=admin_headers
        ).json()["recommendations"]
        assert all(r["feedback"] is None for r in other)
        assert _relevance(client, admin_headers)["responses"] == 0


class TestRelevanceCalculation:
    def _seed(self, db_session, user_id, rows):
        for i, (rating, category, priority, confidence) in enumerate(rows):
            db_session.add(
                RecommendationFeedback(
                    user_id=user_id,
                    recommendation_id=f"rec-{i}",
                    category=category,
                    priority=priority,
                    stated_confidence=confidence,
                    rating=rating,
                )
            )
        db_session.commit()

    def test_rate_is_helpful_over_explicit_verdicts(self, db_session, test_user):
        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.9)] * 3
            + [(RATING_NOT_HELPFUL, "wake", "low", 0.6)],
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["helpful"] == 3
        assert report["not_helpful"] == 1
        assert report["rated"] == 4
        assert report["relevance_rate"] == 75.0
        assert report["status"] == "ok"

    def test_dismissals_are_recorded_but_kept_out_of_the_rate(
        self, db_session, test_user
    ):
        """'Not now' is a weaker signal than 'this was wrong for me'."""
        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.9)] * 3
            + [(RATING_DISMISSED, "wake", "low", 0.6)] * 5,
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["responses"] == 8
        assert report["dismissed"] == 5
        assert report["rated"] == 3
        assert report["relevance_rate"] == 100.0

    def test_stated_confidence_is_contrasted_with_the_measured_rate(
        self, db_session, test_user
    ):
        """The engine claimed 90%; users found half of it useful."""
        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.9)] * 2
            + [(RATING_NOT_HELPFUL, "sleep", "high", 0.9)] * 2,
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["relevance_rate"] == 50.0
        assert report["avg_stated_confidence"] == 90.0
        assert report["confidence_gap"] == -40.0

    def test_dismissed_confidences_do_not_pollute_the_calibration(
        self, db_session, test_user
    ):
        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.8)] * 3
            + [(RATING_DISMISSED, "wake", "low", 0.1)] * 4,
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["avg_stated_confidence"] == 80.0

    def test_too_few_verdicts_reports_insufficient_data(
        self, db_session, test_user
    ):
        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.9)] * (MIN_RELEVANCE_RESPONSES - 1),
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["status"] == "insufficient_data"
        assert report["rated"] == MIN_RELEVANCE_RESPONSES - 1

    def test_no_feedback_reports_no_data_not_a_perfect_score(
        self, db_session, test_user
    ):
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["status"] == "no_data"
        assert report["relevance_rate"] == 0.0
        assert report["avg_stated_confidence"] is None
        assert report["confidence_gap"] is None
        assert report["by_category"] == {}

    def test_only_dismissals_still_has_no_measurable_relevance(
        self, db_session, test_user
    ):
        self._seed(
            db_session, test_user.id, [(RATING_DISMISSED, "sleep", "low", 0.5)] * 6
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["status"] == "insufficient_data"
        assert report["rated"] == 0
        assert report["relevance_rate"] == 0.0
        assert report["confidence_gap"] is None

    def test_breakdowns_are_reported_per_category_and_priority(
        self, db_session, test_user
    ):
        self._seed(
            db_session,
            test_user.id,
            [
                (RATING_HELPFUL, "sleep", "high", 0.9),
                (RATING_HELPFUL, "sleep", "high", 0.9),
                (RATING_NOT_HELPFUL, "challenge", "low", 0.6),
                (RATING_NOT_HELPFUL, "challenge", "low", 0.6),
                (RATING_HELPFUL, "challenge", "low", 0.6),
            ],
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["by_category"]["sleep"]["relevance_rate"] == 100.0
        assert report["by_category"]["challenge"]["relevance_rate"] == 33.3
        assert report["by_priority"]["high"]["helpful"] == 2
        assert report["by_priority"]["low"]["not_helpful"] == 2

    def test_relevance_is_scoped_to_the_user(
        self, db_session, test_user, admin_user
    ):
        self._seed(
            db_session, test_user.id, [(RATING_HELPFUL, "sleep", "high", 0.9)] * 3
        )
        self._seed(
            db_session,
            admin_user.id,
            [(RATING_NOT_HELPFUL, "sleep", "high", 0.9)] * 9,
        )
        report = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert report["rated"] == 3
        assert report["relevance_rate"] == 100.0

    def test_the_window_filters_older_feedback(self, db_session, test_user):
        from datetime import datetime, timedelta, timezone

        self._seed(
            db_session,
            test_user.id,
            [(RATING_HELPFUL, "sleep", "high", 0.9)] * 3
            + [(RATING_NOT_HELPFUL, "sleep", "high", 0.9)] * 3,
        )
        stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
        for row in (
            db_session.query(RecommendationFeedback)
            .filter(RecommendationFeedback.rating == RATING_NOT_HELPFUL)
            .all()
        ):
            row.updated_at = stale
        db_session.commit()

        windowed = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id, days=30
        )
        assert windowed["rated"] == 3
        assert windowed["relevance_rate"] == 100.0

        all_time = RecommendationRelevanceService.compute_relevance(
            db_session, test_user.id
        )
        assert all_time["rated"] == 6
        assert all_time["relevance_rate"] == 50.0


class TestRelevanceEndpoint:
    def test_rating_through_the_api_shows_up_in_the_report(
        self, client, auth_headers
    ):
        rec_id = _first_ids(client, auth_headers)[0]
        assert _rate(client, auth_headers, rec_id, RATING_HELPFUL).status_code == 200

        report = _relevance(client, auth_headers)
        assert report["responses"] == 1
        assert report["helpful"] == 1
        assert report["rated"] == 1
        # One verdict is not enough to publish a rate
        assert report["status"] == "insufficient_data"
        assert report["avg_stated_confidence"] is not None
        assert report["last_feedback_at"] is not None

    def test_endpoint_aggregates_stored_verdicts(
        self, client, db_session, test_user, auth_headers
    ):
        for i, rating in enumerate(
            [RATING_HELPFUL] * 3 + [RATING_NOT_HELPFUL] + [RATING_DISMISSED] * 2
        ):
            db_session.add(
                RecommendationFeedback(
                    user_id=test_user.id,
                    recommendation_id=f"seeded-{i}",
                    category="sleep",
                    priority="high",
                    stated_confidence=0.9,
                    rating=rating,
                )
            )
        db_session.commit()

        report = _relevance(client, auth_headers)
        assert report["status"] == "ok"
        assert report["responses"] == 6
        assert report["helpful"] == 3
        assert report["not_helpful"] == 1
        assert report["dismissed"] == 2
        assert report["relevance_rate"] == 75.0
        assert report["avg_stated_confidence"] == 90.0
        assert report["confidence_gap"] == -15.0
        assert report["min_responses"] == MIN_RELEVANCE_RESPONSES
        assert report["by_category"]["sleep"]["helpful"] == 3

    def test_the_days_window_is_accepted(self, client, auth_headers):
        report = _relevance(client, auth_headers, params="?days=30")
        assert report["days"] == 30

    def test_empty_report_has_the_full_shape(self, client, auth_headers):
        report = _relevance(client, auth_headers)
        for key in (
            "responses",
            "rated",
            "helpful",
            "not_helpful",
            "dismissed",
            "relevance_rate",
            "avg_stated_confidence",
            "confidence_gap",
            "status",
            "min_responses",
            "by_category",
            "by_priority",
            "last_feedback_at",
        ):
            assert key in report, key
        assert report["status"] == "no_data"
