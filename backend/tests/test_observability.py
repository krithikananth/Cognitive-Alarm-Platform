"""
Observability: logging configuration, correlation ids, client error intake and
metric alerting.

These tests pin the behaviour that was previously missing outright — most
importantly that ``logger.info(...)`` actually reaches a handler. Before the
logging configuration existed the root logger had none, so Python's lastResort
handler applied at WARNING and every INFO record in the codebase was discarded.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core import logging_config
from app.core.logging_config import (
    ACCESS_LOGGER_NAME,
    JsonLogFormatter,
    RequestContextFilter,
    configure_logging,
    logging_status,
    reset_logging,
    resolve_log_directory,
)
from app.core.metrics_exposition import escape_label_value, render_prometheus
from app.core.request_context import (
    NO_REQUEST_ID,
    bind_request_id,
    get_request_id,
    new_request_id,
    reset_request_id,
    sanitize_request_id,
)
from app.core.request_metrics import request_latency
from app.services.metrics_alert_service import (
    RULE_API_ERROR_RATE,
    RULE_API_LATENCY,
    RULE_CHALLENGE_LATENCY,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    MetricsAlertEvaluator,
)


# ── helpers ───────────────────────────────────────────────────────────


class CaptureHandler(logging.Handler):
    """Collects formatted output so the real formatter is under test."""

    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.setFormatter(formatter)
        self.lines: List[str] = []
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.lines.append(self.format(record))

    def payloads(self) -> List[Dict[str, Any]]:
        return [json.loads(line) for line in self.lines]


@pytest.fixture
def json_capture():
    """Attach a JSON-formatted capture handler to the root logger."""
    handler = CaptureHandler(JsonLogFormatter())
    handler.addFilter(RequestContextFilter("icap-backend", "test", "1.0.0"))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


@pytest.fixture(autouse=True)
def ensure_app_logging():
    """Install the application configuration before every test in this module.

    Other suites run code that rewrites the global logging tree (Alembic's
    ``env.py`` being the notable one), so the state left by the previous test
    can never be assumed. Forcing here also makes each test self-healing.
    """
    configure_logging(force=True)
    yield


@pytest.fixture
def restore_logging():
    """Reinstall the application logging config after a test reconfigures it."""
    yield
    reset_logging()
    configure_logging(force=True)


@pytest.fixture(autouse=True)
def clean_request_context():
    """No test may leak a correlation id into the next one."""
    token = bind_request_id("test-context")[1]
    reset_request_id(token)
    yield


def _route(name="GET /api/v1/alarms/", **overrides) -> Dict[str, Any]:
    base = {
        "route": name,
        "requests": 100,
        "errors": 0,
        "sampled": 100,
        "p50_ms": 5.0,
        "p95_ms": 10.0,
        "p99_ms": 12.0,
        "min_ms": 1.0,
        "max_ms": 20.0,
        "mean_ms": 6.0,
    }
    base.update(overrides)
    return base


def _requests_snapshot(*routes) -> Dict[str, Any]:
    return {"sample_size": 500, "routes_tracked": len(routes), "routes": list(routes)}


def _challenge_key(key="math/medium/procedural", **overrides) -> Dict[str, Any]:
    base = {
        "key": key,
        "challenge_type": key.split("/")[0],
        "difficulty": key.split("/")[1],
        "source": key.split("/")[2],
        "calls": 100,
        "failures": 0,
        "sampled": 100,
        "p50_ms": 5.0,
        "p95_ms": 10.0,
        "p99_ms": 12.0,
        "min_ms": 1.0,
        "max_ms": 15.0,
        "mean_ms": 6.0,
    }
    base.update(overrides)
    return base


def _challenges_snapshot(*keys) -> Dict[str, Any]:
    return {"sample_size": 500, "keys_tracked": len(keys), "by_key": list(keys)}


# ── logging configuration ─────────────────────────────────────────────


class TestLoggingConfiguration:
    def test_info_records_actually_reach_a_handler(self, json_capture):
        """The whole point: INFO used to be silently discarded."""
        logging.getLogger("app.services.probe").info("scheduled sweep finished")

        messages = [p["message"] for p in json_capture.payloads()]
        assert "scheduled sweep finished" in messages

    def test_root_logger_has_handlers_after_configuration(self):
        assert logging.getLogger().handlers, "root logger must not rely on lastResort"

    def test_configured_level_is_applied(self):
        assert logging.getLogger().level <= logging.INFO

    def test_status_reports_what_was_installed(self):
        status = logging_status()
        assert status["level"]
        assert status["format"] in {"json", "console"}
        assert "console" in status["handlers"]

    def test_configuration_is_idempotent(self):
        before = len(logging.getLogger().handlers)
        configure_logging()
        configure_logging()
        assert len(logging.getLogger().handlers) == before

    def test_force_rebuilds_without_duplicating_handlers(self, restore_logging):
        # Counted from the installed set, not the root logger: pytest attaches
        # its own capture handlers there for the duration of each test.
        before = configure_logging(force=True)["handlers"]
        after = configure_logging(force=True)["handlers"]
        assert before == after
        assert len(after) == len(set(after))

    def test_invalid_level_falls_back_instead_of_silencing_everything(
        self, monkeypatch, restore_logging
    ):
        monkeypatch.setattr(logging_config.settings, "LOG_LEVEL", "NOT_A_LEVEL")
        status = configure_logging(force=True)
        assert status["level"] == "INFO"

    def test_noisy_third_party_loggers_are_capped(self):
        assert logging.getLogger("httpx").level >= logging.WARNING


class TestLoggingSurvivesMigrations:
    """Alembic's ``env.py`` calls ``fileConfig``, which rewrites logging.

    Left unguarded it resets the root logger to WARN and disables every logger
    the application already created, so an in-process migration would silently
    switch application logging off for the rest of the process.
    """

    def test_the_app_is_marked_as_owning_the_logging_tree(self):
        assert logging_config.is_logging_configured() is True

    def test_running_migrations_does_not_silence_the_application(
        self, tmp_path, json_capture
    ):
        from alembic import command
        from alembic.config import Config

        backend_root = Path(logging_config.__file__).resolve().parents[2]
        config = Config(str(backend_root / "alembic.ini"))
        config.set_main_option("script_location", str(backend_root / "alembic"))
        config.set_main_option(
            "sqlalchemy.url", f"sqlite:///{tmp_path / 'migrated.db'}"
        )

        root_level_before = logging.getLogger().level
        command.upgrade(config, "head")

        assert logging.getLogger().level == root_level_before
        assert logging_config.is_logging_configured() is True

        logging.getLogger("app.services.post_migration").info("still logging")
        assert "still logging" in [p["message"] for p in json_capture.payloads()]


class TestStructuredFormat:
    def test_record_is_valid_single_line_json(self, json_capture):
        logging.getLogger("app.test").warning("structured output")

        line = json_capture.lines[-1]
        assert "\n" not in line
        json.loads(line)

    def test_required_fields_are_present(self, json_capture):
        logging.getLogger("app.test").info("field check")

        payload = json_capture.payloads()[-1]
        for field in (
            "timestamp",
            "level",
            "logger",
            "message",
            "request_id",
            "service",
            "environment",
            "version",
            "module",
            "function",
            "line",
        ):
            assert field in payload, f"missing {field}"

    def test_extra_fields_are_promoted_to_top_level_keys(self, json_capture):
        logging.getLogger("app.test").info(
            "with extras", extra={"event": "probe", "duration_ms": 12.5}
        )

        payload = json_capture.payloads()[-1]
        assert payload["event"] == "probe"
        assert payload["duration_ms"] == 12.5

    def test_exceptions_are_serialized_not_dropped(self, json_capture):
        try:
            raise ValueError("kaboom")
        except ValueError:
            logging.getLogger("app.test").exception("failed")

        payload = json_capture.payloads()[-1]
        assert payload["exception"]["type"] == "ValueError"
        assert "kaboom" in payload["exception"]["message"]
        assert "Traceback" in payload["exception"]["traceback"]

    def test_unserializable_extra_does_not_lose_the_record(self, json_capture):
        class Opaque:
            def __repr__(self) -> str:
                return "<opaque>"

        logging.getLogger("app.test").info("odd extra", extra={"thing": Opaque()})

        payload = json_capture.payloads()[-1]
        assert payload["thing"] == "<opaque>"

    def test_percent_style_message_is_interpolated(self, json_capture):
        logging.getLogger("app.test").info("processed %d of %d", 3, 7)

        assert json_capture.payloads()[-1]["message"] == "processed 3 of 7"


class TestLogRotation:
    def test_rotating_file_handler_is_installed(self):
        from logging.handlers import RotatingFileHandler

        handlers = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, RotatingFileHandler)
        ]
        assert handlers, "persistent log rotation must be configured"
        assert handlers[0].maxBytes > 0
        assert handlers[0].backupCount > 0

    def test_log_directory_resolves_under_backend(self):
        assert resolve_log_directory().is_absolute()

    def test_handler_rotates_once_the_size_limit_is_passed(self, tmp_path):
        from logging.handlers import RotatingFileHandler

        target = tmp_path / "rotate.log"
        handler = RotatingFileHandler(
            target, maxBytes=512, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(JsonLogFormatter())
        handler.addFilter(RequestContextFilter("icap-backend", "test", "1.0.0"))
        logger = logging.getLogger("app.rotation-probe")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            for i in range(50):
                logger.info("filling the log file %d", i)
        finally:
            logger.removeHandler(handler)
            handler.close()
            logger.propagate = True

        assert target.exists()
        assert (tmp_path / "rotate.log.1").exists(), "rotation never happened"

    def test_unwritable_directory_degrades_to_stdout(
        self, monkeypatch, restore_logging
    ):
        def explode(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(logging_config, "RotatingFileHandler", explode)
        status = configure_logging(force=True)

        assert status["log_file"] is None
        assert "console" in status["handlers"]


# ── correlation ids ───────────────────────────────────────────────────


class TestRequestContext:
    def test_default_outside_a_request(self):
        assert get_request_id() == NO_REQUEST_ID

    def test_generated_ids_are_unique(self):
        assert len({new_request_id() for _ in range(200)}) == 200

    @pytest.mark.parametrize(
        "value",
        ["abc-123", "0123456789abcdef", "trace:1.2_3", "A" * 64],
    )
    def test_safe_values_are_accepted(self, value):
        assert sanitize_request_id(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "   ",
            "A" * 65,
            "bad value",
            "inject\r\nX-Admin: 1",
            "<script>alert(1)</script>",
            'quote"d',
        ],
    )
    def test_unsafe_values_are_rejected(self, value):
        assert sanitize_request_id(value) is None

    def test_bind_adopts_a_trusted_value(self):
        request_id, token = bind_request_id("known-trace-id")
        try:
            assert request_id == "known-trace-id"
            assert get_request_id() == "known-trace-id"
        finally:
            reset_request_id(token)

    def test_bind_mints_a_value_when_the_inbound_one_is_unsafe(self):
        request_id, token = bind_request_id("nope nope\n")
        try:
            assert request_id != "nope nope\n"
            assert sanitize_request_id(request_id) == request_id
        finally:
            reset_request_id(token)

    def test_reset_restores_the_previous_value(self):
        _, outer = bind_request_id("outer")
        _, inner = bind_request_id("inner")
        reset_request_id(inner)
        assert get_request_id() == "outer"
        reset_request_id(outer)

    def test_bound_id_lands_on_log_records(self, json_capture):
        _, token = bind_request_id("corr-42")
        try:
            logging.getLogger("app.test").info("inside a request")
        finally:
            reset_request_id(token)

        assert json_capture.payloads()[-1]["request_id"] == "corr-42"


class TestRequestIdMiddleware:
    def test_response_carries_a_generated_id(self, client):
        response = client.get("/health")
        request_id = response.headers.get("X-Request-ID")

        assert request_id
        assert sanitize_request_id(request_id) == request_id

    def test_ids_differ_between_requests(self, client):
        first = client.get("/health").headers["X-Request-ID"]
        second = client.get("/health").headers["X-Request-ID"]
        assert first != second

    def test_inbound_id_is_honoured(self, client):
        response = client.get(
            "/health", headers={"X-Request-ID": "client-supplied-99"}
        )
        assert response.headers["X-Request-ID"] == "client-supplied-99"

    def test_header_injection_attempt_is_replaced_not_echoed(self, client):
        response = client.get(
            "/health", headers={"X-Request-ID": "abc/../../etc/passwd"}
        )
        echoed = response.headers["X-Request-ID"]
        assert echoed != "abc/../../etc/passwd"
        assert sanitize_request_id(echoed) == echoed

    def test_timing_header_is_still_stamped(self, client):
        """The correlation layer must not displace the existing metrics."""
        assert client.get("/health").headers.get("X-Process-Time") is not None

    def test_access_log_line_is_emitted_with_the_correlation_id(
        self, client, json_capture
    ):
        response = client.get("/api/v1/system/status")
        request_id = response.headers["X-Request-ID"]

        access = [
            p
            for p in json_capture.payloads()
            if p.get("logger") == ACCESS_LOGGER_NAME
            and p.get("http_path") == "/api/v1/system/status"
        ]
        assert access, "no access log record was emitted"
        entry = access[-1]
        assert entry["request_id"] == request_id
        assert entry["http_method"] == "GET"
        assert entry["http_status"] == 200
        assert entry["event"] == "request.completed"
        assert isinstance(entry["duration_ms"], float)

    def test_access_log_uses_the_route_template_not_the_raw_path(
        self, client, auth_headers, json_capture
    ):
        client.get("/api/v1/alarms/999999", headers=auth_headers)

        entries = [
            p
            for p in json_capture.payloads()
            if p.get("logger") == ACCESS_LOGGER_NAME
            and p.get("http_path") == "/api/v1/alarms/999999"
        ]
        assert entries
        assert entries[-1]["http_route"] == "/api/v1/alarms/{alarm_id}"

    def test_client_errors_are_logged_at_warning(self, client, json_capture):
        client.get("/api/v1/alarms/")  # unauthenticated → 401

        entries = [
            p
            for p in json_capture.payloads()
            if p.get("logger") == ACCESS_LOGGER_NAME and p.get("http_status") == 401
        ]
        assert entries and entries[-1]["level"] == "WARNING"

    def test_health_probes_are_not_logged_at_info(self, client, json_capture):
        """Container probes hit /health every 30s; they must not bury traffic."""
        client.get("/health")

        entries = [
            p
            for p in json_capture.payloads()
            if p.get("logger") == ACCESS_LOGGER_NAME and p.get("http_path") == "/health"
        ]
        assert entries == []

    def test_a_failing_health_probe_is_still_logged(self, client, json_capture):
        client.get("/health/does-not-exist")

        entries = [
            p
            for p in json_capture.payloads()
            if p.get("logger") == ACCESS_LOGGER_NAME and p.get("http_status") == 404
        ]
        assert entries and entries[-1]["level"] == "WARNING"

    def test_service_logs_inherit_the_request_correlation_id(
        self, client, json_capture
    ):
        """A record emitted deep inside a handler must be attributable."""
        marker = "correlation-probe-record"

        from app.api.v1.endpoints import system as system_endpoint

        original = system_endpoint.SystemSettingsService.get_or_create

        def noisy(db):
            logging.getLogger("app.services.probe").info(marker)
            return original(db)

        system_endpoint.SystemSettingsService.get_or_create = staticmethod(noisy)
        try:
            response = client.get("/api/v1/system/status")
        finally:
            system_endpoint.SystemSettingsService.get_or_create = original

        deep = [p for p in json_capture.payloads() if p.get("message") == marker]
        assert deep, "probe record was not emitted"
        assert deep[-1]["request_id"] == response.headers["X-Request-ID"]


# ── client error reporting ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_client_error_limiter():
    from app.api.v1.endpoints.system import client_error_limiter

    client_error_limiter.reset()
    yield
    client_error_limiter.reset()


class TestClientErrorReporting:
    ENDPOINT = "/api/v1/system/client-errors"

    def test_report_is_accepted_without_authentication(self, client):
        response = client.post(
            self.ENDPOINT,
            json={"message": "TypeError: x is undefined", "source": "error_boundary"},
        )
        assert response.status_code == 202
        assert response.json()["recorded"] is True

    def test_report_is_written_to_the_server_log(self, client, json_capture):
        client.post(
            self.ENDPOINT,
            json={
                "message": "Cannot read properties of null",
                "name": "TypeError",
                "source": "error_boundary",
                "boundary": "route",
                "component_stack": "at UserDashboard",
                "url": "https://app.example.com/dashboard",
            },
        )

        entries = [
            p for p in json_capture.payloads() if p.get("event") == "client.error"
        ]
        assert entries
        entry = entries[-1]
        assert entry["level"] == "ERROR"
        assert entry["error_name"] == "TypeError"
        assert entry["boundary"] == "route"
        assert entry["component_stack"] == "at UserDashboard"
        assert entry["page_url"] == "https://app.example.com/dashboard"

    def test_browser_correlation_id_is_preserved(self, client):
        response = client.post(
            self.ENDPOINT,
            json={"message": "boom", "request_id": "browser-trace-7"},
        )
        assert response.json()["request_id"] == "browser-trace-7"

    def test_forged_correlation_id_is_dropped(self, client):
        response = client.post(
            self.ENDPOINT,
            json={"message": "boom", "request_id": "evil\r\nSet-Cookie: a=b"},
        )
        returned = response.json()["request_id"]
        assert sanitize_request_id(returned) == returned

    def test_unknown_source_is_normalized_rather_than_rejected(self, client, json_capture):
        response = client.post(
            self.ENDPOINT, json={"message": "boom", "source": "made-up"}
        )
        assert response.status_code == 202
        entries = [
            p for p in json_capture.payloads() if p.get("event") == "client.error"
        ]
        assert entries[-1]["client_source"] == "unknown"

    def test_warning_severity_lowers_the_log_level(self, client, json_capture):
        client.post(
            self.ENDPOINT, json={"message": "slow render", "severity": "warning"}
        )
        entries = [
            p for p in json_capture.payloads() if p.get("event") == "client.error"
        ]
        assert entries[-1]["level"] == "WARNING"

    def test_empty_message_is_rejected(self, client):
        assert client.post(self.ENDPOINT, json={"message": ""}).status_code == 422

    def test_oversized_payload_is_rejected(self, client):
        response = client.post(self.ENDPOINT, json={"message": "x" * 5000})
        assert response.status_code == 422

    def test_context_is_bounded(self, client, json_capture):
        client.post(
            self.ENDPOINT,
            json={
                "message": "boom",
                "context": {f"k{i}": "v" * 1000 for i in range(50)},
            },
        )
        entries = [
            p for p in json_capture.payloads() if p.get("event") == "client.error"
        ]
        context = entries[-1]["context"]
        assert len(context) <= 20
        assert all(len(value) <= 300 for value in context.values())

    def test_flooding_is_capped(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "CLIENT_ERROR_MAX_PER_WINDOW", 3)

        results = [
            client.post(self.ENDPOINT, json={"message": f"boom {i}"}).json()["recorded"]
            for i in range(6)
        ]
        assert results[0] is True
        assert results[-1] is False, "an error storm must not flood the log pipeline"

    def test_reporting_can_be_disabled(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "CLIENT_ERROR_LOGGING_ENABLED", False)
        response = client.post(self.ENDPOINT, json={"message": "boom"})
        assert response.status_code == 202
        assert response.json()["recorded"] is False


# ── metric alerting ───────────────────────────────────────────────────


class TestMetricsAlerting:
    def test_healthy_metrics_raise_nothing(self):
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route()),
            challenges=_challenges_snapshot(_challenge_key()),
            notify=False,
        )
        assert result["firing"] == []
        assert result["worst_severity"] is None

    def test_slow_route_fires_a_latency_alert(self):
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            notify=False,
        )
        assert [a["rule"] for a in result["firing"]] == [RULE_API_LATENCY]
        assert result["firing"][0]["value"] == 900.0

    def test_a_small_sample_is_not_enough_to_alert(self):
        """A p95 over two requests is noise, not a signal."""
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(
                _route(p95_ms=5000.0, sampled=2, requests=2)
            ),
            challenges=_challenges_snapshot(),
            notify=False,
        )
        assert result["firing"] == []

    def test_severity_escalates_past_the_critical_multiplier(self):
        evaluator = MetricsAlertEvaluator()
        warning = evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=500.0)),
            challenges=_challenges_snapshot(),
            notify=False,
        )
        assert warning["firing"][0]["severity"] == SEVERITY_WARNING

        evaluator.reset()
        critical = evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=1200.0)),
            challenges=_challenges_snapshot(),
            notify=False,
        )
        assert critical["firing"][0]["severity"] == SEVERITY_CRITICAL

    def test_error_rate_alert_is_independent_of_latency(self):
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(requests=100, errors=20)),
            challenges=_challenges_snapshot(),
            notify=False,
        )
        rules = [a["rule"] for a in result["firing"]]
        assert rules == [RULE_API_ERROR_RATE]
        assert result["firing"][0]["value"] == 20.0

    def test_challenge_generation_uses_its_own_budget(self):
        """50ms, not the 400ms API budget — it runs while an alarm is ringing."""
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(),
            challenges=_challenges_snapshot(_challenge_key(p95_ms=120.0)),
            notify=False,
        )
        assert [a["rule"] for a in result["firing"]] == [RULE_CHALLENGE_LATENCY]

    def test_alert_is_new_once_then_merely_active(self):
        evaluator = MetricsAlertEvaluator()
        snapshot = _requests_snapshot(_route(p95_ms=900.0))

        first = evaluator.evaluate(
            requests=snapshot, challenges=_challenges_snapshot(), notify=False, now=0.0
        )
        second = evaluator.evaluate(
            requests=snapshot, challenges=_challenges_snapshot(), notify=False, now=1.0
        )

        assert len(first["new"]) == 1
        assert second["new"] == []
        assert second["active_count"] == 1

    def test_recovery_resolves_the_alert(self):
        evaluator = MetricsAlertEvaluator()
        evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            notify=False,
            now=0.0,
        )
        recovered = evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=12.0)),
            challenges=_challenges_snapshot(),
            notify=False,
            now=30.0,
        )

        assert recovered["firing"] == []
        assert len(recovered["resolved"]) == 1
        assert recovered["resolved"][0]["duration_seconds"] == 30.0

    def test_a_persistent_alert_does_not_notify_every_cycle(self, json_capture):
        evaluator = MetricsAlertEvaluator()
        snapshot = _requests_snapshot(_route(p95_ms=900.0))

        for tick in range(5):
            evaluator.evaluate(
                requests=snapshot,
                challenges=_challenges_snapshot(),
                notify=True,
                now=float(tick),
            )

        firing = [
            p for p in json_capture.payloads() if p.get("event") == "alert.firing"
        ]
        assert len(firing) == 1, "cooldown must suppress repeat notifications"

    def test_cooldown_expiry_re_notifies(self, json_capture):
        from app.core.config import settings

        evaluator = MetricsAlertEvaluator()
        snapshot = _requests_snapshot(_route(p95_ms=900.0))
        cooldown = float(settings.METRICS_ALERT_COOLDOWN_SECONDS)

        evaluator.evaluate(
            requests=snapshot, challenges=_challenges_snapshot(), now=0.0
        )
        evaluator.evaluate(
            requests=snapshot, challenges=_challenges_snapshot(), now=cooldown + 1
        )

        repeats = [
            p for p in json_capture.payloads() if p.get("event") == "alert.still_firing"
        ]
        assert len(repeats) == 1

    def test_notification_is_a_structured_log_record(self, json_capture):
        MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=1500.0)),
            challenges=_challenges_snapshot(),
            notify=True,
        )

        firing = [
            p for p in json_capture.payloads() if p.get("event") == "alert.firing"
        ]
        assert firing
        entry = firing[-1]
        assert entry["level"] == "ERROR"
        assert entry["rule"] == RULE_API_LATENCY
        assert entry["threshold"] == 400.0
        assert entry["target"] == "GET /api/v1/alarms/"

    def test_alert_detail_survives_the_reserved_logrecord_key(self, json_capture):
        """``message`` is reserved; passing it via extra= raises KeyError."""
        MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            notify=True,
        )

        firing = [
            p for p in json_capture.payloads() if p.get("event") == "alert.firing"
        ]
        assert firing
        assert "budget 400ms" in firing[-1]["alert_message"]
        assert firing[-1]["message"].startswith("Metrics alert firing:")

    def test_resolution_is_logged_too(self, json_capture):
        evaluator = MetricsAlertEvaluator()
        evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            now=0.0,
        )
        evaluator.evaluate(
            requests=_requests_snapshot(_route(p95_ms=9.0)),
            challenges=_challenges_snapshot(),
            now=5.0,
        )

        resolved = [
            p for p in json_capture.payloads() if p.get("event") == "alert.resolved"
        ]
        assert resolved

    def test_a_broken_webhook_never_breaks_evaluation(self, monkeypatch, json_capture):
        from app.core.config import settings
        from app.services import metrics_alert_service

        monkeypatch.setattr(
            settings, "METRICS_ALERT_WEBHOOK_URL", "http://127.0.0.1:1/hook"
        )

        def explode(*_args, **_kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(metrics_alert_service.urllib.request, "urlopen", explode)

        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            notify=True,
        )

        assert result["active_count"] == 1
        assert any(
            p.get("event") == "alert.webhook_failed" for p in json_capture.payloads()
        )

    def test_webhook_receives_the_alert_payload(self, monkeypatch):
        from app.core.config import settings
        from app.services import metrics_alert_service

        monkeypatch.setattr(
            settings, "METRICS_ALERT_WEBHOOK_URL", "http://alertmanager/hook"
        )
        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def capture(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _Response()

        monkeypatch.setattr(metrics_alert_service.urllib.request, "urlopen", capture)

        MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=900.0)),
            challenges=_challenges_snapshot(),
            notify=True,
        )

        assert captured["url"] == "http://alertmanager/hook"
        assert captured["body"]["alerts"][0]["rule"] == RULE_API_LATENCY

    def test_disabling_alerts_short_circuits(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "METRICS_ALERTS_ENABLED", False)
        result = MetricsAlertEvaluator().evaluate(
            requests=_requests_snapshot(_route(p95_ms=9000.0)),
            challenges=_challenges_snapshot(),
        )
        assert result["enabled"] is False
        assert result["firing"] == []

    def test_the_scheduler_registers_an_evaluation_job(self):
        from app.services import notification_scheduler

        assert hasattr(notification_scheduler, "_metrics_alert_job")
        notification_scheduler._metrics_alert_job()  # must not raise


# ── prometheus exposition ─────────────────────────────────────────────


class TestPrometheusExposition:
    def test_label_values_are_escaped(self):
        assert escape_label_value('a"b\\c\nd') == 'a\\"b\\\\c\\nd'

    def test_body_ends_with_a_newline(self):
        body = render_prometheus(
            requests=_requests_snapshot(_route()),
            challenges=_challenges_snapshot(_challenge_key()),
        )
        assert body.endswith("\n")

    def test_every_series_has_help_and_type(self):
        body = render_prometheus(
            requests=_requests_snapshot(_route()),
            challenges=_challenges_snapshot(_challenge_key()),
        )
        names = {
            line.split()[2]
            for line in body.splitlines()
            if line.startswith("# HELP")
        }
        typed = {
            line.split()[2]
            for line in body.splitlines()
            if line.startswith("# TYPE")
        }
        assert names == typed

    def test_route_key_is_split_into_method_and_route_labels(self):
        body = render_prometheus(
            requests=_requests_snapshot(_route("GET /api/v1/alarms/{alarm_id}")),
            challenges=_challenges_snapshot(),
        )
        assert 'method="GET"' in body
        assert 'route="/api/v1/alarms/{alarm_id}"' in body

    def test_percentiles_are_exported_as_quantiles(self):
        body = render_prometheus(
            requests=_requests_snapshot(_route(p95_ms=42.5)),
            challenges=_challenges_snapshot(),
        )
        assert 'quantile="0.95"' in body
        assert "42.5" in body

    def test_challenge_series_keep_their_dimensions(self):
        body = render_prometheus(
            requests=_requests_snapshot(),
            challenges=_challenges_snapshot(_challenge_key("riddle/hard/ai", calls=7)),
        )
        assert 'challenge_type="riddle"' in body
        assert 'difficulty="hard"' in body
        assert 'source="ai"' in body
        assert "icap_challenge_generations_total" in body

    def test_active_alerts_are_exported(self):
        body = render_prometheus(
            requests=_requests_snapshot(),
            challenges=_challenges_snapshot(),
            alerts={
                "firing": [
                    {"rule": RULE_API_LATENCY, "severity": SEVERITY_CRITICAL},
                    {"rule": RULE_API_LATENCY, "severity": SEVERITY_CRITICAL},
                ]
            },
        )
        assert (
            f'icap_metrics_alerts_active{{rule="{RULE_API_LATENCY}",'
            f'severity="{SEVERITY_CRITICAL}"}} 2' in body
        )

    def test_empty_metrics_still_render_build_info(self):
        body = render_prometheus(
            requests={}, challenges={}, version="1.0.0", environment="test"
        )
        assert "icap_build_info" in body
        assert 'version="1.0.0"' in body


class TestObservabilityEndpoints:
    def test_prometheus_requires_privileges(self, client):
        assert client.get("/api/v1/system/metrics/prometheus").status_code == 401

    def test_normal_user_cannot_scrape(self, client, auth_headers):
        response = client.get(
            "/api/v1/system/metrics/prometheus", headers=auth_headers
        )
        assert response.status_code == 403

    def test_admin_can_scrape(self, client, admin_headers):
        response = client.get(
            "/api/v1/system/metrics/prometheus", headers=admin_headers
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "icap_build_info" in response.text

    def test_scrape_token_authenticates_a_machine_scraper(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "METRICS_SCRAPE_TOKEN", "s3cret-scrape-token")
        response = client.get(
            "/api/v1/system/metrics/prometheus",
            headers={"Authorization": "Bearer s3cret-scrape-token"},
        )
        assert response.status_code == 200

    def test_wrong_scrape_token_is_rejected(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "METRICS_SCRAPE_TOKEN", "s3cret-scrape-token")
        response = client.get(
            "/api/v1/system/metrics/prometheus",
            headers={"Authorization": "Bearer wrong"},
        )
        assert response.status_code == 401

    def test_exposition_reflects_recorded_traffic(self, client, admin_headers):
        request_latency.reset()
        for _ in range(3):
            client.get("/api/v1/system/status")

        body = client.get(
            "/api/v1/system/metrics/prometheus", headers=admin_headers
        ).text
        assert 'route="/api/v1/system/status"' in body

    def test_alerts_endpoint_requires_admin(self, client, auth_headers):
        assert client.get("/api/v1/system/alerts").status_code == 401
        assert (
            client.get("/api/v1/system/alerts", headers=auth_headers).status_code == 403
        )

    def test_alerts_endpoint_reports_thresholds(self, client, admin_headers):
        body = client.get("/api/v1/system/alerts", headers=admin_headers).json()
        assert body["enabled"] is True
        assert body["thresholds"]["api_p95_ms"] == 400.0
        assert body["thresholds"]["min_observations"] >= 1

    def test_reading_alerts_never_emits_notifications(self, client, admin_headers, json_capture):
        client.get("/api/v1/system/alerts", headers=admin_headers)
        assert not [
            p
            for p in json_capture.payloads()
            if str(p.get("event", "")).startswith("alert.firing")
        ]

    def test_logging_status_endpoint_requires_admin(self, client, auth_headers):
        assert client.get("/api/v1/system/logging").status_code == 401
        assert (
            client.get("/api/v1/system/logging", headers=auth_headers).status_code
            == 403
        )

    def test_logging_status_reports_the_live_configuration(
        self, client, admin_headers
    ):
        body = client.get("/api/v1/system/logging", headers=admin_headers).json()
        assert body["format"] in {"json", "console"}
        assert "console" in body["handlers"]
        assert body["request_id_header"] == "X-Request-ID"

    def test_existing_metrics_endpoint_is_unchanged(self, client, admin_headers):
        """The JSON contract other tooling reads must not have shifted."""
        body = client.get("/api/v1/system/metrics", headers=admin_headers).json()
        assert set(body) == {"requests", "challenge_generation"}
        assert "routes" in body["requests"]
        assert "budget_ms" in body["challenge_generation"]
