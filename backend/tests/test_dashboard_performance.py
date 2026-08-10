"""Performance regression guards for the dashboard read paths.

These are not latency benchmarks — timing assertions are too flaky in CI.
They lock in the two structural properties that the ``perf/benchmark.py``
measurements identified as the actual causes of slow dashboards:

1. Query count per request must not scale with the requested window
   (the N+1 guard).
2. The indexes backing the hot filter/order patterns must stay declared on
   the models.

Run the full measurement suite with ``python -m perf.benchmark``.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.user import User


@pytest.fixture
def query_counter(db_session):
    """Count SQL statements issued against the test engine."""
    engine = db_session.get_bind()
    counter = {"count": 0}

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


@pytest.fixture
def dashboard_history(db_session, test_user):
    """Seed 120 days of wake and challenge activity for the test user."""
    alarm = Alarm(
        user_id=test_user.id,
        title="Perf alarm",
        alarm_time=datetime.now(timezone.utc).time(),
        is_active=True,
    )
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for day in range(120):
        moment = now - timedelta(days=day, hours=1)
        rows.append(
            AlarmWakeEvent(
                user_id=test_user.id,
                alarm_id=alarm.id,
                triggered_at=moment,
                dismissed_at=moment,
                dismiss_method="challenge",
                challenges_required=1,
                challenges_completed=1,
                failed_attempts=0,
                snooze_count_at_dismiss=0,
                time_to_dismiss_seconds=60,
                verified=True,
            )
        )
        rows.append(
            AlarmChallengeLog(
                alarm_id=alarm.id,
                user_id=test_user.id,
                challenge_type="math",
                difficulty="medium",
                is_correct=True,
                time_taken_seconds=10,
                points_earned=5,
                created_at=moment,
            )
        )
    db_session.add_all(rows)
    db_session.commit()
    return alarm


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/v1/dashboard/summary", {"period": "monthly"}),
        ("/api/v1/dashboard/wake-stats", {"days": 90}),
        ("/api/v1/dashboard/challenge-performance", {"days": 90}),
        ("/api/v1/dashboard/productivity", {"days": 90}),
        ("/api/v1/dashboard/alarm-history", {"days": 90}),
    ],
)
def test_user_dashboard_endpoints_use_bounded_query_counts(
    client, auth_headers, dashboard_history, query_counter, path, params
):
    """Each user dashboard call stays well under a per-request query ceiling."""
    query_counter["count"] = 0
    response = client.get(path, params=params, headers=auth_headers)

    assert response.status_code == 200
    assert query_counter["count"] <= 15, (
        f"{path} issued {query_counter['count']} queries; "
        "a jump here usually means a new per-row or per-day query was added"
    )


def test_admin_statistics_query_count_is_independent_of_window(
    client, admin_headers, db_session, dashboard_history, query_counter
):
    """The registration trend must not issue one COUNT per day in the window.

    Before this guard, ``/admin/statistics?days=365`` issued 368 queries
    against 33 for ``days=30``.
    """
    query_counter["count"] = 0
    short = client.get(
        "/api/v1/admin/statistics", params={"days": 7}, headers=admin_headers
    )
    short_queries = query_counter["count"]

    query_counter["count"] = 0
    long = client.get(
        "/api/v1/admin/statistics", params={"days": 365}, headers=admin_headers
    )
    long_queries = query_counter["count"]

    assert short.status_code == 200
    assert long.status_code == 200
    assert long_queries == short_queries, (
        f"query count scaled with the window ({short_queries} -> {long_queries}); "
        "the per-day aggregation loop has regressed"
    )


def test_admin_statistics_registration_trend_matches_day_buckets(
    client, admin_headers, db_session
):
    """Bucketing registrations in Python must match per-day SQL counting."""
    window_start = (
        datetime.now(timezone.utc) - timedelta(days=5)
    ).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    db_session.add_all(
        [
            User(
                email=f"trend-{i}@example.com",
                username=f"trenduser{i}",
                hashed_password="x",
                is_active=True,
                created_at=window_start + timedelta(days=1, hours=i),
            )
            for i in range(3)
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/v1/admin/statistics", params={"days": 5}, headers=admin_headers
    )

    assert response.status_code == 200
    trend = response.json()["registration_trend"]
    assert len(trend) == 5
    target_date = (window_start + timedelta(days=1)).strftime("%Y-%m-%d")
    bucket = next(d for d in trend if d["date"] == target_date)
    assert bucket["registrations"] == 3


def test_admin_analytics_query_count_is_independent_of_window(
    client, admin_headers, db_session, query_counter
):
    """The analytics ingestion trend must not issue one COUNT per day either."""
    query_counter["count"] = 0
    short = client.get(
        "/api/v1/admin/analytics", params={"days": 7}, headers=admin_headers
    )
    short_queries = query_counter["count"]

    query_counter["count"] = 0
    long = client.get(
        "/api/v1/admin/analytics", params={"days": 365}, headers=admin_headers
    )
    long_queries = query_counter["count"]

    assert short.status_code == 200
    assert long.status_code == 200
    assert long_queries == short_queries, (
        f"query count scaled with the window ({short_queries} -> {long_queries})"
    )


def test_admin_analytics_ingestion_trend_buckets_by_day(
    client, admin_headers, db_session, test_user
):
    """Grouped day buckets must match the events actually stored that day."""
    window_start = (
        datetime.now(timezone.utc) - timedelta(days=5)
    ).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    target_day = window_start + timedelta(days=2)

    db_session.add_all(
        [
            AnalyticsEvent(
                user_id=test_user.id,
                event_type="dashboard.viewed",
                source="client",
                event_data={},
                created_at=target_day + timedelta(hours=i),
            )
            for i in range(4)
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/v1/admin/analytics", params={"days": 5}, headers=admin_headers
    )

    assert response.status_code == 200
    trend = response.json()["ingestion_trend"]
    assert len(trend) == 5
    bucket = next(d for d in trend if d["date"] == target_day.strftime("%Y-%m-%d"))
    assert bucket["events"] == 4


def test_admin_statistics_sql_aggregates_match_seeded_activity(
    client, admin_headers, dashboard_history
):
    """SQL-side grouping must produce the same totals as row-by-row counting."""
    response = client.get(
        "/api/v1/admin/statistics", params={"days": 365}, headers=admin_headers
    )

    assert response.status_code == 200
    body = response.json()

    challenge = body["challenge_performance"]
    assert challenge["total_attempts"] == 120
    assert challenge["total_correct"] == 120
    assert challenge["overall_accuracy_pct"] == 100.0
    assert challenge["total_points_awarded"] == 600
    assert challenge["by_type"] == {
        "math": {"total": 120, "correct": 120, "points": 600, "accuracy_pct": 100.0}
    }
    assert challenge["by_difficulty"] == {
        "medium": {"total": 120, "correct": 120, "accuracy_pct": 100.0}
    }

    wakes = body["wake_events"]
    assert wakes["total"] == 120
    assert wakes["verified"] == 120
    assert wakes["abandoned"] == 0
    assert wakes["success_rate_pct"] == 100.0
    assert wakes["avg_dismiss_seconds"] == 60.0
    assert wakes["by_dismiss_method"] == {"challenge": 120}

    assert sum(h["count"] for h in body["activity_by_hour"]) == 120
    assert sum(w["count"] for w in body["activity_by_weekday"]) == 120


@pytest.mark.parametrize(
    "model,index_name,columns",
    [
        (Alarm, "ix_alarms_user_active", ("user_id", "is_active")),
        (Alarm, "ix_alarms_user_next_trigger", ("user_id", "next_trigger_at")),
        (
            AlarmWakeEvent,
            "ix_alarm_wake_events_user_dismissed",
            ("user_id", "dismissed_at"),
        ),
        (
            AlarmWakeEvent,
            "ix_alarm_wake_events_user_verified_dismissed",
            ("user_id", "verified", "dismissed_at"),
        ),
        (
            AlarmWakeEvent,
            "ix_alarm_wake_events_dismissed",
            ("dismissed_at",),
        ),
        (User, "ix_users_created_at", ("created_at",)),
    ],
)
def test_dashboard_read_path_indexes_are_declared(model, index_name, columns):
    """Dropping one of these indexes reintroduces a measured full table scan."""
    indexes = {idx.name: idx for idx in model.__table__.indexes}
    assert index_name in indexes, f"missing index {index_name} on {model.__tablename__}"
    assert tuple(c.name for c in indexes[index_name].columns) == columns
