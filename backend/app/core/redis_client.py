"""
Redis client with graceful degradation.

If Redis is disabled, unreachable, or errors at runtime, callers receive
``None`` and must fall through to their non-cached path. Connection attempts
are brief and retried periodically so a temporary outage does not permanently
disable caching for the process lifetime.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Any = None
_last_failure_at: float = 0.0
_RETRY_AFTER_SECONDS = 30.0


def get_redis() -> Optional[Any]:
    """Return a live Redis client, or ``None`` when unavailable."""
    global _client, _last_failure_at

    if not settings.REDIS_ENABLED:
        return None

    if _client is not None:
        try:
            _client.ping()
            return _client
        except Exception as exc:  # noqa: BLE001 — soft-fail cache
            logger.warning("Redis ping failed; disabling cache temporarily: %s", exc)
            _close_client()
            _last_failure_at = time.monotonic()
            return None

    now = time.monotonic()
    if _last_failure_at and (now - _last_failure_at) < _RETRY_AFTER_SECONDS:
        return None

    try:
        import redis  # lazy import so missing package does not break startup
    except ImportError:
        logger.warning("redis package not installed; recommendation cache disabled")
        _last_failure_at = now
        return None

    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT_SECONDS,
            health_check_interval=30,
        )
        client.ping()
        _client = client
        _last_failure_at = 0.0
        logger.info("Redis connected for recommendation caching (%s)", settings.REDIS_URL)
        return _client
    except Exception as exc:  # noqa: BLE001 — soft-fail cache
        logger.warning("Redis unavailable; recommendation cache disabled: %s", exc)
        _close_client()
        _last_failure_at = now
        return None


def reset_redis_client() -> None:
    """Drop the cached client (used by tests)."""
    global _last_failure_at
    _close_client()
    _last_failure_at = 0.0


def _close_client() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
    _client = None
