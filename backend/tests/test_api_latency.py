"""
Runtime API response-time measurement, asserted against real budgets.

``test_dashboard_performance.py`` deliberately asserts query counts because
wall clock is noisy, and ``perf/benchmark.py`` times endpoints offline against
a synthetic dataset. Neither one checks what a request actually costs at
runtime, so this module does.

How it stays honest without flaking: every budget is expressed relative to a
calibration workload measured on the same machine, in the same run, through the
same stack — ``GET /system/status`` (one settings read plus JSON). A slow CI box
inflates the calibration and the budget together, so the assertions test the
*shape* of the cost, not the speed of the hardware. A generous absolute ceiling
sits on top to catch anything that escapes the ratio.

Durations come from the ``X-Process-Time`` header the timing middleware stamps,
which is the server-side duration only — client and TestClient overhead are
excluded.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.request_metrics import (
    PROCESS_TIME_HEADER,
    percentile,
    request_latency,
)
from app.models.alarm import Alarm, AlarmChallengeLog
from app.models.alarm_wake_event import AlarmWakeEvent

# Project targets from perf/benchmark.py. Imported rather than duplicated so a
# budget change there is enforced here too.
from perf.benchmark import BUDGETS_MS, DEFAULT_P95_BUDGET_MS

#: Requests per endpoint. Enough for a stable p95 without slowing the suite.
ITERATIONS = 20
#: Calibration requests. More samples because everything else is scaled by it.
CALIBRATION_ITERATIONS = 30
#: Floor so a sub-millisecond calibration cannot produce an impossible budget.
ABSOLUTE_FLOOR_MS = 50.0
#: Nothing in this suite may take longer than this, on any machine.
HARD_CEILING_MS = 3000.0
#: Calibration cost on a machine the project budgets were set for. Machines
#: slower than this get the project budgets scaled up by the same factor.
CALIBRATION_REFERENCE_MS = 5.0

#: (perf/benchmark.py scenario key, path, query params, p95 budget as a
#: multiple of the calibration request). Multipliers carry roughly 3-4x
#: headroom over what each endpoint measures today, so they catch a structural
#: regression without tracking hardware noise. /dashboard/productivity is
#: allowed far more because it runs the pandas sleep and correlation pass.
MEASURED_ENDPOINTS = [
    ("dashboard_summary_monthly", "/api/v1/dashboard/summary", {"period": "monthly"}, 30.0),
    ("dashboard_wake_stats", "/api/v1/dashboard/wake-stats", {"days": 30}, 20.0),
    (
        "dashboard_challenge_performance",
        "/api/v1/dashboard/challenge-performance",
        {"days": 30},
        20.0,
    ),
    ("dashboard_productivity", "/api/v1/dashboard/productivity", {"days": 30}, 150.0),
    ("user_profile_stats", "/api/v1/users/profile/stats", {}, 30.0),
]


@pytest.fixture(autouse=True)
def clean_registry():
    """Latency samples are process-global; isolate each test."""
    request_latency.reset()
    yield
    request_latency.reset()


@pytest.fixture
def latency_history(db_session, test_user):
    """90 days of wake and challenge activity — a plausible active account."""
    alarm = Alarm(
        user_id=test_user.id,
        title="Latency alarm",
        alarm_time=datetime.now(timezone.utc).time(),
        is_active=True,
    )
    db_session.add(alarm)
    db_session.commit()
    db_session.refresh(alarm)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for day in range(90):
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
                snooze_count_at_dismiss=day % 3,
                time_to_dismiss_seconds=60,
                wakefulness_score=70.0 + (day % 20),
                verified=True,
            )
        )
        for index in range(2):
            rows.append(
                AlarmChallengeLog(
                    alarm_id=alarm.id,
                    user_id=test_user.id,
                    challenge_type="math",
                    difficulty="medium",
                    challenge_prompt=f"p-{day}-{index}",
                    is_correct=(day + index) % 4 != 0,
                    time_taken_seconds=10,
                    points_earned=5,
                    created_at=moment + timedelta(minutes=index),
                )
            )
    db_session.add_all(rows)
    db_session.commit()
    return alarm


def _timed(client, path, headers=None, params=None, iterations=ITERATIONS):
    """Return the server-side durations for ``iterations`` identical requests."""
    durations = []
    for _ in range(iterations):
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200, response.text
        durations.append(float(response.headers[PROCESS_TIME_HEADER]))
    return durations


@pytest.fixture
def calibration_ms(client):
    """Median cost of the cheapest real request on this machine."""
    durations = _timed(
        client, "/api/v1/system/status", iterations=CALIBRATION_ITERATIONS
    )
    return percentile(durations, 50)


class TestProcessTimeHeader:
    """Every response must carry its own measured duration."""

    def test_responses_carry_a_measured_duration(self, client):
        response = client.get("/api/v1/system/status")

        assert response.status_code == 200
        assert PROCESS_TIME_HEADER in response.headers
        assert float(response.headers[PROCESS_TIME_HEADER]) > 0

    def test_error_responses_are_timed_too(self, client):
        """A 401 still costs the server time and must still be measured."""
        response = client.get("/api/v1/dashboard/summary")

        assert response.status_code == 401
        assert float(response.headers[PROCESS_TIME_HEADER]) > 0

    def test_the_header_matches_what_was_recorded(self, client):
        response = client.get("/api/v1/system/status")
        header_ms = float(response.headers[PROCESS_TIME_HEADER])

        recorded = request_latency.durations_for("GET", "/api/v1/system/status")
        assert len(recorded) == 1
        assert recorded[0] == pytest.approx(header_ms, abs=0.01)


class TestLatencyRegistry:
    """Samples must be keyed by route template and summarised correctly."""

    def test_path_parameters_collapse_to_one_route_key(
        self, client, auth_headers, latency_history
    ):
        for _ in range(3):
            client.get(f"/api/v1/alarms/{latency_history.id}", headers=auth_headers)

        snapshot = request_latency.snapshot()
        keys = [r["route"] for r in snapshot["routes"]]
        assert "GET /api/v1/alarms/{alarm_id}" in keys
        assert f"GET /api/v1/alarms/{latency_history.id}" not in keys

    def test_percentiles_are_ordered_and_bounded(self, client):
        _timed(client, "/api/v1/system/status", iterations=CALIBRATION_ITERATIONS)

        route = next(
            r
            for r in request_latency.snapshot()["routes"]
            if r["route"] == "GET /api/v1/system/status"
        )
        assert route["sampled"] == CALIBRATION_ITERATIONS
        assert route["requests"] == CALIBRATION_ITERATIONS
        assert route["errors"] == 0
        assert route["min_ms"] <= route["p50_ms"] <= route["p95_ms"]
        assert route["p95_ms"] <= route["p99_ms"] <= route["max_ms"]
        assert 0 < route["mean_ms"] <= route["max_ms"]

    def test_server_errors_are_counted_separately(self, client, monkeypatch):
        from app.services import system_settings_service

        monkeypatch.setattr(
            system_settings_service.SystemSettingsService,
            "get_or_create",
            staticmethod(lambda db: (_ for _ in ()).throw(RuntimeError("boom"))),
        )
        with pytest.raises(RuntimeError):
            client.get("/api/v1/system/status")

        # The middleware never saw a response, so nothing is recorded as OK.
        assert request_latency.durations_for("GET", "/api/v1/system/status") == []

    def test_the_reservoir_is_bounded(self):
        from app.core.request_metrics import RequestLatencyRegistry

        registry = RequestLatencyRegistry(sample_size=5)
        for i in range(50):
            registry.record(
                method="GET", route="/x", status_code=200, duration_ms=float(i)
            )

        route = registry.snapshot()["routes"][0]
        assert route["sampled"] == 5
        assert route["requests"] == 50  # counters do not roll off
        assert route["min_ms"] == 45.0

    def test_snapshot_can_be_limited_to_the_slowest_routes(self):
        from app.core.request_metrics import RequestLatencyRegistry

        registry = RequestLatencyRegistry()
        for name, cost in (("/slow", 90.0), ("/mid", 40.0), ("/fast", 5.0)):
            registry.record(
                method="GET", route=name, status_code=200, duration_ms=cost
            )

        routes = registry.snapshot(top=2)["routes"]
        assert [r["route"] for r in routes] == ["GET /slow", "GET /mid"]


class TestMeasuredApiResponseTime:
    """The actual latency assertions."""

    @pytest.mark.parametrize("key,path,params,multiplier", MEASURED_ENDPOINTS)
    def test_endpoint_latency_is_within_budget(
        self,
        client,
        auth_headers,
        latency_history,
        calibration_ms,
        key,
        path,
        params,
        multiplier,
    ):
        durations = _timed(client, path, headers=auth_headers, params=params)
        p50 = percentile(durations, 50)
        p95 = percentile(durations, 95)

        relative_budget = max(ABSOLUTE_FLOOR_MS, calibration_ms * multiplier)
        assert p95 <= relative_budget, (
            f"{key}: p95 {p95:.1f}ms exceeds {relative_budget:.1f}ms "
            f"({multiplier}x the {calibration_ms:.2f}ms calibration). "
            "A jump here usually means new per-row work on the read path."
        )
        assert p95 <= HARD_CEILING_MS, f"{key}: p95 {p95:.1f}ms"
        assert p50 <= p95

    @pytest.mark.parametrize("key,path,params,multiplier", MEASURED_ENDPOINTS)
    def test_endpoint_meets_the_project_p95_target(
        self,
        client,
        auth_headers,
        latency_history,
        calibration_ms,
        key,
        path,
        params,
        multiplier,
    ):
        """The perf/benchmark.py budget, scaled for slower hardware."""
        durations = _timed(client, path, headers=auth_headers, params=params)
        p95 = percentile(durations, 95)

        target = BUDGETS_MS.get(key, DEFAULT_P95_BUDGET_MS)
        machine_factor = max(1.0, calibration_ms / CALIBRATION_REFERENCE_MS)
        budget = target * machine_factor

        assert p95 <= budget, (
            f"{key}: p95 {p95:.1f}ms exceeds the {target}ms project target "
            f"scaled by {machine_factor:.2f} for this machine."
        )

    def test_the_registry_agrees_with_the_measured_headers(
        self, client, auth_headers, latency_history
    ):
        durations = _timed(
            client, "/api/v1/dashboard/summary", headers=auth_headers,
            params={"period": "monthly"},
        )
        recorded = request_latency.durations_for(
            "GET", "/api/v1/dashboard/summary"
        )

        assert len(recorded) == len(durations)
        assert percentile(recorded, 95) == pytest.approx(
            percentile(durations, 95), abs=0.01
        )

    def test_a_heavier_window_is_not_disproportionately_slower(
        self, client, auth_headers, latency_history, calibration_ms
    ):
        """Widening the window must not multiply the cost — the N+1 signature."""
        short = percentile(
            _timed(client, "/api/v1/dashboard/wake-stats", headers=auth_headers,
                   params={"days": 7}),
            50,
        )
        long = percentile(
            _timed(client, "/api/v1/dashboard/wake-stats", headers=auth_headers,
                   params={"days": 365}),
            50,
        )

        allowance = max(short * 6.0, calibration_ms * 12.0)
        assert long <= allowance, (
            f"365-day window cost {long:.1f}ms against a 7-day {short:.1f}ms; "
            "cost is scaling with the window."
        )


class TestMetricsEndpoint:
    def test_admin_can_read_measured_response_times(
        self, client, admin_headers, auth_headers, latency_history
    ):
        _timed(client, "/api/v1/dashboard/summary", headers=auth_headers,
               params={"period": "monthly"})

        response = client.get("/api/v1/system/metrics", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()["requests"]

        assert body["routes_tracked"] >= 1
        assert body["total_requests"] >= ITERATIONS
        assert body["overall"]["p95_ms"] > 0
        summary = next(
            r for r in body["routes"] if r["route"] == "GET /api/v1/dashboard/summary"
        )
        assert summary["sampled"] == ITERATIONS
        assert summary["p50_ms"] <= summary["p95_ms"]

    def test_the_slowest_routes_can_be_requested_alone(
        self, client, admin_headers, auth_headers, latency_history
    ):
        _timed(client, "/api/v1/dashboard/summary", headers=auth_headers,
               params={"period": "monthly"}, iterations=3)
        _timed(client, "/api/v1/system/status", iterations=3)

        body = client.get(
            "/api/v1/system/metrics?top=1", headers=admin_headers
        ).json()["requests"]
        assert len(body["routes"]) == 1

    def test_metrics_are_admin_only(self, client, auth_headers):
        assert client.get("/api/v1/system/metrics").status_code == 401
        assert (
            client.get("/api/v1/system/metrics", headers=auth_headers).status_code
            == 403
        )
