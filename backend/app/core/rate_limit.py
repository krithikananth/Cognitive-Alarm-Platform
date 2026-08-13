"""
In-process rate limiting and brute-force lockout.

Used by the authentication endpoints to cap credential-stuffing and
password-reset abuse. State is held per process (no external dependency), so a
multi-worker deployment enforces the limit per worker — the counters below are
still a hard runtime block, not an advisory one.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request, status

from app.core import security_events
from app.core.config import settings
from app.core.security_events import log_security_event


@dataclass
class _Bucket:
    """Sliding window of attempt timestamps plus an optional lockout."""

    hits: Deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class RateLimiter:
    """Thread-safe sliding-window limiter with lockout support."""

    def __init__(self) -> None:
        self._buckets: Dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def reset(self, key: Optional[str] = None) -> None:
        """Clear one key (or everything, for tests and admin tooling)."""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def retry_after(self, key: str) -> int:
        """Seconds remaining on an active lockout (0 when not locked)."""
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return 0
            remaining = bucket.blocked_until - time.monotonic()
            return max(0, int(remaining + 0.999)) if remaining > 0 else 0

    def check(self, key: str) -> int:
        """Return remaining lockout seconds without recording an attempt."""
        return self.retry_after(key)

    def hit(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
        block_seconds: int,
    ) -> int:
        """Record an attempt.

        Returns the lockout seconds if this attempt exhausted the allowance (or
        the key was already locked), otherwise 0.
        """
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())

            if bucket.blocked_until > now:
                return max(1, int(bucket.blocked_until - now + 0.999))

            cutoff = now - max(1, window_seconds)
            while bucket.hits and bucket.hits[0] < cutoff:
                bucket.hits.popleft()

            bucket.hits.append(now)
            if len(bucket.hits) >= max(1, limit):
                bucket.blocked_until = now + max(1, block_seconds)
                bucket.hits.clear()
                return max(1, block_seconds)
            return 0


# Separate limiters so a password-reset flood cannot lock out logins.
login_limiter = RateLimiter()
password_reset_limiter = RateLimiter()


def reset_all_limiters() -> None:
    """Clear every limiter (used by tests and after configuration changes)."""
    login_limiter.reset()
    password_reset_limiter.reset()


def client_ip(request: Optional[Request]) -> str:
    """Best-effort client address for keying limits."""
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "unknown") if client else "unknown"


def _too_many_requests(retry_after: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(1, retry_after))},
    )


def _login_targets(
    request: Optional[Request], identifier: str
) -> list[tuple[str, int]]:
    """Keys to enforce, each with its own cap.

    The account is capped tightly; the caller address is capped loosely so a
    shared NAT/proxy address cannot lock out unrelated users.
    """
    targets = [(f"ip:{client_ip(request)}", settings.LOGIN_IP_MAX_ATTEMPTS)]
    account = (identifier or "").strip().lower()
    if account:
        targets.append((f"account:{account}", settings.LOGIN_MAX_ATTEMPTS))
    return targets


def enforce_login_rate_limit(request: Optional[Request], identifier: str) -> None:
    """Reject the request while a login lockout is active."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    for key, _limit in _login_targets(request, identifier):
        retry_after = login_limiter.check(key)
        if retry_after:
            log_security_event(
                security_events.LOGIN_BLOCKED,
                outcome=security_events.OUTCOME_BLOCKED,
                request=request,
                identifier=identifier,
                reason="lockout_active",
                scope=key.split(":", 1)[0],
                retry_after_seconds=retry_after,
            )
            raise _too_many_requests(
                retry_after,
                "Too many failed login attempts. Try again in "
                f"{retry_after} seconds.",
            )


def register_failed_login(request: Optional[Request], identifier: str) -> None:
    """Count a failed login; the lockout applies to the *next* request."""
    if not settings.RATE_LIMIT_ENABLED:
        return
    for key, limit in _login_targets(request, identifier):
        locked_for = login_limiter.hit(
            key,
            limit=limit,
            window_seconds=settings.LOGIN_ATTEMPT_WINDOW_SECONDS,
            block_seconds=settings.LOGIN_LOCKOUT_SECONDS,
        )
        if locked_for:
            # The transition into lockout is the detectable signal of a
            # credential-stuffing run; the individual failures are noise.
            log_security_event(
                security_events.ACCOUNT_LOCKED,
                outcome=security_events.OUTCOME_BLOCKED,
                request=request,
                identifier=identifier,
                reason="too_many_failed_logins",
                scope=key.split(":", 1)[0],
                lockout_seconds=locked_for,
                severity=logging.ERROR,
            )


def clear_login_attempts(request: Optional[Request], identifier: str) -> None:
    """Forget failed attempts after a successful login."""
    for key, _limit in _login_targets(request, identifier):
        login_limiter.reset(key)


def enforce_password_reset_rate_limit(
    request: Optional[Request], identifier: str
) -> None:
    """Cap password-reset / verification email requests per account and IP."""
    if not settings.RATE_LIMIT_ENABLED:
        return

    account = (identifier or "").strip().lower()
    keys = [f"ip:{client_ip(request)}"]
    if account:
        keys.append(f"account:{account}")

    for key in keys:
        retry_after = password_reset_limiter.check(key)
        if retry_after:
            raise _too_many_requests(
                retry_after,
                "Too many password reset requests. Try again in "
                f"{retry_after} seconds.",
            )

    # Allowance is consumed only when the request is actually served.
    for key in keys:
        password_reset_limiter.hit(
            key,
            limit=settings.PASSWORD_RESET_MAX_REQUESTS,
            window_seconds=settings.PASSWORD_RESET_WINDOW_SECONDS,
            block_seconds=settings.PASSWORD_RESET_WINDOW_SECONDS,
        )
