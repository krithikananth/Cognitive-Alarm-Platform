"""Add covering indexes for the admin statistics aggregates.

Revision ID: 20260810_admin_stats_idx
Revises: 20260809_alarm_dispatch
Create Date: 2026-08-10

Index-only migration derived from ``perf/benchmark.py`` measurements on an
891k-row dataset. ``GET /admin/statistics?days=365`` aggregates a full year of
raw events; both aggregates could already range-scan a timestamp index, but
neither index carried the grouped/summed columns, so every matching row still
had to be fetched from the table:

- ``alarm_challenge_logs``: 329k row lookups for the type/difficulty
  breakdown — 737 ms measured.
- ``alarm_wake_events``: 165k row lookups for the activity histograms and the
  dismiss-method outcome breakdown — 539 ms measured.

Widening the two timestamp indexes to cover those columns turns both into
index-only scans (297 ms and 226 ms measured on the same dataset). The
trade-off is write amplification on two append-heavy tables, which is why the
columns are limited to exactly what the aggregates read.

Adding indexes is non-destructive and does not alter query results. Each step
is guarded so the migration is idempotent on databases created via
``Base.metadata.create_all``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "20260810_admin_stats_idx"
down_revision: Union[str, None] = "20260809_alarm_dispatch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "ix_alarm_challenge_logs_created_breakdown",
        "alarm_challenge_logs",
        ["created_at", "challenge_type", "difficulty", "is_correct", "points_earned"],
    ),
    (
        "ix_alarm_wake_events_dismissed_outcome",
        "alarm_wake_events",
        ["dismissed_at", "verified", "dismiss_method", "time_to_dismiss_seconds"],
    ),
)


def _existing_indexes(inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create the admin statistics covering indexes when missing."""
    inspector = inspect(op.get_bind())
    for name, table, columns in _INDEXES:
        if not inspector.has_table(table):
            continue
        if name in _existing_indexes(inspector, table):
            continue
        op.create_index(name, table, columns)


def downgrade() -> None:
    """Drop the admin statistics covering indexes when present."""
    inspector = inspect(op.get_bind())
    for name, table, _columns in reversed(_INDEXES):
        if name in _existing_indexes(inspector, table):
            op.drop_index(name, table_name=table)
