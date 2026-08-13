"""
Threshold evaluation and alerting over the measured runtime metrics.

``/system/metrics`` already records real per-route latency and challenge
generation latency, but nothing ever *looked* at those numbers: a p95 could sit
five times over budget indefinitely and the only way to find out was for a human
to open the endpoint. This module closes that loop.

It measures nothing new. It reads the existing reservoirs
(:data:`~app.core.request_metrics.request_latency` and
:data:`~app.core.challenge_metrics.challenge_generation`), compares them against
configured thresholds, and turns a breach into:

* a structured ``app.alerts`` log record — so the alert lands in whatever
  aggregator the logs already go to;
* an optional outbound webhook (``METRICS_ALERT_WEBHOOK_URL``) for
  Alertmanager / Slack / PagerDuty style delivery.

Alerts are stateful. A breach fires once, re-notifies only after
``METRICS_ALERT_COOLDOWN_SECONDS`` while it persists, and emits an explicit
``resolved`` event when the reading recovers — so a permanently slow route does
not page every evaluation cycle.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.challenge_metrics import challenge_generation
from app.core.config import settings
from app.core.logging_config import ALERT_LOGGER_NAME
from app.core.request_metrics import request_latency

logger = logging.getLogger(ALERT_LOGGER_NAME)

SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

#: Ordering used to pick the single worst severity in a batch.
_SEVERITY_RANK = {SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}

RULE_API_LATENCY = "api_latency_p95"
RULE_API_ERROR_RATE = "api_error_rate"
RULE_CHALLENGE_LATENCY = "challenge_generation_p95"
RULE_CHALLENGE_FAILURES = "challenge_generation_failure_rate"

#: Alert delivery may only speak HTTP(S) — never file://, ftp:// or gopher://.
ALLOWED_WEBHOOK_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True)
class Alert:
    """One threshold breach detected in a single evaluation pass."""

    rule: str
    target: str
    severity: str
    metric: str
    value: float
    threshold: float
    unit: str
    observations: int
    message: str

    @property
    def key(self) -> str:
        return f"{self.rule}:{self.target}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "rule": self.rule,
            "target": self.target,
            "severity": self.severity,
            "metric": self.metric,
            "value": self.value,
            "threshold": self.threshold,
            "unit": self.unit,
            "observations": self.observations,
            "message": self.message,
        }


def _log_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt an alert dict for ``logging`` ``extra=``.

    ``message`` is a reserved LogRecord attribute — passing it raises
    ``KeyError: Attempt to overwrite 'message'`` — so it is carried as
    ``alert_message`` instead.
    """
    fields = dict(payload)
    if "message" in fields:
        fields["alert_message"] = fields.pop("message")
    return fields


@dataclass
class _ActiveAlert:
    """Bookkeeping for an alert that is currently firing."""

    alert: Alert
    first_seen: float
    last_notified: float
    notifications: int = 1
    evaluations: int = 1
    peak_value: float = field(default=0.0)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _severity_for(value: float, threshold: float, multiplier: float) -> str:
    if threshold > 0 and value >= threshold * max(1.0, multiplier):
        return SEVERITY_CRITICAL
    return SEVERITY_WARNING


