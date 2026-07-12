"""
Authentication service layer.

Encapsulates registration, login, token creation / refresh, OAuth account
linking, and user look-up logic, keeping endpoint handlers thin.
"""

from __future__ import annotations

import re
import secrets
from typing import Any, Dict, Optional

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
        """
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
        db.flush()

        tz = user_data.timezone or "UTC"
        default_profile = UserProfile(
            user_id=new_user.id,
            sleep_duration_hours=8.0,
            timezone=tz,
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
        """Authenticate a user with email and password."""
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
        """Generate access and refresh tokens for the given user."""
        token_data = {"sub": str(user.id), "role": user.role.value}
        return {
            "access_token": create_access_token(data=token_data),
            "refresh_token": create_refresh_token(data=token_data),
            "token_type": "bearer",
        }

    @staticmethod
    def token_response(user: User) -> Dict[str, Any]:
        """Build the same login payload shape used by ``POST /auth/login``."""
        tokens = AuthService.create_tokens(user)
        return {
            **tokens,
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
            },
        }

    @staticmethod
    def refresh_access_token(db: Session, refresh_token: str) -> Dict[str, str]:
        """Issue a new access + refresh token pair from a valid refresh JWT."""
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

        return AuthService.create_tokens(user)

    @staticmethod
    def get_user_by_email(db: Session, email: str) -> Optional[User]:
        """Look up a user by email address."""
        return db.query(User).filter(User.email == email).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        """Look up a user by primary key."""
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def _unique_username(db: Session, email: str) -> str:
        """Derive a unique username from an email local-part."""
        local = email.split("@", 1)[0].lower()
        base = re.sub(r"[^a-zA-Z0-9_]", "", local)[:80] or "user"
        candidate = base
        suffix = 1
        while db.query(User).filter(User.username == candidate).first():
            candidate = f"{base}{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def oauth_login_or_register(
        db: Session,
        *,
        provider: str,
        oauth_id: str,
        email: str,
        full_name: Optional[str] = None,
    ) -> User:
        """
        Find or create a user for an OAuth provider identity.

        Lookup order:
        1. Existing ``(oauth_provider, oauth_id)`` pair
        2. Existing account with the same email (link OAuth fields)
        3. Create a new verified user with a random password placeholder
        """
        if not email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth provider did not return an email address",
            )

        user = (
            db.query(User)
            .filter(
                User.oauth_provider == provider,
                User.oauth_id == oauth_id,
            )
            .first()
        )

        if user is None:
            user = db.query(User).filter(User.email == email).first()
            if user is not None:
                user.oauth_provider = provider
                user.oauth_id = oauth_id
                user.is_verified = True
                if full_name and not user.full_name:
                    user.full_name = full_name
            else:
                user = User(
                    email=email,
                    username=AuthService._unique_username(db, email),
                    hashed_password=get_password_hash(secrets.token_urlsafe(32)),
                    full_name=full_name,
                    role=UserRole.USER,
                    is_active=True,
                    is_verified=True,
                    oauth_provider=provider,
                    oauth_id=oauth_id,
                )
                db.add(user)
                db.flush()
                db.add(
                    UserProfile(
                        user_id=user.id,
                        sleep_duration_hours=8.0,
                        timezone="UTC",
                        difficulty_preference=DifficultyPreference.MEDIUM,
                    )
                )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated",
            )

        db.commit()
        db.refresh(user)
        return user
