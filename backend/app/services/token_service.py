"""
JWT revocation service.

Backs logout and password-reset session invalidation:

- individual tokens are revoked by their ``jti`` (``revoked_tokens`` table),
- every outstanding token for a user can be invalidated at once by moving
  ``users.tokens_valid_after`` forward.

Both checks run on each authenticated request, so a revoked token stops working
immediately instead of lingering until its natural expiry.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.revoked_token import RevokedToken
from app.models.user import User

logger = logging.getLogger(__name__)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    """Treat naive DB timestamps as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class TokenRevocationService:
    """Records and enforces JWT revocation."""

    @staticmethod
    def revoke_token(
        db: Session,
        payload: Dict[str, Any],
        *,
        reason: str = "logout",
    ) -> bool:
        """Revoke a decoded token by its ``jti``. Returns True when recorded."""
        jti = payload.get("jti")
        if not jti:
            # Tokens minted before jti claims existed cannot be revoked
            # individually; the caller falls back to revoke_all_for_user.
            return False

        if TokenRevocationService.is_revoked(db, str(jti)):
            return True

        exp = payload.get("exp")
        expires_at = None
        if exp:
            try:
                expires_at = datetime.fromtimestamp(int(exp), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                expires_at = None

        user_id = payload.get("sub")
        try:
            user_id_int = int(user_id) if user_id is not None else None
        except (TypeError, ValueError):
            user_id_int = None

        db.add(
            RevokedToken(
                jti=str(jti),
                user_id=user_id_int,
                token_type=str(payload.get("type") or "access"),
                reason=reason,
                expires_at=expires_at,
            )
        )
        try:
            db.commit()
        except SQLAlchemyError:
            # Concurrent logout already inserted the same jti — still revoked.
            db.rollback()
            return TokenRevocationService.is_revoked(db, str(jti))
        return True

    @staticmethod
    def is_revoked(db: Session, jti: Optional[str]) -> bool:
        """Whether a token id has been explicitly revoked."""
        if not jti:
            return False
        return (
            db.query(RevokedToken.id)
            .filter(RevokedToken.jti == str(jti))
            .first()
            is not None
        )

    @staticmethod
    def revoke_all_for_user(
        db: Session, user: User, *, reason: str = "revoke_all"
    ) -> None:
        """Invalidate every token already issued to ``user``."""
        user.tokens_valid_after = datetime.now(timezone.utc)
        db.commit()
        logger.info("Revoked all sessions for user_id=%s (%s)", user.id, reason)

    @staticmethod
    def is_superseded(payload: Dict[str, Any], user: User) -> bool:
        """Whether the token predates the user's revoke-all cut-off."""
        cutoff = _as_aware(getattr(user, "tokens_valid_after", None))
        if cutoff is None:
            return False
        cutoff_ms = cutoff.timestamp() * 1000

        issued_ms = payload.get("iat_ms")
        if issued_ms is not None:
            try:
                return float(issued_ms) < cutoff_ms
            except (TypeError, ValueError):
                return True

        # Legacy token (no millisecond claim): assume it predates the cut-off.
        return True

    @staticmethod
    def purge_expired(db: Session) -> int:
        """Delete revocation rows whose tokens have expired anyway."""
        now = datetime.now(timezone.utc)
        deleted = (
            db.query(RevokedToken)
            .filter(RevokedToken.expires_at.isnot(None), RevokedToken.expires_at < now)
            .delete(synchronize_session=False)
        )
        db.commit()
        return int(deleted or 0)
