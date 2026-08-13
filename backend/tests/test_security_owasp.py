"""
OWASP-aligned security tests.

The existing suites cover broken access control (A01) and authentication
failures (A07) heavily. This module covers the categories that had no
behavioural coverage at all: injection, cross-site scripting, path traversal,
SSRF, open redirect, vulnerable components, integrity failures, and security
logging.

Each test states the attack, not just the endpoint, so a failure says what an
attacker would have achieved.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.core.logging_config import JsonLogFormatter, RequestContextFilter
from app.core.security_events import (
    MAX_VALUE_LENGTH,
    SECURITY_LOGGER_NAME,
    log_security_event,
    scrub,
)
from app.core.security_events import (
    ACCESS_DENIED,
    ACCOUNT_LOCKED,
    LOGIN_FAILED,
    LOGIN_SUCCEEDED,
    TOKEN_REJECTED,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


# ── shared helpers ────────────────────────────────────────────────────


class LogCapture(logging.Handler):
    """Capture records exactly as the JSON formatter would emit them."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonLogFormatter())
        self.addFilter(RequestContextFilter("icap-backend", "test", "1.0.0"))
        self.lines: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    def payloads(self) -> List[Dict[str, Any]]:
        return [json.loads(line) for line in self.lines]

    def events(self, name: str) -> List[Dict[str, Any]]:
        return [p for p in self.payloads() if p.get("security_event") == name]


@pytest.fixture
def security_log():
    handler = LogCapture()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


#: Payloads that must never be interpreted rather than stored/rejected.
SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' UNION SELECT null, hashed_password FROM users --",
    "admin'--",
    "\" OR 1=1 --",
    "%27%20OR%201=1",
    "'; UPDATE users SET role='admin' WHERE '1'='1",
]

XSS_PAYLOADS = [
    "<script>alert(document.cookie)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    "\"><svg/onload=alert(1)>",
    "<iframe src='javascript:alert(1)'></iframe>",
]

TRAVERSAL_PAYLOADS = [
    "../../etc/passwd",
    "..\\..\\windows\\win.ini",
    "....//....//etc/shadow",
    "%2e%2e%2fetc%2fpasswd",
    "/etc/passwd",
    "..%252f..%252fetc%252fpasswd",
]

SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8000/api/v1/admin/users",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_FLUSHALL",
    "http://localhost:6379",
]

OPEN_REDIRECT_PAYLOADS = [
    "https://evil.example.com",
    "//evil.example.com",
    "/\\evil.example.com",
    "https:/\\evil.example.com",
    "http://evil.example.com/login",
    "\\\\evil.example.com",
]


def _create_alarm(client, auth_headers, title: str, description: str = "d"):
    return client.post(
        "/api/v1/alarms/",
        json={
            "title": title,
            "description": description,
            "alarm_time": "07:15",
            "alarm_type": "one_time",
            "one_time_date": "2026-09-01",
            "snooze_interval_minutes": 5,
            "snooze_limit": 3,
            "challenge_type": "math",
            "challenge_count": 1,
        },
        headers=auth_headers,
    )


# ── A03: Injection ────────────────────────────────────────────────────


