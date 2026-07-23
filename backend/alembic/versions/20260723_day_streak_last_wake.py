"""Add last_successful_wake_date for calendar Day Streak tracking.

Revision ID: 20260723_day_streak_last_wake
Revises: 20260720_adaptive_streak_counters
Create Date: 2026-07-23

Additive-only migration. Stores the local calendar date of the user's last
verified successful wake so Day Streak can continue, stay flat (same day),
or reset after a missed day.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260723_day_streak_last_wake"
down_revision: Union[str, None] = "20260720_adaptive_streak_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(inspector, table: str, column: str) -> bool:
    try:
        return any(col["name"] == column for col in inspector.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_profiles" not in inspector.get_table_names():
        return

    if not _column_exists(inspector, "user_profiles", "last_successful_wake_date"):
        op.add_column(
            "user_profiles",
            sa.Column("last_successful_wake_date", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_profiles" not in inspector.get_table_names():
        return

    if _column_exists(inspector, "user_profiles", "last_successful_wake_date"):
        op.drop_column("user_profiles", "last_successful_wake_date")
