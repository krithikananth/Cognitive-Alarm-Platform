"""
Runtime API latency measurement.

Every metric in this project measured user behaviour; nothing measured the API
itself. ``perf/benchmark.py`` times endpoints offline against a synthetic
dataset, which cannot see what real traffic experiences.

``RequestTimingMiddleware`` times each request end to end (it is registered
last, so it wraps CORS and maintenance-mode handling too), stamps the duration
on the response as ``X-Process-Time`` in milliseconds, and files it into a
bounded in-process reservoir keyed by *route template* — ``/alarms/{alarm_id}``
rather than ``/alarms/17`` — so cardinality stays fixed no matter how many ids
are hit.

The reservoir is per-process and deliberately not persisted: it answers "how is
this worker behaving right now", which is what a latency read-out is for. A
multi-worker deployment reads each worker separately.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Sequence

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

#: Response header carrying the measured server-side duration, in milliseconds.
PROCESS_TIME_HEADER = "X-Process-Time"


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile.

    Matches ``perf/benchmark.py`` so runtime numbers and benchmark numbers are
    computed identically and can be compared directly.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered)))))
    return ordered[rank - 1]


class _RouteSamples:
    """Recent durations for one route, plus counters that never roll off."""

    __slots__ = ("durations", "requests", "errors", "last_status")

    def __init__(self, sample_size: int) -> None:
        self.durations: Deque[float] = deque(maxlen=sample_size)
        self.requests = 0
        self.errors = 0
        self.last_status: Optional[int] = None


class RequestLatencyRegistry:
    """Bounded, thread-safe reservoir of request durations per route."""

    def __init__(self, sample_size: int = 500) -> None:
        self._sample_size = max(1, int(sample_size))
        self._lock = Lock()
        self._routes: Dict[str, _RouteSamples] = {}

    def record(
        self, *, method: str, route: str, status_code: int, duration_ms: float
    ) -> None:
        key = f"{method} {route}"
        with self._lock:
            entry = self._routes.get(key)
            if entry is None:
                entry = _RouteSamples(self._sample_size)
                self._routes[key] = entry
            entry.durations.append(float(duration_ms))
            entry.requests += 1
            entry.last_status = status_code
            if status_code >= 500:
                entry.errors += 1

    def reset(self) -> None:
        with self._lock:
            self._routes.clear()

    def configure(self, sample_size: int) -> None:
        """Resize in place — rebinding would strand modules that imported it."""
        with self._lock:
            self._sample_size = max(1, int(sample_size))
            self._routes.clear()

    def durations_for(self, method: str, route: str) -> List[float]:
        with self._lock:
            entry = self._routes.get(f"{method} {route}")
            return list(entry.durations) if entry else []

    def snapshot(self, *, top: Optional[int] = None) -> Dict[str, Any]:
        """Per-route latency distribution plus a whole-process rollup."""
        with self._lock:
            items = [(key, list(e.durations), e.requests, e.errors) for key, e in self._routes.items()]

        routes = [
            {
                "route": key,
                "requests": requests,
                "errors": errors,
                "sampled": len(durations),
                **distribution(durations),
            }
            for key, durations, requests, errors in items
            if durations
        ]
        routes.sort(key=lambda r: r["p95_ms"], reverse=True)

        every_duration: List[float] = [d for _, durations, _, _ in items for d in durations]
        return {
            "sample_size": self._sample_size,
            "routes_tracked": len(routes),
            "total_requests": sum(r["requests"] for r in routes),
            "total_errors": sum(r["errors"] for r in routes),
            "overall": distribution(every_duration),
            "routes": routes[:top] if top else routes,
        }


def distribution(durations: Sequence[float]) -> Dict[str, Any]:
    """Percentile summary shared by every latency reservoir in the app."""
    if not durations:
        return {
            "sampled": 0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
        }
    return {
        "sampled": len(durations),
        "p50_ms": round(percentile(durations, 50), 2),
        "p95_ms": round(percentile(durations, 95), 2),
        "p99_ms": round(percentile(durations, 99), 2),
        "min_ms": round(min(durations), 2),
        "max_ms": round(max(durations), 2),
        "mean_ms": round(sum(durations) / len(durations), 2),
    }


#: Process-wide registry the middleware writes to and the metrics endpoint reads.
request_latency = RequestLatencyRegistry()


def configure_registry(sample_size: int) -> None:
    """Resize the reservoir at startup, dropping anything already collected."""
    request_latency.configure(sample_size)


def route_template(request: Request) -> str:
    """Matched route pattern, so ``/alarms/{alarm_id}`` never becomes 10k keys."""
    route = request.scope.get("route")
    for attr in ("path_format", "path"):
        value = getattr(route, attr, None)
        if value:
            return str(value)
    return request.url.path


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Time every request, stamp the duration, and file it for reporting."""

    def __init__(self, app, *, enabled: bool = True) -> None:
        super().__init__(app)
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000.0

        response.headers[PROCESS_TIME_HEADER] = f"{duration_ms:.2f}"
        request_latency.record(
            method=request.method,
            route=route_template(request),
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
