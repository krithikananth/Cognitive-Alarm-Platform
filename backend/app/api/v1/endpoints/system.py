"""Public system status, runtime metrics, alerting and client error intake."""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin, get_current_user
from app.core.challenge_metrics import challenge_generation
from app.core.config import settings
from app.core.logging_config import CLIENT_LOGGER_NAME, logging_status
from app.core.metrics_exposition import CONTENT_TYPE, render_prometheus
from app.core.rate_limit import RateLimiter, client_ip
from app.core.request_context import get_request_id
from app.core.request_metrics import request_latency
from app.core.security import oauth2_scheme_optional
from app.db.session import get_db
from app.models.user import User
from app.schemas.observability import (
    ApiMetricsResponse,
    ClientErrorAck,
    ClientErrorReport,
    LoggingStatusResponse,
    MetricsAlertsResponse,
)
from app.schemas.system_settings import SystemStatusResponse
from app.services.metrics_alert_service import evaluate_metrics_alerts
from app.services.system_settings_service import SystemSettingsService

router = APIRouter(prefix="/system", tags=["System"])

client_logger = logging.getLogger(CLIENT_LOGGER_NAME)

#: Dedicated limiter so a browser error storm cannot flood the log pipeline —
#: and, being separate from the auth limiters, cannot lock anyone out either.
client_error_limiter = RateLimiter()


def require_metrics_reader(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> str:
    """Allow an admin session or a configured Prometheus scrape token.

    A scraper has no user account, so gating the exposition endpoint on an
    admin login alone would make it unscrapeable. The role check itself is not
    reimplemented — it defers to the same dependency every other admin route
    uses.
    """
    configured = settings.METRICS_SCRAPE_TOKEN
    if configured and token and secrets.compare_digest(token, configured):
        return "scrape-token"
    admin = get_current_admin(get_current_user(request=request, token=token, db=db))
    return f"admin:{admin.id}"


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="Public platform status",
)
def get_system_status(db: Session = Depends(get_db)):
    """Return maintenance mode flag for client banners (unauthenticated)."""
    row = SystemSettingsService.get_or_create(db)
    return SystemStatusResponse(
        maintenance_mode=bool(row.maintenance_mode),
        maintenance_message=(
            row.maintenance_message if row.maintenance_mode else None
        ),
    )


@router.get(
    "/metrics",
    response_model=ApiMetricsResponse,
    summary="Measured API response times and challenge generation latency",
)
def get_api_latency_metrics(
    top: Optional[int] = Query(
        None, ge=1, le=200, description="Return only the N slowest routes"
    ),
    _admin: User = Depends(get_current_admin),
):
    """Server-side durations recorded by the runtime instrumentation.

    ``requests`` percentiles come from live traffic this worker actually
    served, keyed by route template. ``challenge_generation`` times
    ``ChallengeService.generate_challenge`` on its own, keyed by resolved
    type / difficulty / source, so a slow AI provider is not averaged into the
    procedural path. Both are per-process and reset when the worker restarts.
    """
    return {
        "requests": request_latency.snapshot(top=top),
        "challenge_generation": {
            **challenge_generation.snapshot(top=top),
            "budget_ms": settings.CHALLENGE_GENERATION_BUDGET_MS,
        },
    }


@router.get(
    "/metrics/prometheus",
    response_class=PlainTextResponse,
    summary="Prometheus exposition of the measured runtime metrics",
)
def get_prometheus_metrics(_reader: str = Depends(require_metrics_reader)):
    """The same readings as ``/system/metrics``, in scrape format.

    Nothing extra is measured; this exists so Prometheus/Grafana/Alertmanager
    can consume the metrics on a schedule instead of a human reading JSON.
    """
    body = render_prometheus(
        requests=request_latency.snapshot(),
        challenges=challenge_generation.snapshot(),
        # Read-only: a scrape must never generate alert notifications.
        alerts=evaluate_metrics_alerts(notify=False),
        service=settings.LOG_SERVICE_NAME,
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
    )
    return PlainTextResponse(content=body, media_type=CONTENT_TYPE)


@router.get(
    "/alerts",
    response_model=MetricsAlertsResponse,
    summary="Threshold alerts currently firing on the measured metrics",
)
def get_metrics_alerts(_admin: User = Depends(get_current_admin)):
    """Evaluate the configured thresholds and report what is breaching.

    Read-only: refreshing this view never emits alert notifications. The
    scheduled evaluation job owns delivery.
    """
    return evaluate_metrics_alerts(notify=False)


@router.get(
    "/logging",
    response_model=LoggingStatusResponse,
    summary="Active logging configuration",
)
def get_logging_status(_admin: User = Depends(get_current_admin)):
    """Report the level, format, handlers and rotation actually installed.

    File logging is best-effort (the container runs with a read-only root
    filesystem), so this is the only way to confirm whether it took effect.
    """
    return {
        **logging_status(),
        "request_id_header": settings.REQUEST_ID_HEADER,
    }


@router.post(
    "/client-errors",
    response_model=ClientErrorAck,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Record a browser-side error",
)
def record_client_error(payload: ClientErrorReport, request: Request):
    """Ingest an error caught by the SPA and write it to the server log.

    Unauthenticated on purpose: the errors most worth seeing happen on the
    login and OAuth-callback screens, before a session exists. Volume is capped
    per address so a crash loop cannot be used to flood the log pipeline.
    """
    request_id = payload.request_id or get_request_id()

    if not settings.CLIENT_ERROR_LOGGING_ENABLED:
        return ClientErrorAck(recorded=False, request_id=request_id)

    blocked = client_error_limiter.hit(
        f"client-error:{client_ip(request)}",
        limit=max(1, int(settings.CLIENT_ERROR_MAX_PER_WINDOW)),
        window_seconds=max(1, int(settings.CLIENT_ERROR_WINDOW_SECONDS)),
        block_seconds=max(1, int(settings.CLIENT_ERROR_WINDOW_SECONDS)),
    )
    if blocked:
        return ClientErrorAck(recorded=False, request_id=request_id)

    level = logging.WARNING if payload.severity == "warning" else logging.ERROR
    client_logger.log(
        level,
        "Client error (%s): %s",
        payload.source,
        payload.message,
        extra={
            "event": "client.error",
            "request_id": request_id,
            "client_source": payload.source,
            "client_severity": payload.severity,
            "error_name": payload.name,
            "error_message": payload.message,
            "error_stack": payload.stack,
            "component_stack": payload.component_stack,
            "boundary": payload.boundary,
            "page_url": payload.url,
            "user_agent": payload.user_agent or request.headers.get("user-agent", ""),
            "app_version": payload.app_version,
            "occurred_at": payload.occurred_at,
            "client_ip": client_ip(request),
            "context": payload.context,
        },
    )
    return ClientErrorAck(recorded=True, request_id=request_id)
