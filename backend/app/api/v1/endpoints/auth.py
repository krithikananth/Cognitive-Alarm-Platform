"""
Authentication API endpoints.

Provides user registration, login, token refresh, Google OAuth2, and
current-user retrieval.
"""

from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.db.session import get_db
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserLogin, UserResponse, UserUpdate
from app.services.auth_service import AuthService
from app.utils.hashing import get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user account.

    Creates the user and provisions a default user profile with sensible
    defaults for sleep duration, timezone, and difficulty preference.
    """
    # Check for duplicate email
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Check for duplicate username
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=UserRole.USER,
        is_active=True,
        is_verified=False,
    )
    db.add(user)
    db.flush()

    # Create default profile
    tz = user_data.timezone or "UTC"
    default_profile = UserProfile(
        user_id=user.id,
        sleep_duration_hours=8.0,
        timezone=tz,
        difficulty_preference=DifficultyPreference.MEDIUM,
    )
    db.add(default_profile)
    db.commit()
    db.refresh(user)

    return user


@router.post(
    "/login",
    summary="Authenticate user",
)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Authenticate a user with email and password.

    Returns a pair of JWT tokens (access + refresh) on success.
    """
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    return AuthService.token_response(user)


class RefreshRequest(BaseModel):
    """JSON body for token refresh."""

    refresh_token: str = Field(..., description="Valid refresh JWT")


def _require_google_oauth_config() -> None:
    """Raise 501 when Google OAuth credentials are not configured."""
    if not settings.OAUTH2_GOOGLE_CLIENT_ID or not settings.OAUTH2_GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured",
        )


def _oauth_error_redirect(message: str) -> RedirectResponse:
    """Send the SPA back to login with an error query param."""
    query = urlencode({"error": message})
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL.rstrip('/')}/login?{query}",
        status_code=status.HTTP_302_FOUND,
    )


def _oauth_success_redirect(token_payload: dict) -> RedirectResponse:
    """Send JWT pair to the SPA OAuth callback route (localStorage flow)."""
    query = urlencode(
        {
            "access_token": token_payload["access_token"],
            "refresh_token": token_payload["refresh_token"],
            "token_type": token_payload["token_type"],
        }
    )
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL.rstrip('/')}/oauth/callback?{query}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get(
    "/oauth/google",
    summary="Start Google OAuth2 login",
    response_class=RedirectResponse,
)
def google_oauth_redirect():
    """Redirect the browser to Google's OAuth2 consent screen."""
    _require_google_oauth_config()

    params = urlencode(
        {
            "client_id": settings.OAUTH2_GOOGLE_CLIENT_ID,
            "redirect_uri": settings.OAUTH2_GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(
        url=f"{GOOGLE_AUTH_URL}?{params}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get(
    "/oauth/google/callback",
    summary="Google OAuth2 callback",
    response_class=RedirectResponse,
)
def google_oauth_callback(
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exchange the Google auth code, link/create the user, redirect with JWTs."""
    _require_google_oauth_config()

    if error:
        return _oauth_error_redirect(error)
    if not code:
        return _oauth_error_redirect("missing_authorization_code")

    try:
        with httpx.Client(timeout=15.0) as client:
            token_response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.OAUTH2_GOOGLE_CLIENT_ID,
                    "client_secret": settings.OAUTH2_GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.OAUTH2_GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            if token_response.status_code != 200:
                return _oauth_error_redirect("google_token_exchange_failed")

            google_tokens = token_response.json()
            access_token = google_tokens.get("access_token")
            if not access_token:
                return _oauth_error_redirect("google_access_token_missing")

            userinfo_response = client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_response.status_code != 200:
                return _oauth_error_redirect("google_userinfo_failed")

            user_info = userinfo_response.json()
    except httpx.HTTPError:
        return _oauth_error_redirect("google_request_failed")

    oauth_id = user_info.get("id")
    email = user_info.get("email")
    if not oauth_id or not email:
        return _oauth_error_redirect("google_profile_incomplete")

    try:
        user = AuthService.oauth_login_or_register(
            db,
            provider="google",
            oauth_id=str(oauth_id),
            email=email,
            full_name=user_info.get("name"),
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "oauth_login_failed"
        return _oauth_error_redirect(detail)

    return _oauth_success_redirect(AuthService.token_response(user))


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_db)):
    """Issue a new access token using a valid refresh token.

    The refresh token is verified to ensure it hasn't expired and
    the associated user account is still active.
    """
    payload = verify_token(body.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type — expected refresh token",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account deactivated",
        )

    new_token_data = {"sub": str(user.id), "role": user.role.value}
    new_access = create_access_token(data=new_token_data)
    new_refresh = create_refresh_token(data=new_token_data)

    return Token(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user",
)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's details."""
    return current_user


@router.put(
    "/me",
    response_model=UserResponse,
    summary="Update current user",
)
def update_me(
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the currently authenticated user's profile information."""
    update_data = user_data.model_dump(exclude_unset=True)

    if "email" in update_data:
        existing = (
            db.query(User)
            .filter(User.email == update_data["email"], User.id != current_user.id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )

    for field, value in update_data.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return current_user
