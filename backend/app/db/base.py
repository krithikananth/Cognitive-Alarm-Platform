"""
Declarative base for SQLAlchemy ORM models.

Only defines ``Base``.  Model imports are done in ``alembic/env.py``
and in ``app/db/init_db.py`` to avoid circular imports.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all ORM models."""

    pass
