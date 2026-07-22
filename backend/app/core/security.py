"""
Security utilities for JWT token creation, verification, and OAuth2 scheme.

Provides helper functions to create short-lived access tokens, longer-lived
refresh tokens, and to verify / decode incoming JWT tokens. Uses python-jose
for all cryptographic operations.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import settings

# OAuth2 scheme that extracts the bearer token from the Authorization header.
# tokenUrl must match POST /auth/token (OAuth2 password form) used by Swagger Authorize.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        data: Payload dictionary; must include a ``sub`` claim.
        expires_delta: Custom expiry duration.  Falls back to
            ``settings.ACCESS_TOKEN_EXPIRE_MINUTES`` when *None*.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create a signed JWT refresh token with a longer expiry window.

    Args:
        data: Payload dictionary; must include a ``sub`` claim.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_password_reset_token(user_id: int) -> str:
    """Create a short-lived JWT used exclusively for password reset."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    to_encode = {
        "sub": str(user_id),
        "type": "password_reset",
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_email_verification_token(user_id: int) -> str:
    """Create a short-lived JWT used exclusively for email verification."""
    expire = datetime.now(timezone.utc) + timedelta(
        hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS
    )
    to_encode = {
        "sub": str(user_id),
        "type": "email_verification",
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Decode and verify a JWT token.

    Args:
        token: The raw JWT string.

    Returns:
        Decoded payload as a dictionary.

    Raises:
        HTTPException: 401 if the token is invalid, expired, or missing
            the required ``sub`` claim.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload: Dict[str, Any] = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception
