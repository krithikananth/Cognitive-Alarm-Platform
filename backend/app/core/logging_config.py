"""
Application logging configuration.

Before this module existed the project had no logging configuration at all: the
root logger had no handler, so Python's ``lastResort`` handler applied and every
``logger.info(...)`` call in the codebase was silently discarded while warnings
went to bare stderr with no timestamp, no level filtering and no way to tell
which request produced them.

:func:`configure_logging` installs an explicit configuration:

* a level taken from ``LOG_LEVEL`` instead of the implicit WARNING floor;
* a **structured JSON** formatter (``LOG_FORMAT=json``) so records can be
  shipped to any aggregator verbatim, or a readable console formatter for local
  work;
* a stdout handler — the container/orchestrator contract, switchable off with
  ``LOG_TO_CONSOLE=false`` for a quiet local terminal — plus an optional
  **size-based rotating file handler** so logs survive outside the container's
  ring buffer;
* a filter that stamps the current correlation id, service, environment and
  version on every record, whichever formatter is in use.

It is idempotent and safe to call from tests: handlers are rebuilt rather than
appended, so repeated calls cannot produce duplicate output.
"""

from __future__ import annotations

import json
import logging
import logging.config
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.request_context import NO_REQUEST_ID, get_request_id

#: Name of the logger used for the per-request access line.
ACCESS_LOGGER_NAME = "app.access"

#: Name of the logger used for monitoring alerts.
ALERT_LOGGER_NAME = "app.alerts"

#: Name of the logger used for browser-side error reports.
CLIENT_LOGGER_NAME = "app.client"

CONSOLE_FORMAT = (
    "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"
)

#: Third-party loggers that emit a record per outbound call at INFO.
NOISY_THIRD_PARTY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "multipart",
)

# Attributes the stdlib puts on every LogRecord. Anything outside this set was
# supplied by the caller via ``extra=`` and belongs in the structured output.
_RESERVED_RECORD_KEYS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"asctime", "message", "taskName"}

# Added by RequestContextFilter and emitted explicitly, so they must not be
# repeated inside the extras block.
_CONTEXT_KEYS = frozenset({"request_id", "service", "environment", "version"})

_configured = False
_active: Dict[str, Any] = {}


