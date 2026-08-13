"""Challenge practice reminders and weekly progress recaps.

Revision ID: 20260811_engagement_notifs
Revises: 20260811_alarm_one_time_date
Create Date: 2026-08-11

Additive-only migration for two new notification types:

- ``notification_preferences.challenge_reminders_enabled`` and
  ``progress_updates_enabled`` give each type its own opt-out. Both default to
  on so existing users keep the same experience as new ones.
- The ``notificationtype`` enum gains ``CHALLENGE_REMINDER`` and
  ``PROGRESS_UPDATE`` on PostgreSQL. SQLite stores enums as plain VARCHAR
  (SQLAlchemy 2.0 emits no CHECK constraint), so no change is needed there.

Every step is guarded so the migration is safe on databases created by
``Base.metadata.create_all``, which already contain the newer definitions.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260811_engagement_notifs"
down_revision: Union[str, None] = "20260811_alarm_one_time_date"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "notification_preferences"
_NEW_COLUMNS = ("challenge_reminders_enabled", "progress_updates_enabled")
_NEW_ENUM_VALUES = ("CHALLENGE_REMINDER", "PROGRESS_UPDATE")


def _table_exists(inspector, table: str) -> bool:
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def _column_names(inspector, table: str) -> set:
    try:
        return {col["name"] for col in inspector.get_columns(table)}
    except Exception:
        return set()


def _add_enum_values(bind) -> None:
    """Extend the PostgreSQL ``notificationtype`` enum in place."""
    if bind.dialect.name != "postgresql":
        return
    # IF NOT EXISTS makes this idempotent; it cannot run inside a transaction
    # block on PostgreSQL < 12, hence the autocommit connection.
    with bind.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as conn:
        for value in _NEW_ENUM_VALUES:
            conn.exec_driver_sql(
                "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
                f"'{value}'"
            )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, _TABLE):
        existing = _column_names(inspector, _TABLE)
        for column in _NEW_COLUMNS:
            if column in existing:
                continue
            op.add_column(
                _TABLE,
                sa.Column(
                    column,
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )

    _add_enum_values(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _table_exists(inspector, _TABLE):
        return

    existing = _column_names(inspector, _TABLE)
    for column in _NEW_COLUMNS:
        if column in existing:
            op.drop_column(_TABLE, column)

    # PostgreSQL cannot remove a value from an enum type; the new values are
    # left in place. They are inert once no rows reference them.
