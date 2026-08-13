"""
Prometheus text exposition for the runtime metrics.

The numbers here are exactly the ones ``GET /system/metrics`` returns as JSON —
this module only re-encodes them in the Prometheus text format so an existing
monitoring stack (Prometheus → Grafana → Alertmanager) can scrape them on a
schedule instead of a human opening a JSON endpoint. No metric is computed,
sampled or aggregated here.

Percentiles are exported as ``quantile``-labelled gauges rather than a native
summary: the reservoir is a bounded window, so the values are a rolling read of
recent traffic, and labelling them honestly avoids implying a lifetime summary.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_QUANTILES: Sequence[Tuple[str, str]] = (
    ("0.5", "p50_ms"),
    ("0.95", "p95_ms"),
    ("0.99", "p99_ms"),
)


def escape_label_value(value: Any) -> str:
    """Escape a label value per the Prometheus text exposition format."""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(pairs: Mapping[str, Any]) -> str:
    if not pairs:
        return ""
    rendered = ",".join(
        f'{key}="{escape_label_value(value)}"' for key, value in pairs.items()
    )
    return "{" + rendered + "}"


def _metric(name: str, labels: Mapping[str, Any], value: Any) -> str:
    numeric = float(value or 0.0)
    return f"{name}{_labels(labels)} {numeric:g}"


def _split_route(key: str) -> Tuple[str, str]:
    """``"GET /alarms/{id}"`` → ``("GET", "/alarms/{id}")``."""
    method, _, route = str(key).partition(" ")
    return (method or "UNKNOWN", route or str(key))


def _section(name: str, help_text: str, metric_type: str, lines: Iterable[str]) -> List[str]:
    body = list(lines)
    if not body:
        return []
    return [f"# HELP {name} {help_text}", f"# TYPE {name} {metric_type}", *body]


def render_prometheus(
    *,
    requests: Mapping[str, Any],
    challenges: Mapping[str, Any],
    alerts: Optional[Mapping[str, Any]] = None,
    service: str = "icap-backend",
    environment: str = "unknown",
    version: str = "unknown",
) -> str:
    """Render one scrape response from already-collected metric snapshots."""
    out: List[str] = []

    out += _section(
        "icap_build_info",
        "Build and deployment identity of the reporting worker.",
        "gauge",
        [
            _metric(
                "icap_build_info",
                {"service": service, "environment": environment, "version": version},
                1,
            )
        ],
    )

    routes: List[Dict[str, Any]] = list(requests.get("routes", []) or [])

    out += _section(
        "icap_http_requests_total",
        "Requests observed per route since this worker started.",
        "counter",
        [
            _metric(
                "icap_http_requests_total",
                dict(zip(("method", "route"), _split_route(route.get("route", "")))),
                route.get("requests", 0),
            )
            for route in routes
        ],
    )

    out += _section(
        "icap_http_request_errors_total",
        "Responses with a 5xx status per route since this worker started.",
        "counter",
        [
            _metric(
                "icap_http_request_errors_total",
                dict(zip(("method", "route"), _split_route(route.get("route", "")))),
                route.get("errors", 0),
            )
            for route in routes
        ],
    )

    duration_lines: List[str] = []
    for route in routes:
        method, path = _split_route(route.get("route", ""))
        for quantile, field in _QUANTILES:
            duration_lines.append(
                _metric(
                    "icap_http_request_duration_ms",
                    {"method": method, "route": path, "quantile": quantile},
                    route.get(field, 0.0),
                )
            )
    out += _section(
        "icap_http_request_duration_ms",
        "Rolling request duration percentiles per route, in milliseconds.",
        "gauge",
        duration_lines,
    )

    out += _section(
        "icap_http_request_samples",
        "Durations currently held in the bounded reservoir per route.",
        "gauge",
        [
            _metric(
                "icap_http_request_samples",
                dict(zip(("method", "route"), _split_route(route.get("route", "")))),
                route.get("sampled", 0),
            )
            for route in routes
        ],
    )

    keys: List[Dict[str, Any]] = list(challenges.get("by_key", []) or [])
    generation_labels = ("challenge_type", "difficulty", "source")

    out += _section(
        "icap_challenge_generations_total",
        "Challenge generations performed per type/difficulty/source.",
        "counter",
        [
            _metric(
                "icap_challenge_generations_total",
                {label: entry.get(label, "unknown") for label in generation_labels},
                entry.get("calls", 0),
            )
            for entry in keys
        ],
    )

    out += _section(
        "icap_challenge_generation_failures_total",
        "Failed challenge generations per type/difficulty/source.",
        "counter",
        [
            _metric(
                "icap_challenge_generation_failures_total",
                {label: entry.get(label, "unknown") for label in generation_labels},
                entry.get("failures", 0),
            )
            for entry in keys
        ],
    )

    generation_lines: List[str] = []
    for entry in keys:
        labels = {label: entry.get(label, "unknown") for label in generation_labels}
        for quantile, field in _QUANTILES:
            generation_lines.append(
                _metric(
                    "icap_challenge_generation_duration_ms",
                    {**labels, "quantile": quantile},
                    entry.get(field, 0.0),
                )
            )
    out += _section(
        "icap_challenge_generation_duration_ms",
        "Rolling challenge generation duration percentiles, in milliseconds.",
        "gauge",
        generation_lines,
    )

    if alerts is not None:
        firing: List[Dict[str, Any]] = list(alerts.get("firing", []) or [])
        counts: Dict[Tuple[str, str], int] = {}
        for alert in firing:
            counts[(str(alert.get("rule", "unknown")), str(alert.get("severity", "warning")))] = (
                counts.get(
                    (str(alert.get("rule", "unknown")), str(alert.get("severity", "warning"))),
                    0,
                )
                + 1
            )
        out += _section(
            "icap_metrics_alerts_active",
            "Threshold alerts currently firing, by rule and severity.",
            "gauge",
            [
                _metric(
                    "icap_metrics_alerts_active",
                    {"rule": rule, "severity": severity},
                    count,
                )
                for (rule, severity), count in sorted(counts.items())
            ]
            or [_metric("icap_metrics_alerts_active", {"rule": "none", "severity": "none"}, 0)],
        )

    # Prometheus requires the body to end with a newline.
    return "\n".join(out) + "\n"