class RequestContextFilter(logging.Filter):
    """Stamp correlation and deployment identity onto every record."""

    def __init__(self, service: str, environment: str, version: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.version = version

    def filter(self, record: logging.LogRecord) -> bool:
        # An explicit request_id passed via extra= wins: background jobs can
        # attribute work back to the request that queued it.
        if not getattr(record, "request_id", None):
            record.request_id = get_request_id()
        record.service = self.service
        record.environment = self.environment
        record.version = self.version
        return True


class JsonLogFormatter(logging.Formatter):
    """Render one record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", NO_REQUEST_ID),
            "service": getattr(record, "service", "icap-backend"),
            "environment": getattr(record, "environment", "unknown"),
            "version": getattr(record, "version", "unknown"),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            payload["exception"] = {
                "type": getattr(record.exc_info[0], "__name__", "Exception"),
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_RECORD_KEYS
            and key not in _CONTEXT_KEYS
            and not key.startswith("_")
        }
        if extras:
            payload.update(extras)

        # default=str keeps a stray datetime/Decimal from killing the record.
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleLogFormatter(logging.Formatter):
    """Human-readable formatter that tolerates records made before the filter."""

    def format(self, record: logging.LogRecord) -> str:
        if not getattr(record, "request_id", None):
            record.request_id = NO_REQUEST_ID
        return super().format(record)


def resolve_log_directory() -> Path:
    """Absolute log directory — relative values resolve against ``backend/``."""
    configured = Path(str(settings.LOG_DIR or "logs")).expanduser()
    if configured.is_absolute():
        return configured
    # app/core/logging_config.py -> app/core -> app -> backend
    return Path(__file__).resolve().parents[2] / configured


def _normalized_level(value: Optional[str], fallback: str = "INFO") -> str:
    level = str(value or fallback).strip().upper()
    return level if level in logging._nameToLevel else fallback


def _base_config(
    level: str, fmt: str, service: str, *, console: bool = True
) -> Dict[str, Any]:
    handlers: Dict[str, Any] = {}
    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "formatter": fmt,
            "filters": ["request_context"],
            "stream": sys.stdout,
        }
    else:
        # A root logger with no handlers falls back to the stdlib lastResort
        # handler, which would print WARNING+ to stderr anyway.
        handlers["null"] = {"class": "logging.NullHandler"}
    sql_level = _normalized_level(settings.LOG_SQL_LEVEL, "WARNING")
    loggers: Dict[str, Any] = {
        "app": {"level": level, "propagate": True},
        "uvicorn": {"level": level, "handlers": [], "propagate": True},
        "uvicorn.error": {"level": level, "handlers": [], "propagate": True},
        # Uvicorn's own access log is unstructured and carries no correlation
        # id; RequestContextMiddleware emits ours instead.
        "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": False},
        "sqlalchemy.engine": {"level": sql_level, "propagate": True},
        "apscheduler": {
            "level": _normalized_level(settings.LOG_SCHEDULER_LEVEL, "WARNING"),
            "propagate": True,
        },
    }
    # Chatty transports would otherwise emit a line per outbound call at INFO
    # and bury the application's own records. DEBUG opts back in deliberately.
    if level != "DEBUG":
        for name in NOISY_THIRD_PARTY_LOGGERS:
            loggers[name] = {"level": "WARNING", "propagate": True}

    return {
        "version": 1,
        # Loggers are created at import time all over the codebase; disabling
        # them here would silence the entire application.
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": RequestContextFilter,
                "service": service,
                "environment": str(settings.ENVIRONMENT),
                "version": str(settings.VERSION),
            }
        },
        "formatters": {
            "json": {"()": JsonLogFormatter},
            "console": {
                "()": ConsoleLogFormatter,
                "fmt": CONSOLE_FORMAT,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "root": {"level": level, "handlers": list(handlers)},
        "loggers": loggers,
    }


def _build_file_handler(
    level: str, fmt: str, service: str
) -> Optional[RotatingFileHandler]:
    """Build the rotating file handler, or return ``None`` if it is unavailable."""
    directory = resolve_log_directory()
    path = directory / str(settings.LOG_FILE_NAME or "icap.log")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=max(1024, int(settings.LOG_FILE_MAX_BYTES)),
            backupCount=max(0, int(settings.LOG_FILE_BACKUP_COUNT)),
            encoding="utf-8",
            # delay=False so an unwritable path fails here, at startup, rather
            # than on the first error we were trying to record.
            delay=False,
        )
    except OSError:
        # Read-only root filesystem (the backend container runs read_only) or a
        # missing volume: stdout logging is used instead, so degrade rather
        # than refuse to boot.
        return None

    handler.setLevel(logging.getLevelName(level))
    handler.setFormatter(
        JsonLogFormatter()
        if fmt == "json"
        else ConsoleLogFormatter(fmt=CONSOLE_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    )
    handler.addFilter(
        RequestContextFilter(service, str(settings.ENVIRONMENT), str(settings.VERSION))
    )
    handler.name = "file"
    return handler


def configure_logging(*, force: bool = False) -> Dict[str, Any]:
    """Install the application-wide logging configuration.

    Returns a summary of what was actually installed — the file handler is
    best-effort, so the caller (and the tests) can see whether it took effect.
    """
    global _configured, _active

    if _configured and not force:
        return dict(_active)

    level = _normalized_level(settings.LOG_LEVEL)
    fmt = "json" if str(settings.LOG_FORMAT).strip().lower() == "json" else "console"
    service = str(settings.LOG_SERVICE_NAME or "icap-backend")

    # Reset first so the previous run's file handle is closed before a new one
    # opens the same path.
    reset_logging()

    # Built before the tree is installed so a failed file sink can veto the
    # console being switched off — the process must never log nowhere.
    file_handler = (
        _build_file_handler(level, fmt, service) if settings.LOG_TO_FILE else None
    )
    file_error = bool(settings.LOG_TO_FILE) and file_handler is None
    console = bool(settings.LOG_TO_CONSOLE) or file_handler is None

    logging.config.dictConfig(_base_config(level, fmt, service, console=console))

    log_file: Optional[str] = None
    if file_handler is not None:
        logging.getLogger().addHandler(file_handler)
        log_file = file_handler.baseFilename

    _active = {
        "level": level,
        "format": fmt,
        "service": service,
        "environment": str(settings.ENVIRONMENT),
        "handlers": [h.name or type(h).__name__ for h in logging.getLogger().handlers],
        "log_file": log_file,
        "rotation": {
            "max_bytes": int(settings.LOG_FILE_MAX_BYTES),
            "backup_count": int(settings.LOG_FILE_BACKUP_COUNT),
        }
        if log_file
        else None,
        "access_log": bool(settings.LOG_ACCESS_ENABLED),
    }
    _configured = True

    if file_error:
        logging.getLogger(__name__).warning(
            "File logging unavailable; continuing with stdout only",
            extra={"log_dir": str(resolve_log_directory())},
        )
    return dict(_active)


def logging_status() -> Dict[str, Any]:
    """What :func:`configure_logging` last installed (empty if never called)."""
    return dict(_active)


def is_logging_configured() -> bool:
    """Whether the application owns the logging tree in this process.

    Alembic's ``env.py`` checks this before running ``fileConfig``, which would
    otherwise replace the whole configuration during an in-process migration.
    """
    return _configured


def reset_logging() -> None:
    """Detach and close every root handler — used before reconfiguring."""
    global _configured, _active
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    _configured = False
    _active = {}
