"""Schemas for browser error reporting and monitoring read-outs."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.request_context import MAX_REQUEST_ID_LENGTH, sanitize_request_id

#: Where the browser says the error came from. Anything else is recorded as
#: "unknown" rather than rejected — losing a crash report to a typo would be
#: worse than storing a slightly vague source.
CLIENT_ERROR_SOURCES = {
    "error_boundary",
    "window_error",
    "unhandled_rejection",
    "manual",
}

CLIENT_ERROR_SEVERITIES = {"error", "warning"}

#: Contexts are free-form, so both the number of keys and the value length are
#: capped to keep an unbounded object out of the log pipeline.
MAX_CONTEXT_KEYS = 20
MAX_CONTEXT_VALUE_LENGTH = 300


class ClientErrorReport(BaseModel):
    """One JavaScript error captured in the browser."""

    message: str = Field(..., min_length=1, max_length=1000)
    name: Optional[str] = Field(None, max_length=120)
    stack: Optional[str] = Field(None, max_length=8000)
    component_stack: Optional[str] = Field(None, max_length=8000)
    source: str = Field("manual", max_length=40)
    severity: str = Field("error", max_length=20)
    url: Optional[str] = Field(None, max_length=500)
    user_agent: Optional[str] = Field(None, max_length=300)
    app_version: Optional[str] = Field(None, max_length=60)
    boundary: Optional[str] = Field(None, max_length=80)
    # Correlation id minted in the browser, so a crash report can be lined up
    # with the server log records of the requests that preceded it.
    request_id: Optional[str] = Field(None, max_length=MAX_REQUEST_ID_LENGTH)
    occurred_at: Optional[str] = Field(None, max_length=40)
    context: Optional[Dict[str, Any]] = None

    @field_validator("source")
    @classmethod
    def _known_source(cls, v: str) -> str:
        value = str(v or "").strip().lower()
        return value if value in CLIENT_ERROR_SOURCES else "unknown"

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, v: str) -> str:
        value = str(v or "").strip().lower()
        return value if value in CLIENT_ERROR_SEVERITIES else "error"

    @field_validator("request_id")
    @classmethod
    def _safe_request_id(cls, v: Optional[str]) -> Optional[str]:
        # Reused verbatim so a browser-supplied id can never inject a header or
        # forge a log field.
        return sanitize_request_id(v)

    @field_validator("context")
    @classmethod
    def _bounded_context(
        cls, v: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not v:
            return None
        trimmed: Dict[str, Any] = {}
        for key, value in list(v.items())[:MAX_CONTEXT_KEYS]:
            trimmed[str(key)[:60]] = str(value)[:MAX_CONTEXT_VALUE_LENGTH]
        return trimmed


class ClientErrorAck(BaseModel):
    """Acknowledgement returned to the browser after a report is recorded."""

    recorded: bool
    request_id: str


class AlertThresholds(BaseModel):
    api_p95_ms: float
    api_error_rate_pct: float
    challenge_generation_p95_ms: float
    min_observations: int
    critical_multiplier: float
    cooldown_seconds: int


class MetricsAlertsResponse(BaseModel):
    """Current state of the threshold alerts over the measured metrics."""

    enabled: bool
    evaluated_at: Optional[str] = None
    thresholds: AlertThresholds
    firing: List[Dict[str, Any]] = Field(default_factory=list)
    resolved: List[Dict[str, Any]] = Field(default_factory=list)
    active_count: int = 0
    worst_severity: Optional[str] = None


class LoggingStatusResponse(BaseModel):
    """What the logging subsystem actually installed at startup."""

    level: str
    format: str
    service: str
    environment: str
    handlers: List[str] = Field(default_factory=list)
    log_file: Optional[str] = None
    rotation: Optional[Dict[str, Any]] = None
    access_log: bool = True
    request_id_header: str


class ApiMetricsResponse(BaseModel):
    """GET /system/metrics — measured request and generation latency."""

    requests: Dict[str, Any] = Field(default_factory=dict)
    challenge_generation: Dict[str, Any] = Field(default_factory=dict)
