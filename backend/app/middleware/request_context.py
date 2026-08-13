"""
Correlation id propagation and structured access logging.

Registered as the outermost middleware so the correlation id is bound before
anything else runs — including the timing middleware — and every log record
emitted anywhere below, in any service, carries it automatically via the
context variable.

An inbound ``X-Request-ID`` is honoured when it is safe (so a trace started at
nginx or in the browser continues through the backend) and is always echoed on
the response, giving support a single value that ties a user report, a browser
error report and a server log line together.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging_config import ACCESS_LOGGER_NAME
from app.core.request_context import bind_request_id, reset_request_id
from app.core.request_metrics import route_template

logger = logging.getLogger(__name__)
access_logger = logging.getLogger(ACCESS_LOGGER_NAME)

#: Container/orchestrator probes hit these constantly. A successful probe is
#: logged at DEBUG so it does not bury real traffic; a failing one is still
#: logged loudly, which is the only time a health check is interesting.
QUIET_PATHS = frozenset({"/health", "/nginx-health"})


def _client_address(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def _level_for(status_code: int, path: str) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.DEBUG if path in QUIET_PATHS else logging.INFO


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id per request and emit one structured access line."""

    def __init__(
        self,
        app,
        *,
        header_name: str = "X-Request-ID",
        access_log: bool = True,
        quiet_paths: Iterable[str] = QUIET_PATHS,
    ) -> None:
        super().__init__(app)
        self.header_name = header_name
        self.access_log = access_log
        self.quiet_paths = frozenset(quiet_paths)

    async def dispatch(self, request: Request, call_next):
        request_id, token = bind_request_id(request.headers.get(self.header_name))
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000.0
            # The exception is re-raised for the server's own handler; this
            # record exists so the failure is attributable to a request.
            logger.exception(
                "Unhandled exception during %s %s",
                request.method,
                request.url.path,
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_route": route_template(request),
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": _client_address(request),
                    "event": "request.failed",
                },
            )
            reset_request_id(token)
            raise

        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers[self.header_name] = request_id

        if self.access_log:
            path = request.url.path
            level = _level_for(response.status_code, path)
            if path in self.quiet_paths and response.status_code < 400:
                level = logging.DEBUG
            access_logger.log(
                level,
                "%s %s %s %.2fms",
                request.method,
                path,
                response.status_code,
                duration_ms,
                extra={
                    "http_method": request.method,
                    "http_path": path,
                    "http_route": route_template(request),
                    "http_status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": _client_address(request),
                    "user_agent": request.headers.get("user-agent", ""),
                    "event": "request.completed",
                },
            )

        reset_request_id(token)
        return response
