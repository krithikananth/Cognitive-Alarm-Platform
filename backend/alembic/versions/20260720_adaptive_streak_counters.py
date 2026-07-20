"""Add consecutive adaptive-difficulty streak counters on user_profiles.

Revision ID: 20260720_adaptive_streak_counters
Revises: 20260716_analytics_ingestion
Create Date: 2026-07-20

Additive-only migration. Existing users default to 0 / 0 so streak tracking
starts clean without breaking profiles or APIs.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260720_adaptive_streak_counters"
down_revision: Union[str, None] = "20260716_analytics_ingestion"
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

    if not _column_exists(inspector, "user_profiles", "consecutive_success_streak"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "consecutive_success_streak",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    # Re-inspect after potential add so the second check is accurate
    inspector = inspect(bind)
    if not _column_exists(inspector, "user_profiles", "consecutive_failure_streak"):
        op.add_column(
            "user_profiles",
            sa.Column(
                "consecutive_failure_streak",
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

    if _column_exists(inspector, "user_profiles", "consecutive_failure_streak"):
        op.drop_column("user_profiles", "consecutive_failure_streak")

    inspector = inspect(bind)
    if _column_exists(inspector, "user_profiles", "consecutive_success_streak"):
        op.drop_column("user_profiles", "consecutive_success_streak")
