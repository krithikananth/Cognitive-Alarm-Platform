"""
Per-request correlation identity.

Every log record needs to say *which request* produced it, otherwise a
production log is a flat stream of unrelated lines. The id is held in a
:class:`~contextvars.ContextVar` rather than passed as an argument so that any
module — services, repositories, schedulers — can stamp it without changing its
signature, and so concurrent requests never see each other's value.

Outside a request (startup, APScheduler jobs, CLI scripts) the value is
:data:`NO_REQUEST_ID`, which keeps the log schema stable instead of emitting a
missing key.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar, Token
from typing import Optional, Tuple

#: Placeholder used when no request is in flight.
NO_REQUEST_ID = "-"

#: Upper bound on an accepted inbound id — long enough for a UUID or a trace id.
MAX_REQUEST_ID_LENGTH = 64

# Deliberately strict: the value is echoed back in a response header and written
# into logs, so anything that could forge a header or a log line is rejected
# outright rather than escaped.
_SAFE_REQUEST_ID = re.compile(r"\A[A-Za-z0-9._:-]+\Z")

_request_id: ContextVar[str] = ContextVar("icap_request_id", default=NO_REQUEST_ID)


def new_request_id() -> str:
    """Generate a fresh correlation id."""
    return uuid.uuid4().hex


def sanitize_request_id(value: Optional[str]) -> Optional[str]:
    """Return a caller-supplied id if it is safe to trust, else ``None``."""
    if not value or not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_REQUEST_ID_LENGTH:
        return None
    if not _SAFE_REQUEST_ID.match(candidate):
        return None
    return candidate


def get_request_id() -> str:
    """Correlation id for the current context, or ``"-"`` outside a request."""
    return _request_id.get()


def set_request_id(value: str) -> Token:
    """Bind ``value`` to the current context; keep the token to restore it."""
    return _request_id.set(value or NO_REQUEST_ID)


def reset_request_id(token: Token) -> None:
    """Restore whatever was bound before the matching :func:`set_request_id`."""
    try:
        _request_id.reset(token)
    except ValueError:
        # Token belongs to a different context (task boundary) — the context
        # copy is discarded anyway, so there is nothing left to restore.
        _request_id.set(NO_REQUEST_ID)


def bind_request_id(incoming: Optional[str] = None) -> Tuple[str, Token]:
    """Adopt a trusted inbound id, or mint one, and bind it to this context."""
    request_id = sanitize_request_id(incoming) or new_request_id()
    return request_id, set_request_id(request_id)