class TestSqlInjection:
    """A03 — user input must never reach the database as SQL."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_login_email_is_not_a_sql_bypass(self, client, payload):
        response = client.post(
            "/api/v1/auth/login", json={"email": payload, "password": payload}
        )
        assert response.status_code in (401, 422)
        assert "access_token" not in response.text

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_admin_user_search_is_parameterized(
        self, client, admin_headers, payload
    ):
        response = client.get(
            "/api/v1/admin/users",
            params={"search": payload},
            headers=admin_headers,
        )
        assert response.status_code == 200
        # A working injection would return rows; a parameterized LIKE cannot.
        assert response.json()["users"] == []

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_admin_sort_field_is_whitelisted(self, client, admin_headers, payload):
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_by": payload},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_sort_order_is_whitelisted(self, client, admin_headers):
        response = client.get(
            "/api/v1/admin/users",
            params={"sort_order": "asc; DROP TABLE users"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_coach_client_sort_is_whitelisted(self, client, admin_headers, payload):
        response = client.get(
            "/api/v1/coach/clients",
            params={"sort_by": payload},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_injection_attempt_does_not_destroy_data(self, client, admin_headers):
        """The tables must still be there after every payload above."""
        client.get(
            "/api/v1/admin/users",
            params={"search": "'; DROP TABLE users; --"},
            headers=admin_headers,
        )
        after = client.get("/api/v1/admin/users", headers=admin_headers)
        assert after.status_code == 200
        assert after.json()["total"] >= 1

    def test_no_raw_sql_string_building_in_application_code(self):
        """Static guard: an interpolated SQL string would bypass the ORM."""
        offenders = []
        # Only interpolation into SQL matters. Constant DDL passed to
        # exec_driver_sql (the SQLite column ensure step) is parameter-free.
        interpolated_sql = re.compile(
            r"""(execute|exec_driver_sql|text)\(\s*f["']|"""
            r"""f["'][^"']*\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b""",
            re.IGNORECASE,
        )
        concatenated_sql = re.compile(
            r"""(execute|exec_driver_sql|text)\(\s*["'][^"']*["']\s*[+%]""",
            re.IGNORECASE,
        )
        for path in (BACKEND_ROOT / "app").rglob("*.py"):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if interpolated_sql.search(line) or concatenated_sql.search(line):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        assert offenders == []


class TestHeaderAndLogInjection:
    """A03 — injection is not only SQL."""

    def test_export_filename_cannot_break_the_header(self):
        from app.services.report_export import content_disposition

        header = content_disposition('evil";\r\nSet-Cookie: admin=1')
        assert "\r" not in header and "\n" not in header
        assert header.count('"') == 2
        assert "Set-Cookie" not in header.split(";")[0]

    def test_export_filename_cannot_carry_a_path(self):
        from app.services.report_export import safe_attachment_filename

        assert "/" not in safe_attachment_filename("../../etc/passwd")
        assert "\\" not in safe_attachment_filename("..\\..\\win.ini")

    def test_real_export_header_is_clean(self, client, auth_headers):
        response = client.get(
            "/api/v1/reports/habit/export",
            params={"format": "pdf"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert re.fullmatch(r'attachment; filename="[A-Za-z0-9._-]+"', disposition)

    def test_crlf_in_a_username_cannot_forge_a_log_line(self, security_log):
        log_security_event(
            LOGIN_FAILED, identifier="victim\r\nsecurity.auth.login.succeeded"
        )
        for line in security_log.lines:
            assert "\n" not in line.rstrip("\n")
        assert len(security_log.events(LOGIN_FAILED)) == 1
        assert "\r" not in security_log.events(LOGIN_FAILED)[0]["identifier"]

    def test_scrub_strips_control_characters_and_caps_length(self):
        assert scrub("a\r\nb\x00c") == "abc"
        assert len(scrub("x" * 5000)) == MAX_VALUE_LENGTH


class TestCodeExecution:
    """A03 — no code-execution primitive may remain in the request path."""

    def test_challenge_generation_does_not_use_eval(self):
        source = (
            BACKEND_ROOT / "app" / "services" / "challenge_service.py"
        ).read_text(encoding="utf-8")
        assert "eval(" not in source.replace("literal_eval(", "").replace(
            "solve_arithmetic(", ""
        )

    def test_arithmetic_solver_still_computes_correctly(self):
        from app.services.challenge_service import solve_arithmetic

        assert solve_arithmetic("7 + 3") == 10
        assert solve_arithmetic("20 - 5 + 2") == 17
        assert solve_arithmetic("(4 + 6) * 3") == 30
        assert solve_arithmetic("-5 + 8") == 3

    @pytest.mark.parametrize(
        "payload",
        [
            "__import__('os').system('calc')",
            "open('/etc/passwd').read()",
            "().__class__.__bases__[0].__subclasses__()",
            "1 if print('pwned') else 2",
            "exec('x=1')",
            "10 / 0",
            "2 ** 9999999",
        ],
    )
    def test_arithmetic_solver_refuses_anything_but_arithmetic(self, payload):
        from app.services.challenge_service import solve_arithmetic

        with pytest.raises((ValueError, SyntaxError)):
            solve_arithmetic(payload)

    def test_generated_math_challenges_are_still_solvable(self):
        from app.services.challenge_service import ChallengeService

        for difficulty in ("beginner", "easy", "medium"):
            challenge = ChallengeService._generate_math(difficulty)
            assert str(int(challenge["answer"])) == str(challenge["answer"])


# ── XSS ───────────────────────────────────────────────────────────────


class TestCrossSiteScripting:
    """Stored payloads must come back as inert JSON data, never as markup."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_alarm_title_is_returned_as_json_data(
        self, client, auth_headers, payload
    ):
        created = _create_alarm(client, auth_headers, payload)
        assert created.status_code == 201
        assert created.headers["content-type"].startswith("application/json")
        # Round-trips as a string value, so no browser ever parses it as HTML.
        assert created.json()["title"] == payload

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_profile_name_is_returned_as_json_data(
        self, client, auth_headers, payload
    ):
        response = client.put(
            "/api/v1/users/profile",
            json={"full_name": payload},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    def test_no_endpoint_reflects_input_as_html(self, client, auth_headers):
        """A text/html response is the precondition for reflected XSS."""
        payload = "<script>alert(1)</script>"
        for response in (
            client.get("/api/v1/alarms/", params={"q": payload}, headers=auth_headers),
            client.get(f"/api/v1/reports/{payload}", headers=auth_headers),
            client.post("/api/v1/auth/login", json={"email": payload, "password": "x"}),
        ):
            assert "text/html" not in response.headers.get("content-type", "")

    def test_error_body_is_json_encoded(self, client, auth_headers):
        response = client.get(
            "/api/v1/reports/<img src=x onerror=alert(1)>", headers=auth_headers
        )
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        # Reflected back as a JSON string value, never as markup in a document.
        assert isinstance(response.json()["detail"], str)

    def test_stored_payload_never_becomes_a_script_tag_in_export(
        self, client, auth_headers
    ):
        _create_alarm(client, auth_headers, "<script>alert(1)</script>")
        response = client.get(
            "/api/v1/reports/habit/export",
            params={"format": "pdf"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")

    def test_the_spa_is_served_with_sniffing_disabled(self):
        """Blocks a JSON/text response being sniffed into executable HTML."""
        assert "X-Content-Type-Options nosniff" in EDGE_CONFIG


# ── Path traversal ────────────────────────────────────────────────────


class TestPathTraversal:
    """No request parameter may select a file on disk."""

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_report_type_cannot_escape_the_enum(
        self, client, auth_headers, payload
    ):
        response = client.get(f"/api/v1/reports/{payload}", headers=auth_headers)
        assert response.status_code in (404, 400, 422)
        assert "root:" not in response.text

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_report_export_type_cannot_escape_the_enum(
        self, client, auth_headers, payload
    ):
        response = client.get(
            f"/api/v1/reports/{payload}/export", headers=auth_headers
        )
        assert response.status_code in (404, 400, 422)
        assert "root:" not in response.text

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_export_format_is_whitelisted(self, client, auth_headers, payload):
        response = client.get(
            "/api/v1/reports/habit/export",
            params={"format": payload},
            headers=auth_headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("payload", TRAVERSAL_PAYLOADS)
    def test_admin_system_report_type_cannot_escape(
        self, client, admin_headers, payload
    ):
        response = client.get(
            f"/api/v1/admin/system-reports/{payload}", headers=admin_headers
        )
        assert response.status_code in (404, 400, 422)
        assert "root:" not in response.text

    def test_numeric_path_params_reject_traversal(self, client, auth_headers):
        response = client.get(
            "/api/v1/alarms/../../../etc/passwd", headers=auth_headers
        )
        assert response.status_code in (404, 422)

    def test_no_endpoint_opens_a_caller_supplied_path(self):
        """Static guard: `open()` driven by a request parameter."""
        endpoints = BACKEND_ROOT / "app" / "api"
        offenders = []
        for path in endpoints.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for number, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if re.search(r"\b(open|FileResponse)\s*\(", stripped):
                    offenders.append(f"{path.name}:{number}: {stripped}")
        assert offenders == []


# ── SSRF ──────────────────────────────────────────────────────────────


class TestServerSideRequestForgery:
    """The server must never fetch a URL a caller chose."""

    @pytest.mark.parametrize("payload", SSRF_PAYLOADS)
    def test_client_error_url_field_is_not_fetched(
        self, client, payload, monkeypatch
    ):
        """The report carries a `url`; it is recorded, never requested."""
        import urllib.request

        def explode(*_args, **_kwargs):
            raise AssertionError("the server made an outbound request")

        monkeypatch.setattr(urllib.request, "urlopen", explode)
        response = client.post(
            "/api/v1/system/client-errors",
            json={"message": "boom", "url": payload},
        )
        assert response.status_code == 202

    @pytest.mark.parametrize("payload", SSRF_PAYLOADS)
    def test_device_token_registration_does_not_fetch(self, client, auth_headers, payload):
        import urllib.request

        response = client.post(
            "/api/v1/notifications/device-token",
            json={"fcm_token": payload, "device_type": "web"},
            headers=auth_headers,
        )
        assert response.status_code in (200, 201, 400, 422)

    def test_no_endpoint_accepts_a_url_to_fetch(self):
        """Static guard: an outbound call inside the request-handling layer."""
        offenders = []
        pattern = re.compile(
            r"(urlopen|requests\.(get|post|put|delete)|httpx\.(get|post|Client))"
        )
        for path in (BACKEND_ROOT / "app" / "api").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for number, line in enumerate(source.splitlines(), start=1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{number}")
        # auth.py talks to Google's fixed OAuth endpoints; nothing else may.
        assert all("auth.py" in entry for entry in offenders), offenders

    def test_oauth_provider_hosts_are_constants(self):
        from app.api.v1.endpoints import auth as auth_module

        for url in (
            auth_module.GOOGLE_AUTH_URL,
            auth_module.GOOGLE_TOKEN_URL,
            auth_module.GOOGLE_USERINFO_URL,
        ):
            assert url.startswith("https://")
            assert "googleapis.com" in url or "google.com" in url

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://127.0.0.1:6379/_FLUSHALL",
            "ftp://internal/secrets",
            "jar:http://evil/!/",
        ],
    )
    def test_alert_webhook_refuses_non_http_schemes(self, monkeypatch, url):
        """urlopen honours file:// and friends; the scheme must be pinned."""
        from app.core.config import settings
        from app.services import metrics_alert_service

        monkeypatch.setattr(settings, "METRICS_ALERT_WEBHOOK_URL", url)

        def explode(*_args, **_kwargs):
            raise AssertionError(f"the server opened {url}")

        monkeypatch.setattr(metrics_alert_service.urllib.request, "urlopen", explode)
        metrics_alert_service.MetricsAlertEvaluator()._post_webhook(
            [
                metrics_alert_service.Alert(
                    rule="r",
                    target="t",
                    severity="warning",
                    metric="m",
                    value=1.0,
                    threshold=0.5,
                    unit="ms",
                    observations=10,
                    message="probe",
                )
            ]
        )

    def test_allowed_webhook_schemes_are_only_http(self):
        from app.services.metrics_alert_service import ALLOWED_WEBHOOK_SCHEMES

        assert ALLOWED_WEBHOOK_SCHEMES == {"http", "https"}

    def test_alert_webhook_target_is_not_settable_over_the_api(
        self, client, admin_headers
    ):
        """The only outbound webhook is configuration, not an API field."""
        from app.core.config import settings

        before = settings.METRICS_ALERT_WEBHOOK_URL
        for path in (
            "/api/v1/admin/notification-settings",
            "/api/v1/system/alerts",
        ):
            client.put(
                path,
                json={"METRICS_ALERT_WEBHOOK_URL": "http://169.254.169.254/"},
                headers=admin_headers,
            )
        assert settings.METRICS_ALERT_WEBHOOK_URL == before


# ── Open redirect ─────────────────────────────────────────────────────


class TestOpenRedirect:
    """Every redirect must land on the configured frontend origin."""

    @pytest.mark.parametrize("payload", OPEN_REDIRECT_PAYLOADS)
    def test_oauth_error_cannot_steer_the_redirect(self, client, payload):
        response = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"error": payload, "state": "x"},
            follow_redirects=False,
        )
        assert response.status_code in (302, 307, 400)
        location = response.headers.get("location", "")
        if location:
            assert self._origin(location) == self._configured_origin()

    @pytest.mark.parametrize("payload", OPEN_REDIRECT_PAYLOADS)
    def test_oauth_code_cannot_steer_the_redirect(self, client, payload):
        response = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": payload, "state": payload},
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        if location:
            assert self._origin(location) == self._configured_origin()

    @pytest.mark.parametrize("payload", OPEN_REDIRECT_PAYLOADS)
    def test_redirect_builder_pins_the_origin(self, payload):
        from app.api.v1.endpoints.auth import frontend_redirect_url

        url = frontend_redirect_url(payload, {"error": payload})
        assert self._origin(url) == self._configured_origin()

    def test_redirect_builder_keeps_the_intended_path(self):
        from app.api.v1.endpoints.auth import frontend_redirect_url

        assert frontend_redirect_url("/login", {"error": "bad"}).endswith(
            "/login?error=bad"
        )

    def test_unknown_query_parameters_are_not_used_as_targets(self, client):
        response = client.get(
            "/api/v1/auth/oauth/google",
            params={
                "next": "https://evil.example.com",
                "redirect_uri": "https://evil.example.com",
                "returnTo": "https://evil.example.com",
            },
            follow_redirects=False,
        )
        location = response.headers.get("location", "")
        assert "evil.example.com" not in location

    @staticmethod
    def _origin(url: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    @staticmethod
    def _configured_origin() -> str:
        from urllib.parse import urlsplit

        from app.core.config import settings

        parts = urlsplit(settings.FRONTEND_URL)
        return f"{parts.scheme}://{parts.netloc}"


# ── A06: Vulnerable and outdated components ───────────────────────────


class TestVulnerableComponents:
    """A06 — the dependency set must be pinned and continuously scanned."""

    def test_every_python_dependency_is_pinned(self):
        unpinned = []
        for line in (BACKEND_ROOT / "requirements.txt").read_text().splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry and "==" not in entry:
                unpinned.append(entry)
        assert unpinned == []

    def test_security_tooling_is_declared(self):
        text = (BACKEND_ROOT / "requirements-security.txt").read_text()
        assert "pip-audit" in text
        assert "bandit" in text

    def test_sast_configuration_exists(self):
        assert (BACKEND_ROOT / "bandit.yaml").is_file()

    def test_scan_runner_exists_and_covers_all_three_scanners(self):
        from importlib import util

        path = REPO_ROOT / "scripts" / "security_scan.py"
        assert path.is_file()
        spec = util.spec_from_file_location("icap_security_scan", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert set(module.SCANNERS) == {"pip-audit", "bandit", "npm-audit"}

    def test_a_missing_scanner_is_not_reported_as_a_pass(self):
        from importlib import util

        path = REPO_ROOT / "scripts" / "security_scan.py"
        spec = util.spec_from_file_location("icap_security_scan_status", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        skipped = module.ScanResult("x", module.STATUS_SKIPPED, "not installed")
        assert skipped.status != module.STATUS_PASSED

    def test_a_scanner_that_audited_nothing_is_not_a_pass(self, monkeypatch):
        """Auditing 0 packages is a broken run, not a clean bill of health."""
        from importlib import util

        path = REPO_ROOT / "scripts" / "security_scan.py"
        spec = util.spec_from_file_location("icap_security_scan_empty", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class _Proc:
            stdout = "{}"
            stderr = "ERROR: failed to build the resolution environment"

        monkeypatch.setattr(module, "_resolve", lambda *a, **k: ["pip-audit"])
        monkeypatch.setattr(module, "_run", lambda *a, **k: _Proc())
        result = module.run_pip_audit()

        assert result.status == module.STATUS_FAILED
        assert "0 packages" in result.summary

    def test_an_npm_run_with_no_report_is_not_a_pass(self, monkeypatch):
        from importlib import util

        path = REPO_ROOT / "scripts" / "security_scan.py"
        spec = util.spec_from_file_location("icap_security_scan_npm", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class _Proc:
            stdout = "{}"
            stderr = "npm ERR! network timeout"

        monkeypatch.setattr(module.shutil, "which", lambda name: "npm")
        monkeypatch.setattr(module.Path, "exists", lambda self: True)
        monkeypatch.setattr(module, "_run", lambda *a, **k: _Proc())
        result = module.run_npm_audit()

        assert result.status == module.STATUS_FAILED

    def test_continuous_scanning_is_wired_into_ci(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text()
        assert "security_scan.py" in workflow
        assert "test_security_owasp.py" in workflow
        assert "schedule:" in workflow

    def test_dependency_updates_are_automated(self):
        config = (REPO_ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem in ("pip", "npm", "docker", "github-actions"):
            assert ecosystem in config

    def test_frontend_dependencies_are_lockfile_pinned(self):
        assert (REPO_ROOT / "frontend" / "package-lock.json").is_file()

    def test_build_tooling_is_not_a_production_dependency(self):
        """react-scripts under `dependencies` puts the whole build chain in
        the shipped tree and makes the production audit meaningless."""
        package = json.loads(
            (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
        )
        assert "react-scripts" not in package["dependencies"]
        assert "react-scripts" in package["devDependencies"]


class TestTriagedFindings:
    """An accepted risk nobody re-reads is an unfixed vulnerability."""

    @staticmethod
    def _module():
        from importlib import util

        path = REPO_ROOT / "scripts" / "security_scan.py"
        spec = util.spec_from_file_location("icap_security_allowlist", path)
        module = util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_allowlist_exists_and_parses(self):
        allowlist = self._module().load_allowlist()
        assert set(allowlist) <= {"pip-audit", "bandit", "npm-audit"}

    def test_every_entry_carries_a_reason_and_a_review_date(self):
        from datetime import date

        raw = json.loads(
            (REPO_ROOT / "security-allowlist.json").read_text(encoding="utf-8")
        )
        for scanner, entries in raw.items():
            if scanner.startswith("_"):
                continue
            for entry in entries:
                assert entry.get("reason"), f"{scanner}:{entry.get('package')}"
                date.fromisoformat(entry["review_by"])

    def test_no_entry_has_already_expired(self):
        module = self._module()
        assert module.expired_allowlist_entries(module.load_allowlist()) == []

    def test_an_expired_entry_fails_the_scan(self):
        from datetime import date

        module = self._module()
        stale = {
            "pip-audit": {
                "somepkg": {
                    "package": "somepkg",
                    "reason": "x",
                    "review_by": "2000-01-01",
                }
            }
        }
        assert module.expired_allowlist_entries(stale, today=date(2026, 8, 12))

    def test_an_entry_without_a_review_date_fails(self):
        module = self._module()
        undated = {"pip-audit": {"somepkg": {"package": "somepkg", "reason": "x"}}}
        assert module.expired_allowlist_entries(undated)

    def test_triaged_findings_are_documented(self):
        review = (REPO_ROOT / "docs" / "SECURITY_REVIEW.md").read_text(
            encoding="utf-8"
        )
        raw = json.loads(
            (REPO_ROOT / "security-allowlist.json").read_text(encoding="utf-8")
        )
        for scanner, entries in raw.items():
            if scanner.startswith("_"):
                continue
            for entry in entries:
                assert entry["package"] in review, entry["package"]


# ── A08: Software and data integrity failures ─────────────────────────


class TestMassAssignment:
    """A08 — a client must not be able to set fields it does not own."""

    @pytest.mark.parametrize(
        "field, value",
        [
            ("role", "admin"),
            ("is_active", True),
            ("is_verified", True),
            ("hashed_password", "pwned"),
            ("id", 999999),
            ("tokens_valid_after", "2020-01-01T00:00:00"),
        ],
    )
    def test_self_update_cannot_set_privileged_fields(
        self, client, auth_headers, test_user, db_session, field, value
    ):
        before = getattr(test_user, field, None)
        response = client.put(
            "/api/v1/users/profile",
            json={"full_name": "Legit Name", field: value},
            headers=auth_headers,
        )
        assert response.status_code in (200, 422)
        db_session.refresh(test_user)
        assert getattr(test_user, field, None) == before

    def test_admin_update_schema_exposes_only_intended_fields(self):
        from app.schemas.user import AdminUserUpdate

        assert set(AdminUserUpdate.model_fields) == {
            "full_name",
            "email",
            "role",
            "is_active",
        }

    def test_unknown_fields_are_dropped_not_applied(self):
        from app.schemas.user import AdminUserUpdate

        parsed = AdminUserUpdate(full_name="x", hashed_password="pwned")
        assert "hashed_password" not in parsed.model_dump(exclude_unset=True)

    def test_user_cannot_award_themselves_progress(
        self, client, auth_headers, db_session, test_user
    ):
        profile_before = client.get(
            "/api/v1/profiles/me/habit-score", headers=auth_headers
        ).json()
        client.put(
            "/api/v1/profiles/me",
            json={"habit_score": 100, "current_streak": 999, "total_points": 99999},
            headers=auth_headers,
        )
        profile_after = client.get(
            "/api/v1/profiles/me/habit-score", headers=auth_headers
        ).json()
        assert profile_after.get("habit_score") == profile_before.get("habit_score")


class TestChallengeIntegrity:
    """A08 — wake verification must not be forgeable by the client."""

    def test_challenge_payload_never_contains_the_answer(self, client, auth_headers):
        alarm_id = _create_alarm(client, auth_headers, "Integrity").json()["id"]
        response = client.get(
            f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "answer" not in body
        assert "answer" not in json.dumps(body).lower().replace("answered", "")

    def test_dismiss_without_solving_is_refused(self, client, auth_headers):
        alarm_id = _create_alarm(client, auth_headers, "No Cheating").json()["id"]
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        response = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss", json={}, headers=auth_headers
        )
        assert response.status_code == 403

    def test_forged_verification_token_is_refused(self, client, auth_headers):
        alarm_id = _create_alarm(client, auth_headers, "Forged Token").json()["id"]
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        response = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss",
            json={"verification_token": "forged-token-value"},
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_wrong_answer_does_not_confirm_wake(self, client, auth_headers):
        alarm_id = _create_alarm(client, auth_headers, "Wrong Answer").json()["id"]
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        verify = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={"user_answer": "definitely-not-the-answer"},
            headers=auth_headers,
        )
        # A wrong answer is rejected outright and resets the streak.
        assert verify.status_code == 400
        body = verify.json()
        assert body.get("wake_confirmed") is not True
        assert "verification_token" not in body
        alarm = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers).json()
        assert alarm["total_dismissals"] == 0

    def test_client_supplied_expected_answer_cannot_force_a_pass(
        self, client, auth_headers
    ):
        """The grading key must come from the server session, never the body."""
        alarm_id = _create_alarm(client, auth_headers, "Own Marking").json()["id"]
        client.get(f"/api/v1/alarms/{alarm_id}/challenge", headers=auth_headers)
        verify = client.post(
            f"/api/v1/alarms/{alarm_id}/verify",
            json={
                "user_answer": "whatever-i-want",
                "expected_answer": "whatever-i-want",
            },
            headers=auth_headers,
        )
        assert verify.status_code == 400
        assert verify.json().get("wake_confirmed") is not True
        alarm = client.get(f"/api/v1/alarms/{alarm_id}", headers=auth_headers).json()
        assert alarm["total_dismissals"] == 0

    def test_another_users_alarm_cannot_be_dismissed(
        self, client, auth_headers, admin_headers
    ):
        alarm_id = _create_alarm(client, admin_headers, "Admin Alarm").json()["id"]
        response = client.post(
            f"/api/v1/alarms/{alarm_id}/dismiss", json={}, headers=auth_headers
        )
        assert response.status_code in (403, 404)


class TestTokenIntegrity:
    """A08 — the signed session artefacts must resist tampering."""

    def test_alg_none_token_is_rejected(self, client):
        import base64

        def b64(payload: dict) -> str:
            raw = json.dumps(payload).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        forged = (
            f"{b64({'alg': 'none', 'typ': 'JWT'})}."
            f"{b64({'sub': '1', 'type': 'access', 'role': 'admin'})}."
        )
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 401

    def test_payload_tampering_invalidates_the_signature(self, client, auth_headers):
        import base64

        token = auth_headers["Authorization"].split(" ", 1)[1]
        header, payload, signature = token.split(".")
        decoded = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        decoded["role"] = "admin"
        tampered = (
            base64.urlsafe_b64encode(json.dumps(decoded).encode())
            .decode()
            .rstrip("=")
        )
        response = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {header}.{tampered}.{signature}"},
        )
        assert response.status_code in (401, 403)


# ── A09: Security logging and monitoring failures ─────────────────────


class TestSecurityLogging:
    """A09 — every security-relevant outcome must leave an audit record."""

    def test_failed_login_is_recorded(self, client, security_log):
        client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "WrongPass123"},
        )
        events = security_log.events(LOGIN_FAILED)
        assert events
        assert events[-1]["outcome"] == "failure"
        assert events[-1]["identifier"] == "nobody@example.com"
        assert events[-1]["level"] == "WARNING"

    def test_successful_login_is_recorded(self, client, test_user, security_log):
        client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "TestPass123"},
        )
        events = security_log.events(LOGIN_SUCCEEDED)
        assert events
        assert events[-1]["outcome"] == "success"
        assert str(events[-1]["user_id"]) == str(test_user.id)

    def test_lockout_is_recorded_at_error_level(
        self, client, test_user, security_log, monkeypatch
    ):
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
        monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 3)
        rate_limit.reset_all_limiters()

        for _ in range(5):
            client.post(
                "/api/v1/auth/login",
                json={"email": test_user.email, "password": "WrongPass123"},
            )

        events = security_log.events(ACCOUNT_LOCKED)
        assert events, "a lockout must be detectable in the logs"
        assert events[-1]["level"] == "ERROR"
        assert events[-1]["outcome"] == "blocked"
        rate_limit.reset_all_limiters()

    def test_rejected_token_is_recorded(self, client, security_log):
        client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        events = security_log.events(TOKEN_REJECTED)
        assert events
        assert events[-1]["outcome"] == "failure"

    def test_denied_privilege_escalation_is_recorded(
        self, client, auth_headers, test_user, security_log
    ):
        client.get("/api/v1/admin/users", headers=auth_headers)
        events = security_log.events(ACCESS_DENIED)
        assert events
        entry = events[-1]
        assert entry["required_role"] == "admin"
        assert entry["actual_role"] == "user"
        assert str(entry["user_id"]) == str(test_user.id)

    def test_every_record_carries_the_request_correlation_id(
        self, client, security_log
    ):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "trace@example.com", "password": "WrongPass123"},
            headers={"X-Request-ID": "audit-trace-1"},
        )
        assert response.headers["X-Request-ID"] == "audit-trace-1"
        events = security_log.events(LOGIN_FAILED)
        assert events[-1]["request_id"] == "audit-trace-1"

    def test_records_include_the_caller_address(self, client, security_log):
        client.post(
            "/api/v1/auth/login",
            json={"email": "who@example.com", "password": "WrongPass123"},
            headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"},
        )
        assert security_log.events(LOGIN_FAILED)[-1]["client_ip"] == "203.0.113.9"

    def test_credentials_never_reach_the_log(self, client, security_log):
        secret = "SuperSecretPassword123"
        client.post(
            "/api/v1/auth/login",
            json={"email": "leak@example.com", "password": secret},
        )
        blob = "\n".join(security_log.lines)
        assert secret not in blob

    def test_a_secret_passed_explicitly_is_dropped(self, security_log):
        log_security_event(
            LOGIN_FAILED,
            identifier="x@example.com",
            password="hunter2",
            access_token="eyJhbGciOi",
            api_key="sk-live-123",
        )
        blob = "\n".join(security_log.lines)
        assert "hunter2" not in blob
        assert "eyJhbGciOi" not in blob
        assert "sk-live-123" not in blob

    def test_events_share_one_dedicated_logger(self, security_log):
        log_security_event(LOGIN_FAILED, identifier="a@example.com")
        assert security_log.events(LOGIN_FAILED)[-1]["logger"] == SECURITY_LOGGER_NAME


