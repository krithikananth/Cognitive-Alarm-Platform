"""
Authentication service layer.

Encapsulates registration, login, token creation / refresh, and user
look-up logic, keeping endpoint handlers thin.
"""

from typing import Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_refresh_token, verify_token
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.utils.hashing import get_password_hash, verify_password


class AuthService:
    """Service class that handles all authentication-related operations."""

    @staticmethod
    def register_user(db: Session, user_data: UserCreate) -> User:
        """
        Register a new user account.

        Validates email and username uniqueness, hashes the password,
        creates the ``User`` row, and provisions a default ``UserProfile``.

        Args:
            db: Active database session.
            user_data: Validated registration payload.

        Returns:
            The newly created ``User`` instance.

        Raises:
            HTTPException: 400 if the email or username is already taken.
        """
        # ── Uniqueness checks ────────────────────────────────────────
        existing_email = (
            db.query(User).filter(User.email == user_data.email).first()
        )
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered",
            )

        existing_username = (
            db.query(User).filter(User.username == user_data.username).first()
        )
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username is already taken",
            )

        # ── Create user ──────────────────────────────────────────────
        new_user = User(
            email=user_data.email,
            username=user_data.username,
            hashed_password=get_password_hash(user_data.password),
            full_name=user_data.full_name,
            role=UserRole.USER,
            is_active=True,
            is_verified=False,
        )
        db.add(new_user)
        db.flush()  # assigns new_user.id

        # ── Create default profile ───────────────────────────────────
        default_profile = UserProfile(
            user_id=new_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
        )
        db.add(default_profile)
        db.commit()
        db.refresh(new_user)

        return new_user

    @staticmethod
    def authenticate_user(
        db: Session, email: str, password: str
    ) -> Optional[User]:
        """
        Authenticate a user with email and password.

        Args:
            db: Active database session.
            email: Email address supplied at login.
            password: Plain-text password supplied at login.

        Returns:
            The ``User`` if credentials are valid, otherwise ``None``.
        """
        user: Optional[User] = (
            db.query(User).filter(User.email == email).first()
        )
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def create_tokens(user: User) -> Dict[str, str]:
        """
        Generate access and refresh tokens for the given user.

        Args:
            user: The authenticated ``User`` instance.

        Returns:
            Dictionary with ``access_token``, ``refresh_token``, and
            ``token_type`` keys.
        """
        token_data = {"sub": str(user.id), "role": user.role.value}
        return {
            "access_token": create_access_token(data=token_data),
            "refresh_token": create_refresh_token(data=token_data),
            "token_type": "bearer",
        }

    @staticmethod
    def refresh_access_token(db: Session, refresh_token: str) -> Dict[str, str]:
        """
        Issue a new access token using a valid refresh token.

        The refresh token is verified and the user is re-fetched to ensure
        the account is still active.

        Args:
            db: Active database session.
            refresh_token: The JWT refresh token string.

        Returns:
            Dictionary with new ``access_token``, the same ``refresh_token``,
            and ``token_type``.

        Raises:
            HTTPException: 401 if the refresh token is invalid, expired, or
                the user no longer exists / is inactive.
        """
        payload = verify_token(refresh_token)
        token_type = payload.get("type")
        if token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type — expected refresh token",
            )

        user_id = payload.get("sub")
        user: Optional[User] = (
            db.query(User).filter(User.id == int(user_id)).first()
        )
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or account deactivated",
            )

        token_data = {"sub": str(user.id), "role": user.role.value}
        return {
            "access_token": create_access_token(data=token_data),
            "refresh_token": refresh_token,  # reuse existing refresh token
            "token_type": "bearer",
        }

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """
        Look up a user by email address.

        Args:
            db: Active database session.
            email: Email to search for.

        Returns:
            The matching ``User`` or ``None``.
        """
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """
        Look up a user by primary key.

        Args:
            db: Active database session.
            user_id: User primary key.

        Returns:
            The matching ``User`` or ``None``.
        """
        return db.query(User).filter(User.id == user_id).first()
