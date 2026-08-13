"""
SQLAlchemy database session setup.

Creates the engine, session factory, and a FastAPI-compatible dependency
generator for request-scoped database sessions.
"""

from typing import Any, Dict, Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Build the SQLAlchemy engine.
# ``check_same_thread=False`` is required only for SQLite; harmless for
# other dialects.
_connect_args = {}
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    _connect_args["check_same_thread"] = False

# Connection pool sizing. FastAPI runs every sync endpoint in a threadpool, so
# concurrent users hold concurrent connections: with the SQLAlchemy defaults
# (pool 5, overflow 10) the 11th simultaneous request blocks on checkout and
# the queue wait is billed to the user as latency. These are now explicit and
# tunable so capacity can be raised without a code change.
# SQLite pools do not accept sizing arguments, so they are omitted there.
_pool_args: Dict[str, Any] = {}
if not _is_sqlite:
    _pool_args = {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT_SECONDS,
        "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
    }

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
    **_pool_args,
)

# Session factory bound to the engine.  ``autocommit`` and ``autoflush``
# are disabled so that callers have explicit control over transactions.
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a scoped SQLAlchemy session.

    The session is automatically closed after the request completes,
    regardless of whether the request succeeded or raised an exception.

    Yields:
        A SQLAlchemy ``Session`` instance.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
