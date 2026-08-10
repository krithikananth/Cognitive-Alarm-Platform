"""Add dashboard read-path indexes.

Revision ID: 20260807_dashboard_perf_idx
Revises: 20260807_notif_delivery
Create Date: 2026-08-07

Index-only migration derived from ``perf/benchmark.py`` measurements on an
891k-row dataset. Every index below replaces a full table scan that was
observed in a captured query plan for a dashboard endpoint:

- ``alarms`` had no index on ``user_id`` at all, so every per-user alarm read
  (dashboard summary, profile stats, admin user list) scanned the table.
- ``alarm_wake_events`` had no index on ``dismissed_at``, so platform-wide
  admin windows scanned the table, and per-user windows could only use the
  single-column ``user_id`` index.
- ``users`` had no index on ``created_at``, used by admin growth windows.

Adding indexes is non-destructive and does not alter query results. Each step
is guarded so the migration is idempotent on databases created via
``Base.metadata.create_all``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "20260807_dashboard_perf_idx"
down_revision: Union[str, None] = "20260807_notif_delivery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_alarms_user_active", "alarms", ["user_id", "is_active"]),
    ("ix_alarms_user_next_trigger", "alarms", ["user_id", "next_trigger_at"]),
    (
        "ix_alarm_wake_events_user_dismissed",
        "alarm_wake_events",
        ["user_id", "dismissed_at"],
    ),
    (
        "ix_alarm_wake_events_user_verified_dismissed",
        "alarm_wake_events",
        ["user_id", "verified", "dismissed_at"],
    ),
    ("ix_alarm_wake_events_dismissed", "alarm_wake_events", ["dismissed_at"]),
    ("ix_users_created_at", "users", ["created_at"]),
)


def _existing_indexes(inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create the dashboard read-path indexes when missing."""
    inspector = inspect(op.get_bind())
    for name, table, columns in _INDEXES:
        if name in _existing_indexes(inspector, table):
            continue
        if not inspector.has_table(table):
            continue
        op.create_index(name, table, columns)


def downgrade() -> None:
    """Drop the dashboard read-path indexes when present."""
    inspector = inspect(op.get_bind())
    for name, table, _columns in reversed(_INDEXES):
        if name in _existing_indexes(inspector, table):
            op.drop_index(name, table_name=table)
