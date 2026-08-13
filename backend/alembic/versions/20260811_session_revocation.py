"""Session revocation support (logout + password-reset invalidation).

Revision ID: 20260811_session_revocation
Revises: 20260810_admin_stats_covering_idx
Create Date: 2026-08-11

Additive-only:

- ``revoked_tokens`` stores the ``jti`` of every access/refresh token that was
  explicitly logged out, until the token would have expired anyway.
- ``users.tokens_valid_after`` invalidates *all* tokens issued before the
  instant it holds (password reset, revoke-all-sessions).

Guarded so it is safe on databases created by ``Base.metadata.create_all``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260811_session_revocation"
down_revision: Union[str, None] = "20260810_admin_stats_covering_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return inspect(op.get_bind())


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
    inspector = _inspector()

    if not _table_exists(inspector, "revoked_tokens"):
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "token_type", sa.String(length=20), nullable=False, server_default="access"
            ),
            sa.Column(
                "reason", sa.String(length=64), nullable=False, server_default="logout"
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "revoked_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True
        )
        op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
        op.create_index(
            "ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"]
        )
    else:
        existing = _index_names(inspector, "revoked_tokens")
        if "ix_revoked_tokens_expires_at" not in existing:
            op.create_index(
                "ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"]
            )

    if _table_exists(inspector, "users"):
        if "tokens_valid_after" not in _column_names(inspector, "users"):
            op.add_column(
                "users", sa.Column("tokens_valid_after", sa.DateTime(), nullable=True)
            )


def downgrade() -> None:
    inspector = _inspector()

    if _table_exists(inspector, "users") and "tokens_valid_after" in _column_names(
        inspector, "users"
    ):
        op.drop_column("users", "tokens_valid_after")

    if _table_exists(inspector, "revoked_tokens"):
        op.drop_table("revoked_tokens")
