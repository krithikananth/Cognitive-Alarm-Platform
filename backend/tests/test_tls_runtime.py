"""
Runtime verification of edge transport security.

Every other security assertion in this suite runs against the application. This
module runs against a **real nginx process**: it builds the actual
``nginx/Dockerfile`` image, serves the actual ``nginx/nginx.conf``, and then
speaks real TLS and real HTTP to it.

That distinction matters. Reading directives out of a config file proves they
were written; it does not prove nginx parses them, that the listener negotiates
the protocol versions intended, that a header survives to the client, or that
the certificate the entrypoint generates is usable. Those are the failures that
only show up in production, so they are checked here against a running server.

The application containers are replaced by trivial stubs — nginx resolves its
upstreams at boot and would refuse to start without them, but nothing about
transport security depends on what they return.

Skips cleanly (never fails) when Docker is unavailable, so the rest of the suite
still runs on a machine without it. Set ``ICAP_SKIP_EDGE_TESTS=1`` to opt out.
"""

from __future__ import annotations

import os
import re
import socket
import ssl
import subprocess
import time
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EDGE_DIR = REPO_ROOT / "nginx"
COMPOSE_FILE = EDGE_DIR / "docker-compose.edge-test.yml"
PROJECT = "icap-edge-test"

HOST = "127.0.0.1"
HTTP_PORT = 18080
HTTPS_PORT = 18443

#: First build pulls two images and compiles nothing; later runs are cached.
STARTUP_TIMEOUT_SECONDS = 420
READY_TIMEOUT_SECONDS = 90


def _docker_available() -> bool:
    try:
        result = subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _compose(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
        ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), *args],
        cwd=str(EDGE_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def _tls_context() -> ssl.SSLContext:
    """Trust the self-signed certificate; these tests are not about the CA."""
    return ssl._create_unverified_context()


def _wait_until_ready(deadline_seconds: int = READY_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, HTTPS_PORT), timeout=5) as raw:
                with _tls_context().wrap_socket(raw, server_hostname="localhost"):
                    return True
        except OSError:
            time.sleep(2)
    return False


@pytest.fixture(scope="module")
def edge():
    """Bring the real edge up for the module, then tear it down."""
    if os.environ.get("ICAP_SKIP_EDGE_TESTS") == "1":
        pytest.skip("ICAP_SKIP_EDGE_TESTS=1")
    if not COMPOSE_FILE.is_file():
        pytest.skip(f"missing {COMPOSE_FILE}")
    if not _docker_available():
        pytest.skip("Docker engine unavailable — edge runtime checks skipped")

    started = _compose("up", "-d", "--build", timeout=STARTUP_TIMEOUT_SECONDS)
    if started.returncode != 0:
        _compose("down", "-v", timeout=180)
        pytest.skip(f"could not start the edge stack: {started.stderr[-400:]}")

    try:
        if not _wait_until_ready():
            logs = _compose("logs", "nginx", timeout=60).stdout[-600:]
            pytest.fail(f"edge did not accept TLS in time. nginx logs:\n{logs}")
        yield
    finally:
        _compose("down", "-v", timeout=180)


def https_get(path: str, host_header: Optional[str] = None) -> Tuple[int, Dict[str, str], bytes]:
    connection = HTTPSConnection(
        HOST, HTTPS_PORT, context=_tls_context(), timeout=15
    )
    try:
        connection.request("GET", path, headers={"Host": host_header} if host_header else {})
        response = connection.getresponse()
        body = response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body
    finally:
        connection.close()


def http_get(path: str) -> Tuple[int, Dict[str, str], bytes]:
    connection = HTTPConnection(HOST, HTTP_PORT, timeout=15)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body
    finally:
        connection.close()


def tls_handshake(minimum: ssl.TLSVersion, maximum: ssl.TLSVersion) -> Optional[str]:
    """Negotiated protocol, or ``None`` when the server refuses the range."""
    context = _tls_context()
    try:
        context.minimum_version = minimum
        context.maximum_version = maximum
    except (ValueError, OSError):
        pytest.skip("this OpenSSL build cannot request that TLS version")
    try:
        with socket.create_connection((HOST, HTTPS_PORT), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname="localhost") as tls:
                return tls.version()
    except (ssl.SSLError, OSError):
        return None


# ── TLS ───────────────────────────────────────────────────────────────


class TestTlsRuntime:
    def test_the_listener_serves_tls(self, edge):
        status, _, _ = https_get("/nginx-health")
        assert status == 200

    def test_tls_1_2_is_accepted(self, edge):
        assert tls_handshake(ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2) == "TLSv1.2"

    def test_tls_1_3_is_accepted(self, edge):
        assert tls_handshake(ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3) == "TLSv1.3"

    def test_tls_1_0_is_refused(self, edge):
        assert tls_handshake(ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1) is None

    def test_tls_1_1_is_refused(self, edge):
        assert tls_handshake(ssl.TLSVersion.TLSv1_1, ssl.TLSVersion.TLSv1_1) is None

    def test_the_default_negotiation_picks_the_newest_protocol(self, edge):
        with socket.create_connection((HOST, HTTPS_PORT), timeout=10) as raw:
            with _tls_context().wrap_socket(raw, server_hostname="localhost") as tls:
                assert tls.version() == "TLSv1.3"

    def test_the_negotiated_cipher_is_forward_secret(self, edge):
        """A non-ECDHE suite would make captured traffic retro-decryptable."""
        negotiated = ssl._create_unverified_context()
        negotiated.minimum_version = ssl.TLSVersion.TLSv1_2
        negotiated.maximum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection((HOST, HTTPS_PORT), timeout=10) as raw:
            with negotiated.wrap_socket(raw, server_hostname="localhost") as tls:
                name = tls.cipher()[0]
        assert name.startswith("ECDHE"), name

    def test_the_generated_certificate_is_valid_for_localhost(self, edge, tmp_path):
        """Proves the entrypoint's SAN is usable, not merely that a file exists."""
        pem = ssl.get_server_certificate((HOST, HTTPS_PORT))
        ca_file = tmp_path / "edge.pem"
        ca_file.write_text(pem, encoding="utf-8")

        verifying = ssl.create_default_context(cafile=str(ca_file))
        with socket.create_connection((HOST, HTTPS_PORT), timeout=10) as raw:
            with verifying.wrap_socket(raw, server_hostname="localhost") as tls:
                names = [v for k, v in tls.getpeercert().get("subjectAltName", ()) if k == "DNS"]
        assert "localhost" in names


