"""Alembic environment configuration for ICAP.

This module configures Alembic to work with the application's SQLAlchemy
models, enabling automatic migration generation and execution.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Ensure the backend directory is on sys.path so we can import app modules
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402

# Import all model modules so Base.metadata is fully populated
from app.models import user  # noqa: E402, F401
from app.models import profile  # noqa: E402, F401
from app.models import alarm  # noqa: E402, F401
from app.models import challenge_session  # noqa: E402, F401
from app.models import alarm_wake_event  # noqa: E402, F401
from app.models import alarm_snooze_event  # noqa: E402, F401
from app.models import analytics_event  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini
# ---------------------------------------------------------------------------
config = context.config

# Prefer app settings / DATABASE_URL env over alembic.ini default
database_url = os.getenv("DATABASE_URL") or settings.DATABASE_URL
if database_url:
    # configparser interpolates `%` — escape for URLs that contain them
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Set up Python logging from the config file
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData object for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
