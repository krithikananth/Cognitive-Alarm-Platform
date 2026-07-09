"""
FastAPI dependency injection helpers for authentication and RBAC.

Provides reusable dependencies to extract and validate the current user
from the JWT bearer token and enforce role-based access control.
"""

from typing import List

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import oauth2_scheme, verify_token
from app.db.session import get_db
from app.models.user import User, UserRole


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the JWT bearer token and return the corresponding ``User``.

    Args:
        token: JWT extracted from the ``Authorization`` header.
        db: Database session (injected).

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        HTTPException: 401 if the token is invalid or the user is not found.
    """
    payload = verify_token(token)
    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user: User | None = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Ensure the authenticated user's account is active.

    Args:
        current_user: The user resolved from the JWT (injected).

    Returns:
        The same ``User`` if active.

    Raises:
        HTTPException: 403 if the user account has been deactivated.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return current_user


class RoleChecker:
    """
    Callable dependency that enforces role-based access control.

    Usage::

        require_admin = RoleChecker([UserRole.ADMIN])

        @router.get("/admin-only", dependencies=[Depends(require_admin)])
        def admin_endpoint(): ...

    Args:
        allowed_roles: List of ``UserRole`` values that are permitted.
    """

    def __init__(self, allowed_roles: List[UserRole]) -> None:
        """
        Initialise the checker with the roles that should be allowed.

        Args:
            allowed_roles: Roles that grant access.
        """
        self.allowed_roles = allowed_roles

    def __call__(
        self,
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        """
        Verify the current user has one of the allowed roles.

        Args:
            current_user: The active user (injected).

        Returns:
            The same ``User`` if authorised.

        Raises:
            HTTPException: 403 if the user's role is not in the allowed set.
        """
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user


# ── Pre-built role checkers ──────────────────────────────────────────
require_admin = RoleChecker([UserRole.ADMIN])
require_coach = RoleChecker([UserRole.ADMIN, UserRole.WELLNESS_COACH])
