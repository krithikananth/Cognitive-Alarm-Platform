"""
Authentication API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.database import get_db, get_redis
from app.services.auth_service import AuthService
from app.schemas.user_schema import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh,
    PasswordResetRequest, PasswordReset, UserResponse,
)
from app.middleware.auth_middleware import get_current_user
from app.models.user import User
from app.config import settings


router = APIRouter(prefix="/auth", tags=["Authentication"])


# ═══════════════════════════════════════════
# Email/Password Auth
# ═══════════════════════════════════════════

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """Register a new user account."""
    service = AuthService(db)
    return await service.register(data)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login with email and password."""
    service = AuthService(db)
    return await service.login(data)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: TokenRefresh, db: AsyncSession = Depends(get_db)):
    """Refresh an expired access token."""
    service = AuthService(db)
    return await service.refresh_token(data.refresh_token)


@router.post("/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Logout by blacklisting the current access token."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    redis = get_redis()
    if redis:
        # Blacklist token for the remaining TTL
        await redis.setex(
            f"blacklist:{token}",
            settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "1",
        )
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get the current authenticated user."""
    return UserResponse.model_validate(current_user)


# ═══════════════════════════════════════════
# Password Reset
# ═══════════════════════════════════════════

@router.post("/forgot-password")
async def forgot_password(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """Request a password reset token."""
    service = AuthService(db)
    return await service.request_password_reset(data.email)


@router.post("/reset-password")
async def reset_password(data: PasswordReset, db: AsyncSession = Depends(get_db)):
    """Reset password using a valid reset token."""
    service = AuthService(db)
    return await service.reset_password(data.token, data.new_password)


# ═══════════════════════════════════════════
# OAuth2 — Google
# ═══════════════════════════════════════════

@router.get("/oauth/google")
async def google_oauth_redirect():
    """Redirect user to Google OAuth2 consent screen."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    redirect_uri = "http://localhost:8000/api/v1/auth/oauth/google/callback"
    scope = "openid email profile"
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={settings.GOOGLE_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={scope}&"
        f"access_type=offline"
    )
    return RedirectResponse(url=url)


@router.get("/oauth/google/callback")
async def google_oauth_callback(code: str, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth2 callback."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    redirect_uri = "http://localhost:8000/api/v1/auth/oauth/google/callback"

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to exchange code for token")

        tokens = token_response.json()

        # Get user info
        userinfo_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to get user info")

        user_info = userinfo_response.json()

    service = AuthService(db)
    result = await service.oauth_login_or_register(
        provider="google",
        oauth_id=user_info["id"],
        email=user_info["email"],
        full_name=user_info.get("name"),
        avatar_url=user_info.get("picture"),
    )

    # In production: redirect to frontend with tokens
    # For now, return JSON
    return result


# ═══════════════════════════════════════════
# OAuth2 — GitHub
# ═══════════════════════════════════════════

@router.get("/oauth/github")
async def github_oauth_redirect():
    """Redirect user to GitHub OAuth2 consent screen."""
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    redirect_uri = "http://localhost:8000/api/v1/auth/oauth/github/callback"
    url = (
        f"https://github.com/login/oauth/authorize?"
        f"client_id={settings.GITHUB_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"scope=user:email"
    )
    return RedirectResponse(url=url)


@router.get("/oauth/github/callback")
async def github_oauth_callback(code: str, db: AsyncSession = Depends(get_db)):
    """Handle GitHub OAuth2 callback."""
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            },
        )
        tokens = token_response.json()
        access_token = tokens.get("access_token")

        if not access_token:
            raise HTTPException(status_code=400, detail="Failed to get access token")

        # Get user info
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_info = user_response.json()

        # Get primary email
        email_response = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails = email_response.json()
        primary_email = next(
            (e["email"] for e in emails if e.get("primary")),
            user_info.get("email"),
        )

    service = AuthService(db)
    result = await service.oauth_login_or_register(
        provider="github",
        oauth_id=str(user_info["id"]),
        email=primary_email,
        full_name=user_info.get("name"),
        avatar_url=user_info.get("avatar_url"),
    )

    return result
