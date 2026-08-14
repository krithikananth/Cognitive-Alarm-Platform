"""Add adapted_difficulty on user_profiles (separate from preference).

Revision ID: 20260723_adapted_difficulty
Revises: 20260723_streak_watermarks
Create Date: 2026-07-23

Additive-only migration. Profile Preference (``difficulty_preference``) stays
user-controlled; the adaptive engine persists ±1 shifts into
``adapted_difficulty`` only. Existing rows backfill adapted = preference.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "20260723_adapted_difficulty"
down_revision: Union[str, None] = "20260723_streak_watermarks"
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

    if not _column_exists(inspector, "user_profiles", "adapted_difficulty"):
        # Store enum NAMES (MEDIUM) to match difficulty_preference / SQLAlchemy.
        op.add_column(
            "user_profiles",
            sa.Column(
                "adapted_difficulty",
                sa.String(50),
                nullable=False,
                server_default="MEDIUM",
            ),
        )
        # Align working level with the saved user preference for existing rows.
        bind.execute(
            text(
                "UPDATE user_profiles "
                "SET adapted_difficulty = CAST(difficulty_preference AS TEXT)"
            )
        )
    else:
        # Repair lowercase .value leftovers from early VARCHAR default 'medium'.
        # Exact lowercase only — do not touch valid names like MEDIUM/HARD.
        # CAST is load-bearing on Postgres: the baseline creates both columns as
        # the ``difficultypreference`` enum, and neither TRIM nor a comparison
        # against non-label literals is defined for an enum. SQLite stores the
        # same column as VARCHAR, so it accepts the uncast form and hides this.
        bind.execute(
            text(
                "UPDATE user_profiles "
                "SET adapted_difficulty = difficulty_preference "
                "WHERE adapted_difficulty IS NULL "
                "OR TRIM(CAST(adapted_difficulty AS TEXT)) = '' "
                "OR CAST(adapted_difficulty AS TEXT) IN "
                "('beginner','easy','medium','hard','expert')"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_profiles" not in inspector.get_table_names():
        return

    if _column_exists(inspector, "user_profiles", "adapted_difficulty"):
        op.drop_column("user_profiles", "adapted_difficulty")
