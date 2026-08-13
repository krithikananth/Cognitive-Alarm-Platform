"""
Anti-CSRF ``state`` for the Google OAuth2 authorization-code flow.

Without ``state`` an attacker can hand a victim's browser their own Google
authorization code and silently sign the victim into the attacker's account
(login CSRF). The token below is cryptographically random, HMAC-signed with the
application secret, bound to the initiating browser through a short-lived
HttpOnly cookie, and accepted exactly once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from typing import Dict, Optional

from fastapi import Request, Response

from app.core.config import settings

_VERSION = "v1"
_NONCE_BYTES = 32
_MIN_TTL_SECONDS = 30


class StateError(Exception):
    """Raised when a callback ``state`` cannot be trusted.

    ``reason`` is a stable, non-sensitive slug safe to surface to the SPA.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _SingleUseNonces:
    """Registry of redeemed nonces so a captured state cannot be replayed."""

    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def redeem(self, nonce: str, expires_at: float) -> bool:
        """Claim ``nonce``; returns False when it was already claimed."""
        now = time.time()
        with self._lock:
            for seen, expiry in list(self._seen.items()):
                if expiry <= now:
                    del self._seen[seen]
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires_at
            return True

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()


_redeemed = _SingleUseNonces()


def reset_state_store() -> None:
    """Forget every redeemed nonce (tests and admin tooling)."""
    _redeemed.clear()


def _ttl_seconds() -> int:
    return max(_MIN_TTL_SECONDS, int(settings.OAUTH_STATE_TTL_SECONDS))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _signature(payload: str) -> str:
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    return _b64(hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest())


def generate_state() -> str:
    """Build a signed, expiring, single-use state token."""
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    expires_at = int(time.time()) + _ttl_seconds()
    payload = f"{_VERSION}.{nonce}.{expires_at}"
    return f"{payload}.{_signature(payload)}"


def verify_state(returned: Optional[str], expected: Optional[str]) -> None:
    """Validate the callback state against the cookie bound to the browser.

    Args:
        returned: ``state`` query parameter sent back by the provider.
        expected: Value read from the browser's state cookie.

    Raises:
        StateError: If the value is missing, mismatched, tampered with,
            expired, or has already been redeemed.
    """
    if not returned or not expected:
        raise StateError("oauth_state_missing")

    if not hmac.compare_digest(returned, expected):
        raise StateError("oauth_state_mismatch")

    parts = returned.split(".")
    if len(parts) != 4:
        raise StateError("oauth_state_invalid")

    version, nonce, expires_raw, signature = parts
    if version != _VERSION or not nonce:
        raise StateError("oauth_state_invalid")

    if not hmac.compare_digest(
        signature, _signature(f"{version}.{nonce}.{expires_raw}")
    ):
        raise StateError("oauth_state_invalid")

    try:
        expires_at = int(expires_raw)
    except ValueError:
        raise StateError("oauth_state_invalid") from None

    # Expiry is checked before redemption so a stale nonce is never stored.
    if expires_at <= time.time():
        raise StateError("oauth_state_expired")

    if not _redeemed.redeem(nonce, expires_at):
        raise StateError("oauth_state_replayed")


def set_state_cookie(response: Response, state: str) -> None:
    """Bind the state to the initiating browser via a short-lived cookie."""
    max_age = _ttl_seconds()
    response.set_cookie(
        settings.OAUTH_STATE_COOKIE_NAME,
        state,
        max_age=max_age,
        expires=max_age,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.cookies_secure,
        httponly=True,
        # Lax, never Strict: the cookie must survive the provider's top-level
        # redirect back to the callback.
        samesite="lax",
    )


def clear_state_cookie(response: Response) -> None:
    """Drop the state cookie once the flow terminates (success or failure)."""
    response.delete_cookie(
        settings.OAUTH_STATE_COOKIE_NAME,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
        secure=settings.cookies_secure,
        httponly=True,
        samesite="lax",
    )


def state_cookie(request: Optional[Request]) -> Optional[str]:
    """Read the pending state token from the request cookies."""
    if request is None:
        return None
    return request.cookies.get(settings.OAUTH_STATE_COOKIE_NAME)
