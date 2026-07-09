"""
SQLAlchemy database session setup.

Creates the engine, session factory, and a FastAPI-compatible dependency
generator for request-scoped database sessions.
"""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# Build the SQLAlchemy engine.
# ``check_same_thread=False`` is required only for SQLite; harmless for
# other dialects.
_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
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
