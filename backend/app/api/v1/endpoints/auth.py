"""
Authentication API endpoints.

Provides user registration, login, token refresh, Google OAuth2,
password reset, email verification, and current-user retrieval.
"""

from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.cookies import (
    access_cookie,
    clear_auth_cookies,
    refresh_cookie,
    set_auth_cookies,
)
from app.core.oauth_state import (
    StateError,
    clear_state_cookie,
    generate_state,
    set_state_cookie,
    state_cookie,
    verify_state,
)
from app.core.rate_limit import (
    clear_login_attempts,
    enforce_login_rate_limit,
    enforce_password_reset_rate_limit,
    register_failed_login,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.core import security_events
from app.core.security_events import log_security_event
from app.db.session import get_db
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginResponse,
    MessageResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SessionRevokedResponse,
    VerifyEmailRequest,
)
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserLogin, UserResponse, UserUpdate
from app.services.auth_service import AuthService
from app.services.token_service import TokenRevocationService
from app.utils.hashing import get_password_hash, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _bearer_token(request: Request) -> Optional[str]:
    """Extract the raw bearer token from the Authorization header."""
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1].strip() or None
    return None


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
        adapted_difficulty=DifficultyPreference.MEDIUM,
    )
    db.add(default_profile)
    db.commit()
    db.refresh(user)

    # Best-effort verification email — registration still succeeds if mail fails.
    AuthService.send_verification_email(user)

    return user


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset email",
)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Send a password-reset link when the email matches an active account.

    Always returns a generic success message to prevent email enumeration, and
    is rate limited per account and per caller to stop reset-mail flooding.
    """
    enforce_password_reset_rate_limit(request, body.email)
    message = AuthService.request_password_reset(db, body.email)
    return MessageResponse(message=message)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password with a one-time token",
)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Validate the reset JWT and update the account password.

    Rate limited so reset tokens cannot be brute-forced, and every existing
    session is invalidated once the password changes.
    """
    enforce_password_reset_rate_limit(request, "")
    message = AuthService.reset_password(db, body.token, body.new_password)
    return MessageResponse(message=message)