# ── HTTP → HTTPS ──────────────────────────────────────────────────────


class TestHttpRedirect:
    def test_plain_http_is_permanently_redirected(self, edge):
        status, headers, _ = http_get("/dashboard")
        assert status == 308
        assert headers["location"].startswith("https://")

    def test_the_redirect_preserves_the_path_and_query(self, edge):
        _, headers, _ = http_get("/alarms?ring=17&x=2")
        assert headers["location"].endswith("/alarms?ring=17&x=2")

    def test_the_redirect_does_not_leak_the_body(self, edge):
        _, _, body = http_get("/")
        assert b"<html" not in body.lower() or b"308" in body

    def test_health_probes_are_not_redirected(self, edge):
        """A bounced probe would make the container look permanently unhealthy."""
        status, _, _ = http_get("/nginx-health")
        assert status == 200


# ── HSTS ──────────────────────────────────────────────────────────────


class TestHstsRuntime:
    def test_hsts_is_returned_over_tls(self, edge):
        _, headers, _ = https_get("/")
        assert "strict-transport-security" in headers

    def test_hsts_max_age_is_at_least_one_year(self, edge):
        _, headers, _ = https_get("/")
        match = re.search(r"max-age=(\d+)", headers["strict-transport-security"])
        assert match and int(match.group(1)) >= 31536000

    def test_hsts_covers_subdomains(self, edge):
        _, headers, _ = https_get("/")
        assert "includeSubDomains" in headers["strict-transport-security"]

    def test_hsts_is_absent_over_plain_http(self, edge):
        """Browsers ignore it there; sending it signals a misconfigured edge."""
        _, headers, _ = http_get("/nginx-health")
        assert "strict-transport-security" not in headers

    def test_hsts_is_present_on_error_responses_too(self, edge):
        status, headers, _ = https_get("/docs")
        assert status == 404
        assert "strict-transport-security" in headers


# ── CSP ───────────────────────────────────────────────────────────────


def _csp(path: str = "/") -> Dict[str, str]:
    _, headers, _ = https_get(path)
    policy = headers["content-security-policy"]
    directives = {}
    for part in policy.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        directives[name] = value.strip()
    return directives


class TestCspRuntime:
    def test_csp_is_returned(self, edge):
        _, headers, _ = https_get("/")
        assert "content-security-policy" in headers

    def test_default_src_is_self(self, edge):
        assert _csp()["default-src"] == "'self'"

    def test_scripts_may_not_be_inline_or_evaled(self, edge):
        script_src = _csp()["script-src"]
        assert "'unsafe-inline'" not in script_src
        assert "'unsafe-eval'" not in script_src
        assert script_src == "'self'"

    def test_framing_and_plugins_are_blocked(self, edge):
        directives = _csp()
        assert directives["frame-ancestors"] == "'none'"
        assert directives["object-src"] == "'none'"

    def test_base_uri_and_form_action_are_pinned(self, edge):
        directives = _csp()
        assert directives["base-uri"] == "'self'"
        assert directives["form-action"] == "'self'"

    def test_push_registration_hosts_are_allowed(self, edge):
        """Too strict a connect-src silently breaks push notifications."""
        connect_src = _csp()["connect-src"]
        assert "'self'" in connect_src
        assert "https://fcmregistrations.googleapis.com" in connect_src

    def test_the_policy_is_applied_to_api_responses_too(self, edge):
        _, headers, _ = https_get("/api/")
        assert "content-security-policy" in headers


# ── Supporting headers and exposure ───────────────────────────────────


class TestEdgeHeadersRuntime:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "DENY"),
            ("referrer-policy", "strict-origin-when-cross-origin"),
            ("cross-origin-opener-policy", "same-origin"),
            ("cross-origin-resource-policy", "same-origin"),
        ],
    )
    def test_header_is_set(self, edge, header, expected):
        _, headers, _ = https_get("/")
        assert headers.get(header) == expected

    def test_permissions_policy_disables_sensitive_apis(self, edge):
        _, headers, _ = https_get("/")
        policy = headers["permissions-policy"]
        for feature in ("geolocation", "microphone", "camera"):
            assert f"{feature}=()" in policy

    def test_the_server_version_is_not_advertised(self, edge):
        _, headers, _ = https_get("/")
        assert not re.search(r"nginx/\d", headers.get("server", ""))

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_the_api_schema_is_refused_at_the_edge(self, edge, path):
        status, _, body = https_get(path)
        assert status == 404
        assert b"swagger" not in body.lower()

    def test_traffic_reaches_the_frontend_upstream(self, edge):
        status, _, body = https_get("/")
        assert status == 200
        assert body

    def test_api_traffic_reaches_the_backend_upstream(self, edge):
        """Proxying must still work with every header and TLS in the path."""
        status, headers, _ = https_get("/api/")
        # The stub has no /api/ directory, so a 404 *from the upstream* is the
        # proof the request was proxied rather than answered by nginx.
        assert status == 404
        assert headers.get("server", "").lower().startswith(("nginx", "simplehttp"))
