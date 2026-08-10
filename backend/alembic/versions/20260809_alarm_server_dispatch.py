"""Server-side alarm dispatch bookkeeping.

Revision ID: 20260809_alarm_dispatch
Revises: 20260807_dashboard_perf_idx
Create Date: 2026-08-09

Additive-only migration supporting backend-driven alarm ringing:

- ``alarms.last_notified_trigger_at`` records which trigger instant already had
  a ring notification queued, so restarts and overlapping sweeps cannot
  double-ring the same alarm.
- ``ix_alarms_active_next_trigger`` backs the dispatcher's cross-user sweep.
- The ``notificationtype`` enum gains ``ALARM_TRIGGER`` on PostgreSQL. SQLite
  stores enums as plain VARCHAR, so no change is needed there.

Every step is guarded so the migration is safe on databases created by
``Base.metadata.create_all``, which already contain the newer definitions.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260809_alarm_dispatch"
down_revision: Union[str, None] = "20260807_dashboard_perf_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "ix_alarms_active_next_trigger"


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


def _index_names(inspector, table: str) -> set:
    try:
        return {idx["name"] for idx in inspector.get_indexes(table)}
    except Exception:
        return set()


def _add_enum_value(bind) -> None:
    """Extend the PostgreSQL ``notificationtype`` enum in place."""
    if bind.dialect.name != "postgresql":
        return
    # IF NOT EXISTS makes this idempotent; it cannot run inside a transaction
    # block on PostgreSQL < 12, hence the autocommit connection.
    with bind.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as conn:
        conn.exec_driver_sql(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'ALARM_TRIGGER'"
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "alarms"):
        if "last_notified_trigger_at" not in _column_names(inspector, "alarms"):
            op.add_column(
                "alarms",
                sa.Column(
                    "last_notified_trigger_at", sa.DateTime(), nullable=True
                ),
            )
        if _INDEX_NAME not in _index_names(inspector, "alarms"):
            op.create_index(
                _INDEX_NAME, "alarms", ["is_active", "next_trigger_at"]
            )

    _add_enum_value(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _table_exists(inspector, "alarms"):
        return

    if _INDEX_NAME in _index_names(inspector, "alarms"):
        op.drop_index(_INDEX_NAME, table_name="alarms")
    if "last_notified_trigger_at" in _column_names(inspector, "alarms"):
        op.drop_column("alarms", "last_notified_trigger_at")

    # PostgreSQL cannot remove a value from an enum type; ALARM_TRIGGER is
    # left in place. It is inert once no rows reference it.
