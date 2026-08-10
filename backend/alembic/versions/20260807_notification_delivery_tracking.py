"""Add delivery tracking and retry bookkeeping to the notification tables.

Revision ID: 20260807_notif_delivery
Revises: 20260806_coach_assignments
Create Date: 2026-08-07

Additive-only migration. Adds delivery timestamps, attempt counters, retry
scheduling, and failure reasons to ``notifications``, plus token health
columns to ``user_device_tokens`` used for invalid-FCM-token cleanup.

Every step is guarded so the migration is safe on databases where the
notification tables were created by ``Base.metadata.create_all`` and already
contain the newer columns.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260807_notif_delivery"
down_revision: Union[str, None] = "20260806_coach_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NOTIFICATION_COLUMNS = (
    ("delivered_at", sa.Column("delivered_at", sa.DateTime(), nullable=True)),
    (
        "push_attempts",
        sa.Column(
            "push_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    ),
    (
        "email_attempts",
        sa.Column(
            "email_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    ),
    ("next_retry_at", sa.Column("next_retry_at", sa.DateTime(), nullable=True)),
    ("last_error", sa.Column("last_error", sa.String(length=500), nullable=True)),
)

_DEVICE_TOKEN_COLUMNS = (
    ("last_success_at", sa.Column("last_success_at", sa.DateTime(), nullable=True)),
    (
        "failure_count",
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    ),
    ("deactivated_at", sa.Column("deactivated_at", sa.DateTime(), nullable=True)),
    (
        "deactivated_reason",
        sa.Column("deactivated_reason", sa.String(length=255), nullable=True),
    ),
)


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


def _index_names(inspector, table: str) -> set:
    try:
        return {idx["name"] for idx in inspector.get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "notifications"):
        existing = _column_names(inspector, "notifications")
        for name, column in _NOTIFICATION_COLUMNS:
            if name not in existing:
                op.add_column("notifications", column)

        if "ix_notifications_retry" not in _index_names(inspector, "notifications"):
            op.create_index(
                "ix_notifications_retry", "notifications", ["next_retry_at"]
            )

    if _table_exists(inspector, "user_device_tokens"):
        existing = _column_names(inspector, "user_device_tokens")
        for name, column in _DEVICE_TOKEN_COLUMNS:
            if name not in existing:
                op.add_column("user_device_tokens", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "user_device_tokens"):
        existing = _column_names(inspector, "user_device_tokens")
        for name, _ in reversed(_DEVICE_TOKEN_COLUMNS):
            if name in existing:
                op.drop_column("user_device_tokens", name)

    if _table_exists(inspector, "notifications"):
        if "ix_notifications_retry" in _index_names(inspector, "notifications"):
            op.drop_index("ix_notifications_retry", table_name="notifications")

        existing = _column_names(inspector, "notifications")
        for name, _ in reversed(_NOTIFICATION_COLUMNS):
            if name in existing:
                op.drop_column("notifications", name)
