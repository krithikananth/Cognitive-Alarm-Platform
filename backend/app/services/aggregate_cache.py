"""
Short-TTL cache for expensive aggregate reads.

Two kinds of endpoint dominate the measured latency in ``docs/PERFORMANCE.md``:
the platform-wide admin aggregates, which are identical for every admin, and
the pandas-backed behavioural analytics, whose cost is DataFrame construction
rather than SQL. Both recompute the same answer for every caller within a few
seconds of each other.

The TTL is deliberately small. These payloads are dashboards, not ledgers, so
a few seconds of staleness is invisible, while anything longer would make an
admin's own mutation appear not to have landed.

Every Redis error is swallowed: a cache miss and a Redis outage must be
indistinguishable to callers, which always recompute.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Optional

from app.core.config import settings
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "icap:v1:agg"

# Shared by every admin aggregate: the population is the same for all admins,
# so the key carries no identity.
PLATFORM_SCOPE = "platform"


def _fingerprint(params: dict[str, Any]) -> str:
    """Stable short digest of the query parameters that shape a payload."""
    canonical = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def cache_key(namespace: str, scope: str | int, params: dict[str, Any]) -> str:
    return f"{_KEY_PREFIX}:{namespace}:{scope}:{_fingerprint(params)}"


def _ttl() -> int:
    return int(settings.AGGREGATE_CACHE_TTL_SECONDS)


def enabled() -> bool:
    return bool(settings.AGGREGATE_CACHE_ENABLED) and _ttl() > 0


def read(namespace: str, scope: str | int, params: dict[str, Any]) -> Optional[Any]:
    """Return a cached payload, or ``None`` on miss, outage or when disabled."""
    if not enabled():
        return None

    client = get_redis()
    if client is None:
        return None

    key = cache_key(namespace, scope, params)
    try:
        raw = client.get(key)
    except Exception as exc:  # noqa: BLE001 — soft-fail cache
        logger.warning("Aggregate cache read failed for %s: %s", key, exc)
        return None

    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        # Corrupt or foreign value: treat exactly like a miss.
        return None


def write(namespace: str, scope: str | int, params: dict[str, Any], payload: Any) -> None:
    """Store a payload. Never raises — a failed write is just a future miss.

    Serialization is strict on purpose. A ``default=`` coercion would let a
    numpy scalar or a datetime be cached as a string and come back a different
    type than the uncached path returns, so anything not natively JSON is
    served and simply not stored.
    """
    if not enabled():
        return

    client = get_redis()
    if client is None:
        return

    try:
        body = json.dumps(payload)
    except (TypeError, ValueError):
        logger.debug("Aggregate payload for %s:%s is not cacheable", namespace, scope)
        return

    key = cache_key(namespace, scope, params)
    try:
        client.set(key, body, ex=_ttl())
    except Exception as exc:  # noqa: BLE001 — soft-fail cache
        logger.warning("Aggregate cache write failed for %s: %s", key, exc)


def get_or_compute(
    namespace: str,
    scope: str | int,
    params: dict[str, Any],
    compute: Callable[[], Any],
) -> Any:
    """Return a cached payload for ``(namespace, scope, params)`` or compute it.

    ``compute`` must return something ``json.dumps`` can serialize; anything
    else is returned uncached rather than raising, so adding a cache can never
    turn a working endpoint into a 500.
    """
    cached = read(namespace, scope, params)
    if cached is not None:
        return cached

    payload = compute()
    write(namespace, scope, params, payload)
    return payload


def invalidate(namespace: str, scope: Optional[str | int] = None) -> None:
    """Drop cached payloads for a namespace, optionally narrowed to one scope.

    Used after a mutation whose effect an operator expects to see immediately;
    a no-op when Redis is unavailable.
    """
    client = get_redis()
    if client is None:
        return

    pattern = f"{_KEY_PREFIX}:{namespace}:{'*' if scope is None else scope}:*"
    try:
        # SCAN rather than KEYS: this runs inside a request, and KEYS blocks
        # the whole server on a large keyspace.
        for key in client.scan_iter(match=pattern, count=200):
            client.delete(key)
    except Exception as exc:  # noqa: BLE001 — soft-fail cache
        logger.warning("Aggregate cache invalidation failed for %s: %s", pattern, exc)
