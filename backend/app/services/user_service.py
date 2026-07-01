"""
User management service layer.

Provides admin-oriented CRUD operations on user accounts, including
pagination, role updates, and soft-activation / deactivation.
"""

from typing import Dict, List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.schemas.user import UserUpdate


class UserService:
    """Service class for user management operations (mostly admin-facing)."""

    @staticmethod
    def get_users(
        db: Session, page: int = 1, per_page: int = 20
    ) -> Dict[str, object]:
        """
        Retrieve a paginated list of all users.

        Args:
            db: Active database session.
            page: Page number (1-indexed).
            per_page: Number of records per page.

        Returns:
            Dictionary with ``users``, ``total``, ``page``, and ``per_page``.
        """
        total: int = db.query(User).count()
        offset = (page - 1) * per_page
        users: List[User] = (
            db.query(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(per_page)
            .all()
        )
        return {
            "users": users,
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    @staticmethod
    def get_user(db: Session, user_id: int) -> User:
        """
        Retrieve a single user by primary key.

        Args:
            db: Active database session.
            user_id: Target user's primary key.

        Returns:
            The ``User`` instance.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user: Optional[User] = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with id {user_id} not found",
            )
        return user

    @staticmethod
    def update_user(
        db: Session, user_id: int, data: UserUpdate
    ) -> User:
        """
        Update a user's profile information.

        Only non-``None`` fields from *data* are applied.

        Args:
            db: Active database session.
            user_id: Target user's primary key.
            data: Validated update payload.

        Returns:
            The updated ``User`` instance.

        Raises:
            HTTPException: 404 if the user does not exist.
            HTTPException: 400 if the new email is already registered.
        """
        user = UserService.get_user(db, user_id)
        update_data = data.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"] != user.email:
            existing = (
                db.query(User)
                .filter(User.email == update_data["email"])
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email is already registered",
                )

        for field, value in update_data.items():
            setattr(user, field, value)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def delete_user(db: Session, user_id: int) -> bool:
        """
        Permanently delete a user and all associated data.

        Args:
            db: Active database session.
            user_id: Target user's primary key.

        Returns:
            ``True`` on success.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user = UserService.get_user(db, user_id)
        db.delete(user)
        db.commit()
        return True

    @staticmethod
    def update_user_role(
        db: Session, user_id: int, role: UserRole
    ) -> User:
        """
        Change a user's role.

        Args:
            db: Active database session.
            user_id: Target user's primary key.
            role: The new ``UserRole`` to assign.

        Returns:
            The updated ``User`` instance.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user = UserService.get_user(db, user_id)
        user.role = role
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def deactivate_user(db: Session, user_id: int) -> User:
        """
        Soft-deactivate a user account.

        Args:
            db: Active database session.
            user_id: Target user's primary key.

        Returns:
            The updated ``User`` instance with ``is_active=False``.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user = UserService.get_user(db, user_id)
        user.is_active = False
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def activate_user(db: Session, user_id: int) -> User:
        """
        Re-activate a deactivated user account.

        Args:
            db: Active database session.
            user_id: Target user's primary key.

        Returns:
            The updated ``User`` instance with ``is_active=True``.

        Raises:
            HTTPException: 404 if the user does not exist.
        """
        user = UserService.get_user(db, user_id)
        user.is_active = True
        db.commit()
        db.refresh(user)
        return user
