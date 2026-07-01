"""
Declarative base and model imports for SQLAlchemy.

All model modules are imported here so that ``Base.metadata`` knows about
every table when Alembic (or ``create_all``) inspects it.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base class for all ORM models."""

    pass


# ── Import every model so metadata is populated ──────────────────────
# These imports have the side-effect of registering each model's table
# with ``Base.metadata``.  They MUST remain here (or be triggered before
# any ``create_all`` / ``metadata.sorted_tables`` call).
from app.models.user import User  # noqa: F401, E402
from app.models.profile import UserProfile  # noqa: F401, E402
from app.models.alarm import Alarm  # noqa: F401, E402
