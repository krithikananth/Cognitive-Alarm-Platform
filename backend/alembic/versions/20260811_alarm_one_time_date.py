"""Persist the calendar date of one-time alarms.

Revision ID: 20260811_alarm_one_time_date
Revises: 20260811_session_revocation
Create Date: 2026-08-11

``one_time_date`` used to be a request-only field: it shaped ``next_trigger_at``
at creation time and was then thrown away. Any later edit or re-enable
recomputed the trigger without it and silently rescheduled the alarm to
today/tomorrow. Storing it makes one-time alarms stable across their whole
lifecycle.

Additive-only and guarded, so it is safe on databases already provisioned by
``Base.metadata.create_all``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260811_alarm_one_time_date"
down_revision: Union[str, None] = "20260811_session_revocation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def upgrade() -> None:
    inspector = inspect(op.get_bind())

    if not _table_exists(inspector, "alarms"):
        return
    if "one_time_date" in _column_names(inspector, "alarms"):
        return

    op.add_column("alarms", sa.Column("one_time_date", sa.Date(), nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())

    if not _table_exists(inspector, "alarms"):
        return
    if "one_time_date" not in _column_names(inspector, "alarms"):
        return

    op.drop_column("alarms", "one_time_date")
