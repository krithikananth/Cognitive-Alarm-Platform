"""Add adaptive-difficulty streak watermarks on user_profiles.

Revision ID: 20260723_adaptive_streak_watermarks
Revises: 20260723_day_streak_last_wake
Create Date: 2026-07-23

Additive-only migration. Watermarks record the consecutive success/failure
streak value consumed by the last difficulty ±1 so display streaks can keep
climbing after an adapt without re-firing on every subsequent wake.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260723_adaptive_streak_watermarks"
down_revision: Union[str, None] = "20260723_day_streak_last_wake"
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

    if not _column_exists(inspector, "user_profiles", "last_adapted_success_streak"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "last_adapted_success_streak",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if not _column_exists(inspector, "user_profiles", "last_adapted_failure_streak"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "last_adapted_failure_streak",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_profiles" not in inspector.get_table_names():
        return

    if _column_exists(inspector, "user_profiles", "last_adapted_failure_streak"):
        op.drop_column("user_profiles", "last_adapted_failure_streak")

    if _column_exists(inspector, "user_profiles", "last_adapted_success_streak"):
        op.drop_column("user_profiles", "last_adapted_success_streak")
