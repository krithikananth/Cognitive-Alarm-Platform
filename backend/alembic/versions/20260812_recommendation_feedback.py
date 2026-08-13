"""Create recommendation_feedback so recommendation relevance can be measured.

Revision ID: 20260812_recommendation_feedback
Revises: 20260812_challenge_deliveries
Create Date: 2026-08-12

Additive-only. No recommendation generation logic or ranking depends on this
table; it only records what users said about the advice they were shown.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260812_recommendation_feedback"
down_revision: Union[str, None] = "20260812_challenge_deliveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "recommendation_feedback"


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
        sa.Column("recommendation_id", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False),
        sa.Column("stated_confidence", sa.Float(), nullable=True),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "recommendation_id", name="uq_recommendation_feedback_item"
        ),
    )
    op.create_index(f"ix_{TABLE}_id", TABLE, ["id"])
    op.create_index(f"ix_{TABLE}_user_id", TABLE, ["user_id"])
    op.create_index(f"ix_{TABLE}_user_created", TABLE, ["user_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _table_exists(inspector, TABLE):
        return
    op.drop_index(f"ix_{TABLE}_user_created", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_user_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_id", table_name=TABLE)
    op.drop_table(TABLE)