@router.post(
    "/verify-email",
    response_model=MessageResponse,
    summary="Verify email with a one-time token",
)
def verify_email(body: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Validate the verification JWT and mark the account as verified."""
    message = AuthService.verify_email(db, body.token)
    return MessageResponse(message=message)


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Resend email verification link",
)
def resend_verification(
    body: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Resend a verification email for an unverified account.

    Always returns a generic success message to prevent email enumeration.
    """
    enforce_password_reset_rate_limit(request, body.email)
    message = AuthService.resend_verification_email(db, body.email)
    return MessageResponse(message=message)


def _authenticate_active_user(
    db: Session, identifier: str, password: str, request: Request | None = None
) -> User:
    """Resolve email or username + password to an active user.

    Failed attempts are counted so repeated guesses lock the account/caller
    out; a success clears the counter.
    """
    enforce_login_rate_limit(request, identifier)

    user = AuthService.authenticate_user(db, identifier, password)
    if user is None:
        candidate = db.query(User).filter(User.username == identifier).first()
        if candidate and verify_password(password, candidate.hashed_password):
            user = candidate

    if user is None:
        register_failed_login(request, identifier)
        log_security_event(
            security_events.LOGIN_FAILED,
            outcome=security_events.OUTCOME_FAILURE,
            request=request,
            identifier=identifier,
            reason="invalid_credentials",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        register_failed_login(request, identifier)
        log_security_event(
            security_events.LOGIN_INACTIVE,
            outcome=security_events.OUTCOME_FAILURE,
            request=request,
            user_id=user.id,
            identifier=identifier,
            reason="account_deactivated",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    clear_login_attempts(request, identifier)
    log_security_event(
        security_events.LOGIN_SUCCEEDED,
        outcome=security_events.OUTCOME_SUCCESS,
        request=request,
        user_id=user.id,
        identifier=identifier,
        role=getattr(user.role, "value", user.role),
    )
    return user


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate user",
)
def login(
    credentials: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate a user with email and password.

    Sets HttpOnly session cookies (the SPA never touches the raw JWTs) and also
    returns the token pair for API/native clients.
    """
    user = _authenticate_active_user(
        db, credentials.email, credentials.password, request
    )
    payload = AuthService.token_response(user)
    set_auth_cookies(response, payload["access_token"], payload["refresh_token"])
    return payload


@router.post(
    "/token",
    response_model=Token,
    summary="OAuth2 password token (Swagger Authorize)",
)
def login_for_access_token(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 password-flow token endpoint for Swagger UI Authorize.

    Accepts ``application/x-www-form-urlencoded`` fields ``username`` and
    ``password`` (standard OAuth2). ``username`` may be the account email
    or username. Returns ``access_token`` / ``refresh_token`` / ``token_type``.
    """
    user = _authenticate_active_user(db, form_data.username, form_data.password, request)
    tokens = AuthService.create_tokens(user)
    set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
    return Token(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
    )


class RefreshRequest(BaseModel):
    """JSON body for token refresh (optional when the cookie is present)."""

    refresh_token: Optional[str] = Field(
        default=None, description="Valid refresh JWT"
    )


def _google_oauth_configured() -> bool:
    """Return True when both Google OAuth client credentials are present."""
    return bool(
        settings.OAUTH2_GOOGLE_CLIENT_ID and settings.OAUTH2_GOOGLE_CLIENT_SECRET
    )


def frontend_redirect_url(path: str, params: Optional[dict] = None) -> str:
    """Build an absolute SPA URL that is guaranteed to stay on our own origin.

    Every OAuth exit is a redirect whose target is partly built from values the
    provider handed back. The origin is therefore taken from ``FRONTEND_URL``
    and re-asserted after assembly: if anything in the path or query managed to
    change the scheme or host, the caller is sent to the bare frontend origin
    instead of off-site.
    """
    base = urlsplit(settings.FRONTEND_URL.rstrip("/") or "/")
    # A leading "//" would be read as a protocol-relative URL and change host.
    clean_path = "/" + str(path or "").lstrip("/")
    candidate = urlunsplit(
        (
            base.scheme,
            base.netloc,
            (base.path.rstrip("/") + clean_path) or "/",
            urlencode(params or {}),
            "",
        )
    )
    parsed = urlsplit(candidate)
    if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
        return urlunsplit((base.scheme, base.netloc, base.path or "/", "", ""))
    return candidate


def _oauth_error_redirect(message: str) -> RedirectResponse:
    """Send the SPA back to login with an error query param."""
    redirect = RedirectResponse(
        url=frontend_redirect_url("/login", {"error": message}),
        status_code=status.HTTP_302_FOUND,
    )
    clear_state_cookie(redirect)
    return redirect


def _oauth_success_redirect(token_payload: dict) -> RedirectResponse:
    """Complete OAuth via HttpOnly cookies — never via URL query parameters.

    Tokens in a redirect URL end up in browser history, proxy logs and the
    ``Referer`` header, so only a non-sensitive status flag is passed back.
    """
    redirect = RedirectResponse(
        url=frontend_redirect_url("/oauth/callback", {"status": "success"}),
        status_code=status.HTTP_302_FOUND,
    )
    set_auth_cookies(
        redirect, token_payload["access_token"], token_payload["refresh_token"]
    )
    clear_state_cookie(redirect)
    return redirect


@router.get(
    "/oauth/google",
    summary="Start Google OAuth2 login",
    response_class=RedirectResponse,
)
def google_oauth_redirect():
    """Redirect the browser to Google's OAuth2 consent screen.

    A single-use ``state`` token is minted here and mirrored into an HttpOnly
    cookie so the callback can prove the flow started in this same browser.
    """
    if not _google_oauth_configured():
        return _oauth_error_redirect(
            "Google sign-in is not configured. Please contact your administrator."
        )

    state = generate_state()
    params = urlencode(
        {
            "client_id": settings.OAUTH2_GOOGLE_CLIENT_ID,
            "redirect_uri": settings.OAUTH2_GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
            "state": state,
        }
    )
    redirect = RedirectResponse(
        url=f"{GOOGLE_AUTH_URL}?{params}",
        status_code=status.HTTP_302_FOUND,
    )
    set_state_cookie(redirect, state)
    return redirect


@router.get(
    "/oauth/google/callback",
    summary="Google OAuth2 callback",
    response_class=RedirectResponse,
)
def google_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Exchange the Google auth code, link/create the user, redirect with JWTs."""
    if not _google_oauth_configured():
        return _oauth_error_redirect(
            "Google sign-in is not configured. Please contact your administrator."
        )

    if error:
        return _oauth_error_redirect(error)

    # Anti-CSRF gate: refuse unknown flows before spending the auth code.
    try:
        verify_state(state, state_cookie(request))
    except StateError as exc:
        return _oauth_error_redirect(exc.reason)

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
    "/logout",
    response_model=SessionRevokedResponse,
    summary="Logout current session",
)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke the presented session so its tokens can no longer authenticate.

    The access token's ``jti`` (and the refresh token's, when supplied) is
    recorded in ``revoked_tokens``; legacy tokens without a ``jti`` fall back to
    invalidating every session for the account.
    """
    revoked_access = False
    access_token = _bearer_token(request) or access_cookie(request)
    if access_token:
        try:
            revoked_access = TokenRevocationService.revoke_token(
                db, verify_token(access_token), reason="logout"
            )
        except HTTPException:
            revoked_access = False

    presented_refresh = refresh_cookie(request)
    if presented_refresh:
        try:
            TokenRevocationService.revoke_token(
                db, verify_token(presented_refresh), reason="logout"
            )
        except HTTPException:
            pass

    if not revoked_access:
        # Cannot pin the exact token — drop every outstanding session instead.
        TokenRevocationService.revoke_all_for_user(db, current_user, reason="logout")

    TokenRevocationService.purge_expired(db)
    clear_auth_cookies(response)
    return {"message": "Logged out successfully", "user_id": current_user.id}


@router.post(
    "/logout-all",
    response_model=SessionRevokedResponse,
    summary="Revoke every session for the current user",
)
def logout_all(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invalidate every access and refresh token issued to this account."""
    TokenRevocationService.revoke_all_for_user(db, current_user, reason="logout_all")
    clear_auth_cookies(response)
    return {"message": "All sessions revoked", "user_id": current_user.id}


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
)
def refresh_token(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Issue a new access token using a valid refresh token.

    The token may arrive in the JSON body (API clients) or the HttpOnly cookie
    (SPA). Revoked tokens and tokens predating a password reset are rejected.
    """
    presented = body.refresh_token or refresh_cookie(request)
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
        )

    payload = verify_token(presented)
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

    if TokenRevocationService.is_revoked(db, payload.get("jti")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account deactivated",
        )

    if TokenRevocationService.is_superseded(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid",
        )

    new_token_data = {"sub": str(user.id), "role": user.role.value}
    new_access = create_access_token(data=new_token_data)
    new_refresh = create_refresh_token(data=new_token_data)

    # The access token being replaced must not outlive the rotation, or a
    # later logout would leave it usable until its natural expiry.
    superseded = _bearer_token(request) or access_cookie(request)
    if superseded:
        try:
            TokenRevocationService.revoke_token(
                db, verify_token(superseded), reason="refresh_rotation"
            )
        except HTTPException:
            pass

    set_auth_cookies(response, new_access, new_refresh)

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
