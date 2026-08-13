"""
Revoked JWT registry.

JWTs are stateless, so logout must record the token's unique ``jti`` until it
would have expired anyway. ``get_current_user`` and the refresh endpoint reject
any token whose ``jti`` appears here.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.db.base import Base


class RevokedToken(Base):
    """A single access or refresh token that may no longer authenticate."""

    __tablename__ = "revoked_tokens"
    __table_args__ = (
        # Purge sweeps delete everything already past its natural expiry.
        Index("ix_revoked_tokens_expires_at", "expires_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    jti = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    token_type = Column(String(20), nullable=False, default="access")
    reason = Column(String(64), nullable=False, default="logout")
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
