"""
Authentication API endpoints.

Provides user registration, login, token refresh, and current-user retrieval.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.profile import UserProfile, DifficultyPreference
from app.schemas.user import UserCreate, UserLogin, UserUpdate, UserResponse
from app.schemas.token import Token, TokenPayload
from app.utils.hashing import get_password_hash, verify_password
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
)
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    default_profile = UserProfile(
        user_id=user.id,
        sleep_duration_hours=8.0,
        timezone="UTC",
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

    token_data = {"sub": str(user.id), "role": user.role.value}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
        }
    }


@router.post(
    "/refresh",
    response_model=Token,
    summary="Refresh access token",
)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    """Issue a new access token using a valid refresh token.

    The refresh token is verified to ensure it hasn't expired and
    the associated user account is still active.
    """
    payload = verify_token(refresh_token)
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
