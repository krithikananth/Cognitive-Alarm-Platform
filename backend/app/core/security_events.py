"""
Security event logging (OWASP A09).

Authentication and authorization outcomes were previously invisible: a failed
login, a lockout, a rejected token and a denied admin request all produced no
record at all, so there was nothing to detect an attack with and nothing to
investigate one from afterwards.

Every event goes to the dedicated ``app.security`` logger with a stable
``security_event`` field, so the whole category can be routed, alerted on and
retained independently of application logs.

Two rules are enforced here rather than left to call sites:

* **Never log a credential.** Any field whose name looks like a secret is
  dropped, regardless of what the caller passed.
* **Never let a value forge a log line.** Values are stripped of control
  characters and truncated, so a newline in an attacker-supplied username
  cannot fabricate a second record (the JSON formatter escapes them too — this
  is the second layer, and the one that also protects the console format).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("app.security")

#: Name of the logger carrying every security event.
SECURITY_LOGGER_NAME = "app.security"

# ── Event names ───────────────────────────────────────────────────────
LOGIN_SUCCEEDED = "auth.login.succeeded"
LOGIN_FAILED = "auth.login.failed"
LOGIN_BLOCKED = "auth.login.blocked"
LOGIN_INACTIVE = "auth.login.inactive_account"
LOGOUT = "auth.logout"
LOGOUT_ALL = "auth.logout_all"
TOKEN_REJECTED = "auth.token.rejected"
PASSWORD_RESET_REQUESTED = "auth.password_reset.requested"
PASSWORD_RESET_COMPLETED = "auth.password_reset.completed"
PASSWORD_RESET_BLOCKED = "auth.password_reset.blocked"
OAUTH_STATE_REJECTED = "auth.oauth.state_rejected"
OAUTH_LOGIN_SUCCEEDED = "auth.oauth.succeeded"
ACCESS_DENIED = "authz.denied"
ACCOUNT_LOCKED = "abuse.account_locked"

OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_BLOCKED = "blocked"

#: Any field matching this is dropped before the record is built — a caller
#: cannot accidentally (or deliberately) put a credential into the audit log.
_FORBIDDEN_FIELD = re.compile(
    r"(password|secret|credential|authorization|cookie|api[_-]?key"
    r"|access_token|refresh_token|\btoken\b)",
    re.IGNORECASE,
)

#: Control characters, including CR/LF, that could forge a log line.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

MAX_VALUE_LENGTH = 256

_LEVEL_BY_OUTCOME = {
    OUTCOME_SUCCESS: logging.INFO,
    OUTCOME_FAILURE: logging.WARNING,
    OUTCOME_BLOCKED: logging.WARNING,
}


def scrub(value: Any) -> Any:
    """Make one field value safe to write into a log record."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _CONTROL_CHARS.sub("", str(value))
    return text[:MAX_VALUE_LENGTH]


def _safe_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: scrub(value)
        for key, value in fields.items()
        if value is not None and not _FORBIDDEN_FIELD.search(key)
    }


def client_address(request: Any) -> str:
    """Best-effort caller address, mirroring the rate limiter's view."""
    if request is None:
        return "unknown"
    try:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return scrub(forwarded.split(",")[0].strip()) or "unknown"
        client = getattr(request, "client", None)
        return scrub(getattr(client, "host", None)) or "unknown"
    except Exception:
        return "unknown"


def log_security_event(
    event: str,
    *,
    outcome: str = OUTCOME_FAILURE,
    request: Any = None,
    user_id: Any = None,
    identifier: Optional[str] = None,
    reason: Optional[str] = None,
    severity: Optional[int] = None,
    **fields: Any,
) -> None:
    """Record one security-relevant event.

    ``identifier`` is the account an action was attempted against (email or
    username). It is intentionally recorded — an audit trail that cannot name
    the targeted account is not usable for investigating credential stuffing —
    but it is scrubbed first, and no credential is ever accepted.
    """
    level = severity if severity is not None else _LEVEL_BY_OUTCOME.get(
        outcome, logging.WARNING
    )
    extra: Dict[str, Any] = {
        "event": event,
        "security_event": event,
        "outcome": scrub(outcome),
        "client_ip": client_address(request),
    }
    if request is not None:
        extra["http_method"] = scrub(getattr(request, "method", None))
        url = getattr(request, "url", None)
        extra["http_path"] = scrub(getattr(url, "path", None))
    if user_id is not None:
        extra["user_id"] = scrub(user_id)
    if identifier is not None:
        extra["identifier"] = scrub(identifier)
    if reason is not None:
        extra["reason"] = scrub(reason)
    extra.update(_safe_fields(fields))

    logger.log(level, "security.%s outcome=%s", event, extra["outcome"], extra=extra)
