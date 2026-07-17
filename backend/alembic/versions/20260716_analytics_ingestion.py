"""Create analytics_events table for the dedicated ingestion layer.

Revision ID: 20260716_analytics_ingestion
Revises: 20260716_attempt_log_audit
Create Date: 2026-07-16

Additive-only migration. Does not alter alarm / challenge / snooze tables.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260716_analytics_ingestion"
down_revision: Union[str, None] = "20260716_attempt_log_audit"
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

    if _table_exists(inspector, "analytics_events"):
        return

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="server"),
        sa.Column("event_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_analytics_events_id", "analytics_events", ["id"])
    op.create_index("ix_analytics_events_user_id", "analytics_events", ["user_id"])
    op.create_index(
        "ix_analytics_events_event_type", "analytics_events", ["event_type"]
    )
    op.create_index(
        "ix_analytics_events_created_at", "analytics_events", ["created_at"]
    )
    op.create_index(
        "ix_analytics_user_created",
        "analytics_events",
        ["user_id", "created_at"],
    )
    op.create_index("ix_analytics_event_type", "analytics_events", ["event_type"])
    op.create_index(
        "ix_analytics_event_type_created",
        "analytics_events",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_analytics_entity",
        "analytics_events",
        ["entity_type", "entity_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _table_exists(inspector, "analytics_events"):
        return

    for name in (
        "ix_analytics_entity",
        "ix_analytics_event_type_created",
        "ix_analytics_event_type",
        "ix_analytics_user_created",
        "ix_analytics_events_created_at",
        "ix_analytics_events_event_type",
        "ix_analytics_events_user_id",
        "ix_analytics_events_id",
    ):
        try:
            op.drop_index(name, table_name="analytics_events")
        except Exception:
            pass

    op.drop_table("analytics_events")