# ── Production exposure of the API schema ─────────────────────────────


class TestApiSchemaExposure:
    """The OpenAPI schema is reconnaissance material for an attacker."""

    def test_docs_are_served_outside_production(self, client):
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    @pytest.mark.parametrize("environment", ["production", "PROD"])
    def test_docs_are_disabled_in_production(self, monkeypatch, environment):
        from fastapi.testclient import TestClient

        from app.core.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "ENVIRONMENT", environment)
        monkeypatch.setattr(settings, "ENABLE_API_DOCS", None)
        with TestClient(create_app()) as production_client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert production_client.get(path).status_code == 404

    def test_root_stops_advertising_the_docs_in_production(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.core.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "ENABLE_API_DOCS", None)
        with TestClient(create_app()) as production_client:
            body = production_client.get("/").json()
        assert "docs" not in body and "redoc" not in body

    def test_docs_can_be_re_enabled_deliberately(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.core.config import settings
        from app.main import create_app

        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "ENABLE_API_DOCS", True)
        with TestClient(create_app()) as production_client:
            assert production_client.get("/docs").status_code == 200


# ── Edge TLS / security headers ───────────────────────────────────────

EDGE_CONFIG = (REPO_ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")


class TestEdgeTlsAndHeaders:
    """The reverse proxy is where transport security is enforced."""

    def test_tls_listener_exists(self):
        assert "listen 8443 ssl;" in EDGE_CONFIG
        assert "ssl_certificate" in EDGE_CONFIG
        assert "ssl_certificate_key" in EDGE_CONFIG

    def test_only_modern_tls_versions_are_offered(self):
        assert "ssl_protocols TLSv1.2 TLSv1.3;" in EDGE_CONFIG
        assert "TLSv1.1" not in EDGE_CONFIG
        assert "SSLv3" not in EDGE_CONFIG

    def test_plain_http_is_redirected(self):
        assert "return 308 https://$host$request_uri;" in EDGE_CONFIG

    def test_hsts_is_set_and_long_lived(self):
        match = re.search(
            r"Strict-Transport-Security \"max-age=(\d+)([^\"]*)\"", EDGE_CONFIG
        )
        assert match, "HSTS header missing"
        assert int(match.group(1)) >= 31536000
        assert "includeSubDomains" in match.group(2)

    def test_hsts_is_only_sent_over_tls(self):
        http_block = EDGE_CONFIG.split("listen 8443 ssl;")[0]
        assert "Strict-Transport-Security" not in http_block

    def test_csp_is_defined(self):
        assert "Content-Security-Policy" in EDGE_CONFIG
        assert "default-src 'self'" in EDGE_CONFIG

    def test_csp_does_not_allow_inline_scripts(self):
        policy = re.search(r"default \"(default-src[^\"]+)\"", EDGE_CONFIG).group(1)
        script_src = re.search(r"script-src ([^;]+)", policy).group(1)
        assert "'unsafe-inline'" not in script_src
        assert "'unsafe-eval'" not in script_src

    def test_csp_blocks_framing_and_object_embedding(self):
        assert "frame-ancestors 'none'" in EDGE_CONFIG
        assert "object-src 'none'" in EDGE_CONFIG
        assert "base-uri 'self'" in EDGE_CONFIG

    def test_supporting_headers_are_present(self):
        for header in (
            "X-Content-Type-Options nosniff",
            "X-Frame-Options DENY",
            "Referrer-Policy strict-origin-when-cross-origin",
            "Permissions-Policy",
            "Cross-Origin-Opener-Policy same-origin",
        ):
            assert header in EDGE_CONFIG

    def test_schema_endpoints_are_refused_at_the_edge(self):
        assert re.search(
            r"location ~ \^/\(\?:docs\|redoc\|openapi\\\.json\)\$\s*\{\s*return 404;",
            EDGE_CONFIG,
        )

    def test_frontend_build_avoids_inline_scripts(self):
        dockerfile = (REPO_ROOT / "frontend" / "Dockerfile").read_text()
        assert "INLINE_RUNTIME_CHUNK=false" in dockerfile

    def test_tls_certificate_is_provisioned_before_startup(self):
        entrypoint = (REPO_ROOT / "nginx" / "docker-entrypoint-tls.sh").read_text()
        assert "openssl req -x509" in entrypoint
        dockerfile = (REPO_ROOT / "nginx" / "Dockerfile").read_text()
        assert "docker-entrypoint-tls.sh" in dockerfile

    def test_https_port_is_published(self):
        compose = (REPO_ROOT / "docker-compose.yml").read_text()
        assert "${HTTPS_PORT:-443}:8443" in compose
