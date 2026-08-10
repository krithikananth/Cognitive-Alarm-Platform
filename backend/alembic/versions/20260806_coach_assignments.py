"""Create coach_assignments table scoping wellness coaches to their clients.

Revision ID: 20260806_coach_assignments
Revises: 20260723_adapted_difficulty
Create Date: 2026-08-06

Additive-only migration. Does not alter users or any analytics table.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260806_coach_assignments"
down_revision: Union[str, None] = "20260723_adapted_difficulty"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector, table: str) -> bool:
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "coach_assignments"):
        return

    op.create_table(
        "coach_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("coach_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["coach_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("coach_id", "client_id", name="uq_coach_assignment_pair"),
    )
    op.create_index("ix_coach_assignments_id", "coach_assignments", ["id"])
    op.create_index("ix_coach_assignments_coach_id", "coach_assignments", ["coach_id"])
    op.create_index("ix_coach_assignments_client_id", "coach_assignments", ["client_id"])
    op.create_index(
        "ix_coach_assignments_coach_active",
        "coach_assignments",
        ["coach_id", "is_active"],
    )
    op.create_index(
        "ix_coach_assignments_client_active",
        "coach_assignments",
        ["client_id", "is_active"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _table_exists(inspector, "coach_assignments"):
        return

    for name in (
        "ix_coach_assignments_client_active",
        "ix_coach_assignments_coach_active",
        "ix_coach_assignments_client_id",
        "ix_coach_assignments_coach_id",
        "ix_coach_assignments_id",
    ):
        try:
            op.drop_index(name, table_name="coach_assignments")
        except Exception:
            pass

    op.drop_table("coach_assignments")
