"""Authentication dependencies for FastAPI routes."""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from app.core.cookies import access_cookie
from app.core import security_events
from app.core.security import oauth2_scheme_optional, verify_token
from app.core.security_events import log_security_event
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.token_service import TokenRevocationService

_CREDENTIALS_ERROR = {
    "status_code": status.HTTP_401_UNAUTHORIZED,
    "headers": {"WWW-Authenticate": "Bearer"},
}


def _unauthorized(detail: str, request: Optional[Request] = None) -> HTTPException:
    log_security_event(
        security_events.TOKEN_REJECTED,
        outcome=security_events.OUTCOME_FAILURE,
        request=request,
        reason=detail,
    )
    return HTTPException(detail=detail, **_CREDENTIALS_ERROR)


def _forbidden(detail: str, *, user: User, required: str) -> HTTPException:
    log_security_event(
        security_events.ACCESS_DENIED,
        outcome=security_events.OUTCOME_FAILURE,
        user_id=user.id,
        reason=detail,
        required_role=required,
        actual_role=getattr(user.role, "value", user.role),
    )
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User:
    """Dependency to get the currently authenticated user.

    Accepts either an ``Authorization: Bearer`` header (API clients, Swagger)
    or the HttpOnly session cookie used by the SPA, and rejects tokens that
    have been revoked by logout or a password reset.

    Args:
        request: Incoming request (used to read the session cookie).
        token: JWT access token from the Authorization header, if present.
        db: Database session.

    Returns:
        User object for the authenticated user.

    Raises:
        HTTPException: If the token is missing, invalid, revoked, or the user
            no longer exists / is deactivated.
    """
    token = token or access_cookie(request)
    if not token:
        raise _unauthorized("Not authenticated", request)

    # verify_token raises its own 401 for a malformed/expired/wrong-key token.
    # Re-raising it through _unauthorized keeps the response identical while
    # guaranteeing the rejection reaches the audit log — presenting an invalid
    # token is the single most common attack signal.
    try:
        payload = verify_token(token)
    except HTTPException as exc:
        raise _unauthorized(str(exc.detail), request) from exc
    if payload is None:
        raise _unauthorized("Could not validate credentials", request)

    token_type = payload.get("type")
    if token_type != "access":
        raise _unauthorized("Invalid token type", request)

    user_id: str = payload.get("sub")
    if user_id is None:
        raise _unauthorized("Could not validate credentials", request)

    if TokenRevocationService.is_revoked(db, payload.get("jti")):
        raise _unauthorized("Token has been revoked", request)

    user = (
        db.query(User)
        .options(joinedload(User.profile))
        .filter(User.id == user_id)
        .first()
    )
    if user is None:
        raise _unauthorized("User not found", request)

    if TokenRevocationService.is_superseded(payload, user):
        raise _unauthorized("Session is no longer valid", request)

    if not user.is_active:
        log_security_event(
            security_events.ACCESS_DENIED,
            outcome=security_events.OUTCOME_FAILURE,
            request=request,
            user_id=user.id,
            reason="Inactive user",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure the current user is an admin.

    Args:
        current_user: The authenticated user.

    Returns:
        User object if admin.

    Raises:
        HTTPException: If user is not an admin.
    """
    if current_user.role != UserRole.ADMIN:
        raise _forbidden(
            "Admin privileges required", user=current_user, required="admin"
        )
    return current_user


def get_current_coach(current_user: User = Depends(get_current_user)) -> User:
    """Dependency to ensure the current user may use the coach APIs.

    Admins are allowed through so platform operators can inspect the coaching
    surface, but they are scoped by the same assignment rules as coaches —
    seeing every user is the job of the ``/admin`` endpoints.

    Args:
        current_user: The authenticated user.

    Returns:
        User object if the role is wellness_coach or admin.

    Raises:
        HTTPException: If the user holds neither role.
    """
    if current_user.role not in (UserRole.WELLNESS_COACH, UserRole.ADMIN):
        raise _forbidden(
            "Wellness coach privileges required",
            user=current_user,
            required="wellness_coach",
        )
    return current_user
