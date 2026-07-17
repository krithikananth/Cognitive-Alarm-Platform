"""Week-2 attempt log solidity: indexes, backfill, snooze events.

Revision ID: 20260716_attempt_log_audit
Revises:
Create Date: 2026-07-16

Additive-only migration:
- Creates ``alarm_snooze_events`` (per-snooze audit trail)
- Adds query indexes on ``alarm_challenge_logs``
- Backfills null/empty difficulty + prompt (does not delete rows)
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "20260716_attempt_log_audit"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_names(inspector, table: str) -> set[str]:
    try:
        return {idx["name"] for idx in inspector.get_indexes(table) if idx.get("name")}
    except Exception:
        return set()


def _table_exists(inspector, table: str) -> bool:
    try:
        return table in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # ── alarm_snooze_events (new) ──────────────────────────────────
    if not _table_exists(inspector, "alarm_snooze_events"):
        op.create_table(
            "alarm_snooze_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("alarm_id", sa.Integer(), sa.ForeignKey("alarms.id"), nullable=False),
            sa.Column("snooze_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "snooze_limit_at_event", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("next_trigger_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    # Refresh inspector after possible create
    inspector = inspect(bind)
    snooze_indexes = _index_names(inspector, "alarm_snooze_events")
    for name, cols in (
        ("ix_alarm_snooze_events_id", ["id"]),
        ("ix_alarm_snooze_events_user_id", ["user_id"]),
        ("ix_alarm_snooze_events_alarm_id", ["alarm_id"]),
        ("ix_alarm_snooze_events_created_at", ["created_at"]),
        ("ix_alarm_snooze_events_user_created", ["user_id", "created_at"]),
        ("ix_alarm_snooze_events_alarm_created", ["alarm_id", "created_at"]),
    ):
        if name not in snooze_indexes and _table_exists(inspector, "alarm_snooze_events"):
            op.create_index(name, "alarm_snooze_events", cols)

    # ── Backfill challenge logs (no deletes) ───────────────────────
    if _table_exists(inspector, "alarm_challenge_logs"):
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET difficulty = 'medium' "
                "WHERE difficulty IS NULL OR TRIM(difficulty) = ''"
            )
        )
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET challenge_prompt = '' "
                "WHERE challenge_prompt IS NULL"
            )
        )
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET challenge_type = 'word_game' "
                "WHERE lower(challenge_type) = 'word'"
            )
        )
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET time_taken_seconds = 0 "
                "WHERE time_taken_seconds IS NULL OR time_taken_seconds < 0"
            )
        )
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET failed_attempts = 0 "
                "WHERE failed_attempts IS NULL OR failed_attempts < 0"
            )
        )
        op.execute(
            sa.text(
                "UPDATE alarm_challenge_logs SET points_earned = 0 "
                "WHERE points_earned IS NULL OR points_earned < 0"
            )
        )

        log_indexes = _index_names(inspector, "alarm_challenge_logs")
        for name, cols in (
            ("ix_alarm_challenge_logs_user_id", ["user_id"]),
            ("ix_alarm_challenge_logs_alarm_id", ["alarm_id"]),
            ("ix_alarm_challenge_logs_created_at", ["created_at"]),
            ("ix_alarm_challenge_logs_user_created", ["user_id", "created_at"]),
            ("ix_alarm_challenge_logs_alarm_created", ["alarm_id", "created_at"]),
        ):
            if name not in log_indexes:
                op.create_index(name, "alarm_challenge_logs", cols)

    # ── Wake-event query indexes (if table already exists) ─────────
    if _table_exists(inspector, "alarm_wake_events"):
        wake_indexes = _index_names(inspector, "alarm_wake_events")
        for name, cols in (
            ("ix_alarm_wake_events_user_id", ["user_id"]),
            ("ix_alarm_wake_events_alarm_id", ["alarm_id"]),
        ):
            if name not in wake_indexes:
                op.create_index(name, "alarm_wake_events", cols)


def downgrade() -> None:
    """
    Downgrade removes only objects introduced by this revision.

    Challenge-log rows and backfilled values are intentionally kept
    (data-preserving downgrade).
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "alarm_snooze_events"):
        for name in (
            "ix_alarm_snooze_events_alarm_created",
            "ix_alarm_snooze_events_user_created",
            "ix_alarm_snooze_events_created_at",
            "ix_alarm_snooze_events_alarm_id",
            "ix_alarm_snooze_events_user_id",
            "ix_alarm_snooze_events_id",
        ):
            if name in _index_names(inspector, "alarm_snooze_events"):
                op.drop_index(name, table_name="alarm_snooze_events")
        op.drop_table("alarm_snooze_events")

    if _table_exists(inspector, "alarm_challenge_logs"):
        log_indexes = _index_names(inspector, "alarm_challenge_logs")
        for name in (
            "ix_alarm_challenge_logs_alarm_created",
            "ix_alarm_challenge_logs_user_created",
            "ix_alarm_challenge_logs_created_at",
            "ix_alarm_challenge_logs_alarm_id",
            "ix_alarm_challenge_logs_user_id",
        ):
            if name in log_indexes:
                op.drop_index(name, table_name="alarm_challenge_logs")