class MetricsAlertEvaluator:
    """Stateful threshold evaluator over the runtime metric reservoirs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: Dict[str, _ActiveAlert] = {}
        self._last_evaluated_at: Optional[str] = None

    # ── rule implementations ──────────────────────────────────────────

    def _api_alerts(self, snapshot: Dict[str, Any]) -> List[Alert]:
        alerts: List[Alert] = []
        min_samples = max(1, int(settings.METRICS_ALERT_MIN_SAMPLES))
        latency_budget = float(settings.METRICS_ALERT_P95_MS)
        error_budget = float(settings.METRICS_ALERT_ERROR_RATE_PCT)
        multiplier = float(settings.METRICS_ALERT_CRITICAL_MULTIPLIER)

        for route in snapshot.get("routes", []) or []:
            target = str(route.get("route", "unknown"))

            sampled = int(route.get("sampled", 0) or 0)
            p95 = float(route.get("p95_ms", 0.0) or 0.0)
            if sampled >= min_samples and latency_budget > 0 and p95 > latency_budget:
                alerts.append(
                    Alert(
                        rule=RULE_API_LATENCY,
                        target=target,
                        severity=_severity_for(p95, latency_budget, multiplier),
                        metric="p95_ms",
                        value=round(p95, 2),
                        threshold=latency_budget,
                        unit="ms",
                        observations=sampled,
                        message=(
                            f"{target} p95 is {p95:.2f}ms over "
                            f"{sampled} samples (budget {latency_budget:.0f}ms)"
                        ),
                    )
                )

            requests = int(route.get("requests", 0) or 0)
            errors = int(route.get("errors", 0) or 0)
            if requests >= min_samples and error_budget > 0:
                rate = errors / requests * 100.0
                if rate > error_budget:
                    alerts.append(
                        Alert(
                            rule=RULE_API_ERROR_RATE,
                            target=target,
                            severity=_severity_for(rate, error_budget, multiplier),
                            metric="error_rate_pct",
                            value=round(rate, 2),
                            threshold=error_budget,
                            unit="%",
                            observations=requests,
                            message=(
                                f"{target} returned {errors} server errors in "
                                f"{requests} requests ({rate:.2f}%)"
                            ),
                        )
                    )
        return alerts

    def _challenge_alerts(self, snapshot: Dict[str, Any]) -> List[Alert]:
        alerts: List[Alert] = []
        min_samples = max(1, int(settings.METRICS_ALERT_MIN_SAMPLES))
        # Challenge generation runs on the critical path of a ringing alarm, so
        # its own published budget is the threshold rather than the API one.
        budget = float(settings.CHALLENGE_GENERATION_BUDGET_MS)
        failure_budget = float(settings.METRICS_ALERT_ERROR_RATE_PCT)
        multiplier = float(settings.METRICS_ALERT_CRITICAL_MULTIPLIER)

        for entry in snapshot.get("by_key", []) or []:
            target = str(entry.get("key", "unknown"))

            sampled = int(entry.get("sampled", 0) or 0)
            p95 = float(entry.get("p95_ms", 0.0) or 0.0)
            if sampled >= min_samples and budget > 0 and p95 > budget:
                alerts.append(
                    Alert(
                        rule=RULE_CHALLENGE_LATENCY,
                        target=target,
                        severity=_severity_for(p95, budget, multiplier),
                        metric="p95_ms",
                        value=round(p95, 2),
                        threshold=budget,
                        unit="ms",
                        observations=sampled,
                        message=(
                            f"challenge generation {target} p95 is {p95:.2f}ms "
                            f"(budget {budget:.0f}ms)"
                        ),
                    )
                )

            calls = int(entry.get("calls", 0) or 0)
            failures = int(entry.get("failures", 0) or 0)
            if calls >= min_samples and failure_budget > 0:
                rate = failures / calls * 100.0
                if rate > failure_budget:
                    alerts.append(
                        Alert(
                            rule=RULE_CHALLENGE_FAILURES,
                            target=target,
                            severity=_severity_for(rate, failure_budget, multiplier),
                            metric="failure_rate_pct",
                            value=round(rate, 2),
                            threshold=failure_budget,
                            unit="%",
                            observations=calls,
                            message=(
                                f"challenge generation {target} failed {failures} "
                                f"of {calls} attempts ({rate:.2f}%)"
                            ),
                        )
                    )
        return alerts

    # ── evaluation ────────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        requests: Optional[Dict[str, Any]] = None,
        challenges: Optional[Dict[str, Any]] = None,
        notify: bool = True,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compare current readings against thresholds and update alert state.

        ``notify=False`` gives a read-only view (used by the admin endpoint) so
        that refreshing a dashboard cannot generate alert traffic.
        """
        if not settings.METRICS_ALERTS_ENABLED:
            return {
                "enabled": False,
                "evaluated_at": _now_iso(),
                "thresholds": self.thresholds(),
                "firing": [],
                "new": [],
                "resolved": [],
                "active_count": 0,
                "worst_severity": None,
            }

        moment = time.monotonic() if now is None else now
        api_snapshot = request_latency.snapshot() if requests is None else requests
        gen_snapshot = (
            challenge_generation.snapshot() if challenges is None else challenges
        )

        firing = self._api_alerts(api_snapshot) + self._challenge_alerts(gen_snapshot)
        by_key = {alert.key: alert for alert in firing}
        cooldown = max(1, int(settings.METRICS_ALERT_COOLDOWN_SECONDS))

        new_alerts: List[Alert] = []
        repeated: List[Alert] = []
        resolved: List[Dict[str, Any]] = []

        with self._lock:
            for key, alert in by_key.items():
                existing = self._active.get(key)
                if existing is None:
                    self._active[key] = _ActiveAlert(
                        alert=alert,
                        first_seen=moment,
                        last_notified=moment,
                        peak_value=alert.value,
                    )
                    new_alerts.append(alert)
                    continue

                existing.alert = alert
                existing.evaluations += 1
                existing.peak_value = max(existing.peak_value, alert.value)
                if moment - existing.last_notified >= cooldown:
                    existing.last_notified = moment
                    existing.notifications += 1
                    repeated.append(alert)

            for key in [k for k in self._active if k not in by_key]:
                cleared = self._active.pop(key)
                resolved.append(
                    {
                        **cleared.alert.to_dict(),
                        "duration_seconds": round(moment - cleared.first_seen, 2),
                        "peak_value": cleared.peak_value,
                    }
                )

            active_snapshot = [
                {
                    **entry.alert.to_dict(),
                    "duration_seconds": round(moment - entry.first_seen, 2),
                    "evaluations": entry.evaluations,
                    "notifications": entry.notifications,
                    "peak_value": entry.peak_value,
                }
                for entry in self._active.values()
            ]
            self._last_evaluated_at = _now_iso()
            evaluated_at = self._last_evaluated_at

        if notify:
            for alert in new_alerts:
                self._notify(alert, "firing")
            for alert in repeated:
                self._notify(alert, "still_firing")
            for payload in resolved:
                self._notify_resolved(payload)
            if new_alerts or repeated:
                self._post_webhook(new_alerts + repeated)

        worst = max(
            (a["severity"] for a in active_snapshot),
            key=lambda s: _SEVERITY_RANK.get(s, 0),
            default=None,
        )
        return {
            "enabled": True,
            "evaluated_at": evaluated_at,
            "thresholds": self.thresholds(),
            "firing": active_snapshot,
            "new": [a.to_dict() for a in new_alerts],
            "resolved": resolved,
            "active_count": len(active_snapshot),
            "worst_severity": worst,
        }

    # ── delivery ──────────────────────────────────────────────────────

    def _notify(self, alert: Alert, event: str) -> None:
        level = (
            logging.ERROR if alert.severity == SEVERITY_CRITICAL else logging.WARNING
        )
        logger.log(
            level,
            "Metrics alert %s: %s",
            event,
            alert.message,
            extra={"event": f"alert.{event}", **_log_fields(alert.to_dict())},
        )

    def _notify_resolved(self, payload: Dict[str, Any]) -> None:
        logger.info(
            "Metrics alert resolved: %s",
            payload.get("message", payload.get("key", "")),
            extra={"event": "alert.resolved", **_log_fields(payload)},
        )

    def _post_webhook(self, alerts: List[Alert]) -> None:
        """Best-effort outbound delivery; a broken webhook must never raise."""
        url = settings.METRICS_ALERT_WEBHOOK_URL
        if not url or not alerts:
            return
        # urlopen honours file://, ftp:// and other handlers. The URL is
        # operator-supplied rather than user-supplied, but restricting the
        # scheme means a typo or a compromised config value cannot turn the
        # alerting path into a local-file read or an SSRF primitive.
        scheme = urllib.parse.urlsplit(url).scheme.lower()
        if scheme not in ALLOWED_WEBHOOK_SCHEMES:
            logger.warning(
                "Metrics alert webhook rejected: unsupported scheme",
                extra={"event": "alert.webhook_rejected", "scheme": scheme},
            )
            return
        body = json.dumps(
            {
                "source": settings.LOG_SERVICE_NAME,
                "environment": settings.ENVIRONMENT,
                "version": settings.VERSION,
                "generated_at": _now_iso(),
                "alerts": [alert.to_dict() for alert in alerts],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            timeout = float(settings.METRICS_ALERT_WEBHOOK_TIMEOUT_SECONDS)
            # Scheme is restricted to http/https above — precisely the check
            # B310 asks for — so the rule is answered rather than ignored.
            with urllib.request.urlopen(request, timeout=timeout):  # nosec B310
                pass
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning(
                "Metrics alert webhook delivery failed",
                extra={"event": "alert.webhook_failed", "error": str(exc)},
            )

    # ── introspection ─────────────────────────────────────────────────

    def thresholds(self) -> Dict[str, Any]:
        return {
            "api_p95_ms": float(settings.METRICS_ALERT_P95_MS),
            "api_error_rate_pct": float(settings.METRICS_ALERT_ERROR_RATE_PCT),
            "challenge_generation_p95_ms": float(
                settings.CHALLENGE_GENERATION_BUDGET_MS
            ),
            "min_observations": int(settings.METRICS_ALERT_MIN_SAMPLES),
            "critical_multiplier": float(settings.METRICS_ALERT_CRITICAL_MULTIPLIER),
            "cooldown_seconds": int(settings.METRICS_ALERT_COOLDOWN_SECONDS),
        }

    def active(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [entry.alert.to_dict() for entry in self._active.values()]

    def reset(self) -> None:
        with self._lock:
            self._active.clear()
            self._last_evaluated_at = None


#: Process-wide evaluator shared by the scheduler job and the admin endpoint.
metrics_alerts = MetricsAlertEvaluator()


def evaluate_metrics_alerts(*, notify: bool = True) -> Dict[str, Any]:
    """Run one evaluation pass against the live reservoirs."""
    return metrics_alerts.evaluate(notify=notify)
