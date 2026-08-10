"""Authentication dependencies for FastAPI routes."""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.security import oauth2_scheme, verify_token
from app.db.session import get_db
from app.models.user import User, UserRole


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency to get the currently authenticated user.

    Args:
        token: JWT access token from Authorization header.
        db: Database session.

    Returns:
        User object for the authenticated user.

    Raises:
        HTTPException: If token is invalid or user not found.
    """
    payload = verify_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        db.query(User)
        .options(joinedload(User.profile))
        .filter(User.id == user_id)
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wellness coach privileges required",
        )
    return current_user
