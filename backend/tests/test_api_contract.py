"""
API contract tests: full route inventory, response-model policy, and
OpenAPI schema-drift detection.

``test_qa_api_inventory.py`` checks a hand-written list of 28 GET routes. That
leaves most of the surface — every POST, PUT, PATCH and DELETE, and every route
added since the list was written — unchecked. This module derives its
expectations from the application itself, so a new route is covered the moment
it is registered rather than when somebody remembers to extend a list.

Three things are enforced:

* **Policy** — every route declares a response model, a summary and tags, and
  is either authenticated or on a reviewed public allowlist.
* **Conformance** — live responses are validated against the response model the
  route declares, so the schema describes what is actually sent.
* **Drift** — the committed snapshot in ``api_contract_snapshot.json`` must
  match the generated OpenAPI document. Any addition, removal or change to a
  route's contract fails until the snapshot is regenerated deliberately.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest
from fastapi.routing import APIRoute

from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = Path(__file__).parent / "api_contract_snapshot.json"

#: Set to 1 to rewrite the snapshot after an intentional contract change.
REGENERATE = os.environ.get("ICAP_UPDATE_API_SNAPSHOT") == "1"


# ── Reviewed exemptions ───────────────────────────────────────────────

#: Routes that legitimately return no JSON body. Each entry is a deliberate
#: decision, not an oversight, so the policy test can stay absolute.
NO_RESPONSE_MODEL: Set[Tuple[str, str]] = {
    # 302 redirects back to the SPA.
    ("GET", "/api/v1/auth/oauth/google"),
    ("GET", "/api/v1/auth/oauth/google/callback"),
    # 204 No Content — a body would violate the status code.
    ("DELETE", "/api/v1/users/account"),
    ("DELETE", "/api/v1/users/{user_id}"),
    ("DELETE", "/api/v1/alarms/{alarm_id}"),
    ("DELETE", "/api/v1/recommendations/{recommendation_id}/feedback"),
    ("DELETE", "/api/v1/admin/coach-assignments"),
    # Binary downloads; the media type is chosen at runtime (pdf/xlsx).
    ("GET", "/api/v1/reports/{report_type}/export"),
    ("GET", "/api/v1/admin/system-reports/{report_type}/export"),
    # Prometheus text exposition format, not JSON.
    ("GET", "/api/v1/system/metrics/prometheus"),
}

#: Routes reachable without a session, and why.
PUBLIC_ROUTES: Set[Tuple[str, str]] = {
    ("GET", "/"),                                   # service identity
    ("GET", "/health"),                             # container probe
    ("GET", "/api/v1/system/status"),               # maintenance banner
    ("POST", "/api/v1/system/client-errors"),       # crashes pre-login
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/token"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/reset-password"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/resend-verification"),
    ("GET", "/api/v1/auth/oauth/google"),
    ("GET", "/api/v1/auth/oauth/google/callback"),
    # Admin *or* a Prometheus scrape token, so it has no user dependency.
    ("GET", "/api/v1/system/metrics/prometheus"),
}


def api_routes() -> List[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def route_pairs() -> List[Tuple[str, str, APIRoute]]:
    pairs = []
    for route in api_routes():
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            pairs.append((method, route.path, route))
    return sorted(pairs, key=lambda p: (p[1], p[0]))


ALL_PAIRS = route_pairs()


def _model_name(route: APIRoute) -> str:
    model = route.response_model
    return getattr(model, "__name__", str(model)) if model is not None else ""


def build_snapshot() -> Dict[str, Any]:
    """The contract, reduced to what a consumer actually depends on."""
    return {
        "routes": {
            f"{method} {path}": {
                "response_model": _model_name(route),
                "status_code": route.status_code,
                "tags": sorted(str(t) for t in (route.tags or [])),
                "path_params": sorted(
                    p.name for p in route.dependant.path_params
                ),
            }
            for method, path, route in ALL_PAIRS
        }
    }


@pytest.fixture(scope="module")
def openapi() -> Dict[str, Any]:
    return app.openapi()


# ── Inventory ─────────────────────────────────────────────────────────


class TestRouteInventory:
    def test_the_surface_is_not_empty(self):
        assert len(ALL_PAIRS) > 100

    def test_every_method_is_covered_not_just_get(self):
        methods = {method for method, _, _ in ALL_PAIRS}
        assert {"GET", "POST", "PUT", "DELETE"} <= methods

    def test_every_route_is_uniquely_identified(self):
        keys = [f"{m} {p}" for m, p, _ in ALL_PAIRS]
        duplicates = {k for k in keys if keys.count(k) > 1}
        assert duplicates == set()

    def test_operation_ids_are_unique(self):
        """Duplicates silently break generated clients."""
        names = [route.name for _, _, route in ALL_PAIRS]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        assert duplicates == []

    def test_every_route_is_versioned(self):
        unversioned = [
            f"{m} {p}"
            for m, p, _ in ALL_PAIRS
            if not p.startswith("/api/v1") and (m, p) not in PUBLIC_ROUTES
        ]
        assert unversioned == []

    def test_every_route_declares_a_summary(self):
        missing = [
            f"{m} {p}"
            for m, p, route in ALL_PAIRS
            if not (route.summary or route.description)
        ]
        assert missing == []

    def test_every_api_route_declares_tags(self):
        missing = [
            f"{m} {p}"
            for m, p, route in ALL_PAIRS
            if p.startswith("/api/v1") and not route.tags
        ]
        assert missing == []

    def test_path_parameters_are_declared(self):
        """A `{param}` with no matching handler argument is a 500 waiting."""
        for method, path, route in ALL_PAIRS:
            declared = {p.name for p in route.dependant.path_params}
            in_path = {
                segment[1:-1]
                for segment in path.split("/")
                if segment.startswith("{") and segment.endswith("}")
            }
            assert in_path <= declared, f"{method} {path} missing {in_path - declared}"


# ── Response-model policy ─────────────────────────────────────────────


class TestResponseModelPolicy:
    def test_every_route_declares_a_response_model(self):
        missing = sorted(
            f"{m} {p}"
            for m, p, route in ALL_PAIRS
            if route.response_model is None and (m, p) not in NO_RESPONSE_MODEL
        )
        assert missing == [], (
            "These routes return an undocumented shape. Add a response model, "
            "or add them to NO_RESPONSE_MODEL with a reason."
        )

    def test_the_exemption_list_has_no_stale_entries(self):
        """An exemption that gained a model must be removed from the list."""
        registered = {(m, p): route for m, p, route in ALL_PAIRS}
        stale = sorted(
            f"{m} {p}"
            for (m, p) in NO_RESPONSE_MODEL
            if (m, p) not in registered or registered[(m, p)].response_model is not None
        )
        assert stale == []

    def test_coverage_is_effectively_complete(self):
        modelled = sum(1 for _, _, r in ALL_PAIRS if r.response_model is not None)
        assert modelled / len(ALL_PAIRS) >= 0.9

    def test_no_content_routes_declare_no_body(self):
        for method, path, route in ALL_PAIRS:
            if route.status_code == 204:
                assert route.response_model is None, f"{method} {path}"

    def test_every_response_model_reaches_the_openapi_schema(self, openapi):
        components = set(openapi.get("components", {}).get("schemas", {}))
        missing = []
        for method, path, route in ALL_PAIRS:
            if route.response_model is None:
                continue
            name = _model_name(route)
            # Generic containers (List[...]) are inlined rather than named.
            if name and name[0].isupper() and name not in components:
                responses = openapi["paths"][path][method.lower()]["responses"]
                ok = responses.get("200") or responses.get("201") or {}
                if not ok.get("content"):
                    missing.append(f"{method} {path} -> {name}")
        assert missing == []


# ── Authentication policy ─────────────────────────────────────────────


class TestAuthenticationPolicy:
    def test_every_non_public_route_rejects_anonymous_access(self, client):
        """Derived from the app, so a new unguarded route fails immediately."""
        leaked = []
        for method, path, route in ALL_PAIRS:
            if (method, path) in PUBLIC_ROUTES:
                continue
            concrete = path
            for name in (p.name for p in route.dependant.path_params):
                concrete = concrete.replace(f"{{{name}}}", "1")
            response = client.request(method, concrete)
            if response.status_code not in (401, 403):
                leaked.append(f"{method} {path} -> {response.status_code}")
        assert leaked == []

    def test_public_routes_are_all_registered(self):
        registered = {(m, p) for m, p, _ in ALL_PAIRS}
        assert {r for r in PUBLIC_ROUTES if r not in registered} == set()


# ── Live conformance ──────────────────────────────────────────────────

#: Endpoints exercised against their declared model. Chosen because they are
#: the aggregate payloads whose shape drifts most easily.
CONFORMANCE_GETS = [
    "/api/v1/dashboard/summary",
    "/api/v1/dashboard/alarm-history",
    "/api/v1/dashboard/wake-stats",
    "/api/v1/dashboard/challenge-performance",
    "/api/v1/dashboard/productivity",
    "/api/v1/users/profile",
    "/api/v1/users/profile/stats",
    "/api/v1/users/profile/preferences",
    "/api/v1/profiles/me/habit-score",
    "/api/v1/alarms/wake-confirmations",
    "/api/v1/alarms/snooze-history",
    "/api/v1/alarms/wakefulness",
    "/api/v1/alarms/challenge/stats",
    "/api/v1/alarms/challenge/history",
    "/api/v1/alarms/challenge/analysis",
    "/api/v1/alarms/challenge/learning-profile",
    "/api/v1/alarms/challenge/log-health",
]

CONFORMANCE_ADMIN_GETS = [
    "/api/v1/admin/dashboard",
    "/api/v1/admin/users",
    "/api/v1/admin/statistics",
    "/api/v1/admin/recommendations",
    "/api/v1/admin/alarms",
    "/api/v1/admin/analytics",
    "/api/v1/admin/reports",
    "/api/v1/system/metrics",
]


def _model_for(path: str, method: str = "GET"):
    for m, p, route in ALL_PAIRS:
        if p == path and m == method:
            return route.response_model
    raise AssertionError(f"{method} {path} is not registered")


class TestLiveConformance:
    @pytest.mark.parametrize("path", CONFORMANCE_GETS)
    def test_user_payload_matches_its_declared_model(self, client, auth_headers, path):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200, response.text
        _model_for(path).model_validate(response.json())

    @pytest.mark.parametrize("path", CONFORMANCE_ADMIN_GETS)
    def test_admin_payload_matches_its_declared_model(
        self, client, admin_headers, path
    ):
        response = client.get(path, headers=admin_headers)
        assert response.status_code == 200, response.text
        _model_for(path).model_validate(response.json())

    @pytest.mark.parametrize("path", CONFORMANCE_GETS)
    def test_declared_fields_are_actually_present(self, client, auth_headers, path):
        """A model may allow extras, but its required fields must be real."""
        body = client.get(path, headers=auth_headers).json()
        model = _model_for(path)
        required = {
            name
            for name, field in model.model_fields.items()
            if field.is_required()
        }
        assert required <= set(body), f"{path} missing {required - set(body)}"

    def test_aggregate_models_do_not_silently_drop_fields(
        self, client, auth_headers
    ):
        """The whole reason these models allow extras.

        A strict model filters the response, deleting any key it does not
        declare. This asserts the nested blocks the frontend reads survive.
        """
        body = client.get(
            "/api/v1/dashboard/productivity", headers=auth_headers
        ).json()
        for key in ("sleep_patterns", "correlations", "productivity_improvement"):
            assert key in body, f"{key} was filtered out of the response"
        assert isinstance(body["habit_score_breakdown"], dict)


# ── Schema drift ──────────────────────────────────────────────────────


class TestOpenApiSchema:
    def test_the_document_generates(self, openapi):
        assert openapi["openapi"].startswith("3.")
        assert openapi["info"]["title"]

    def test_every_route_appears_in_the_document(self, openapi):
        documented = {
            (method.upper(), path)
            for path, operations in openapi["paths"].items()
            for method in operations
        }
        registered = {(m, p) for m, p, _ in ALL_PAIRS}
        assert registered - documented == set()

    def test_every_documented_operation_has_a_success_response(self, openapi):
        missing = []
        for path, operations in openapi["paths"].items():
            for method, operation in operations.items():
                codes = set(operation.get("responses", {}))
                if not codes & {"200", "201", "202", "204", "302", "307"}:
                    missing.append(f"{method.upper()} {path}")
        assert missing == []

    def test_error_shape_is_declared_for_validated_routes(self, openapi):
        """Routes with parameters must document their 422."""
        missing = []
        for path, operations in openapi["paths"].items():
            for method, operation in operations.items():
                has_input = bool(operation.get("parameters")) or bool(
                    operation.get("requestBody")
                )
                if has_input and "422" not in operation.get("responses", {}):
                    missing.append(f"{method.upper()} {path}")
        assert missing == []


class TestContractDrift:
    """The committed snapshot is the reviewed contract.

    Regenerate deliberately with::

        ICAP_UPDATE_API_SNAPSHOT=1 python -m pytest tests/test_api_contract.py
    """

    def test_snapshot_exists(self):
        if REGENERATE:
            SNAPSHOT_PATH.write_text(
                json.dumps(build_snapshot(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        assert SNAPSHOT_PATH.is_file(), (
            "No API contract snapshot. Create it with "
            "ICAP_UPDATE_API_SNAPSHOT=1 python -m pytest tests/test_api_contract.py"
        )

    def test_no_routes_were_added_or_removed(self):
        recorded = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["routes"]
        current = build_snapshot()["routes"]

        added = sorted(set(current) - set(recorded))
        removed = sorted(set(recorded) - set(current))
        assert added == [], f"New routes are not in the snapshot: {added}"
        assert removed == [], f"Routes disappeared from the API: {removed}"

    def test_no_route_changed_its_contract(self):
        recorded = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["routes"]
        current = build_snapshot()["routes"]

        changed = {
            key: {"was": recorded[key], "now": current[key]}
            for key in set(recorded) & set(current)
            if recorded[key] != current[key]
        }
        assert changed == {}, (
            "Response model, status code, tags or path parameters changed. "
            "If intended, regenerate the snapshot."
        )

    def test_the_snapshot_records_response_models(self):
        recorded = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["routes"]
        modelled = [r for r in recorded.values() if r["response_model"]]
        assert len(modelled) / len(recorded) >= 0.9


class TestCoverageGate:
    """Coverage is only a gate if it is configured and enforced."""

    @staticmethod
    def _config():
        import configparser

        parser = configparser.ConfigParser()
        parser.read(BACKEND_ROOT / ".coveragerc", encoding="utf-8")
        return parser

    def test_coverage_config_exists(self):
        assert (BACKEND_ROOT / ".coveragerc").is_file()

    def test_coverage_is_scoped_to_the_api_surface(self):
        source = self._config().get("run", "source")
        assert "app/api" in source
        assert "app/schemas" in source

    def test_branch_coverage_is_measured(self):
        """Line coverage alone hides untested error paths."""
        assert self._config().getboolean("run", "branch") is True

    def test_a_threshold_is_enforced(self):
        threshold = self._config().getfloat("report", "fail_under")
        assert threshold >= 80, "an API coverage gate below 80% is not a gate"

    def test_the_runner_is_declared_as_a_dependency(self):
        requirements = (BACKEND_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )
        assert "pytest-cov" in requirements
