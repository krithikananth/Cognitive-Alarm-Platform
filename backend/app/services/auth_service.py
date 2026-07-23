"""
Authentication service layer.

Encapsulates registration, login, token creation / refresh, OAuth account
linking, password reset, email verification, and user look-up logic,
keeping endpoint handlers thin.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    verify_token,
)
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole
from app.schemas.user import UserCreate
from app.services.email_service import EmailService
from app.utils.hashing import get_password_hash, verify_password

logger = logging.getLogger(__name__)

# Generic responses — never reveal whether an email exists on the system.
_FORGOT_PASSWORD_MESSAGE = (
    "If an account with that email exists, a password reset link has been sent."
)
_RESEND_VERIFICATION_MESSAGE = (
    "If an unverified account with that email exists, a verification link has been sent."
)


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
            adapted_difficulty=DifficultyPreference.MEDIUM,
        )
        db.add(default_profile)
        db.commit()
        db.refresh(new_user)

        AuthService.send_verification_email(new_user)
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
    def _frontend_url(path: str, **query: str) -> str:
        """Build an absolute SPA URL with optional query parameters."""
        base = settings.FRONTEND_URL.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        url = f"{base}{suffix}"
        if query:
            url = f"{url}?{urlencode(query)}"
        return url

    @staticmethod
    def send_verification_email(user: User) -> None:
        """Issue a verification JWT and email the link (best-effort)."""
        if user.is_verified:
            return
        token = create_email_verification_token(user.id)
        verify_url = AuthService._frontend_url("/verify-email", token=token)
        try:
            EmailService.send_verification_email(
                to_email=user.email, verify_url=verify_url
            )
        except Exception:
            logger.exception(
                "Failed to send verification email to user_id=%s", user.id
            )

    @staticmethod
    def request_password_reset(db: Session, email: str) -> str:
        """
        Start a password-reset flow.

        Always returns the same generic message to avoid email enumeration.
        """
        user = AuthService.get_user_by_email(db, email)
        if user is not None and user.is_active:
            token = create_password_reset_token(user.id)
            reset_url = AuthService._frontend_url("/reset-password", token=token)
            try:
                EmailService.send_password_reset_email(
                    to_email=user.email, reset_url=reset_url
                )
            except Exception:
                logger.exception(
                    "Failed to send password-reset email to user_id=%s", user.id
                )
        return _FORGOT_PASSWORD_MESSAGE

    @staticmethod
    def reset_password(db: Session, token: str, new_password: str) -> str:
        """Validate a reset JWT and update the user's password hash."""
        try:
            payload = verify_token(token)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token",
            )

        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token",
            )

        user_id = payload.get("sub")
        try:
            user = AuthService.get_user_by_id(db, int(user_id))
        except (TypeError, ValueError):
            user = None

        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired password reset token",
            )

        user.hashed_password = get_password_hash(new_password)
        db.commit()
        return "Password has been reset successfully. You can now sign in."

    @staticmethod
    def verify_email(db: Session, token: str) -> str:
        """Validate a verification JWT and mark the user as verified."""
        try:
            payload = verify_token(token)
        except HTTPException:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired email verification token",
            )

        if payload.get("type") != "email_verification":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired email verification token",
            )

        user_id = payload.get("sub")
        try:
            user = AuthService.get_user_by_id(db, int(user_id))
        except (TypeError, ValueError):
            user = None

        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired email verification token",
            )

        if not user.is_verified:
            user.is_verified = True
            db.commit()
            db.refresh(user)

        return "Email verified successfully. You can now sign in."

    @staticmethod
    def resend_verification_email(db: Session, email: str) -> str:
        """
        Resend a verification email when the account is unverified.

        Always returns the same generic message to avoid email enumeration.
        """
        user = AuthService.get_user_by_email(db, email)
        if user is not None and user.is_active and not user.is_verified:
            AuthService.send_verification_email(user)
        return _RESEND_VERIFICATION_MESSAGE

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
                        adapted_difficulty=DifficultyPreference.MEDIUM,
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
