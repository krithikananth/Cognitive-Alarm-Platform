"""Create challenge_deliveries so served-but-unanswered challenges are recorded.

Revision ID: 20260812_challenge_deliveries
Revises: 20260811_engagement_notifs
Create Date: 2026-08-12

Additive-only. ``alarm_challenge_logs`` is untouched, so accuracy and every
metric derived from it are unchanged.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260812_challenge_deliveries"
down_revision: Union[str, None] = "20260811_engagement_notifs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "challenge_deliveries"


def _table_exists(inspector, table: str) -> bool:
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("alarm_id", sa.Integer(), nullable=False),
        sa.Column("challenge_type", sa.String(length=50), nullable=False),
        sa.Column("difficulty", sa.String(length=50), nullable=False),
        sa.Column("challenge_prompt", sa.Text(), nullable=False),
        sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("time_taken_seconds", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["alarm_id"], ["alarms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{TABLE}_id", TABLE, ["id"])
    op.create_index(f"ix_{TABLE}_user_id", TABLE, ["user_id"])
    op.create_index(f"ix_{TABLE}_alarm_id", TABLE, ["alarm_id"])
    op.create_index(f"ix_{TABLE}_user_issued", TABLE, ["user_id", "issued_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _table_exists(inspector, TABLE):
        return
    op.drop_index(f"ix_{TABLE}_user_issued", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_alarm_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_user_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_id", table_name=TABLE)
    op.drop_table(TABLE)
