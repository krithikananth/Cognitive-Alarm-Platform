"""
Pydantic schemas for User CRUD operations.

Includes strict validation for email, password strength, and username format.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole
from app.schemas.common import AggregateResponse


class UserCreate(BaseModel):
    """
    Schema for new user registration.

    Attributes:
        email: Valid email address.
        username: 3+ characters, alphanumeric and underscores only.
        password: Minimum 8 characters with uppercase, lowercase, and digit.
        full_name: Optional display name.
    """

    email: EmailStr = Field(..., description="Valid email address")
    username: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="Username (alphanumeric + underscore, 3-100 chars)",
    )
    password: str = Field(
        ..., min_length=8, max_length=128, description="Strong password"
    )
    full_name: Optional[str] = Field(
        None, max_length=255, description="Full display name"
    )
    timezone: Optional[str] = Field(
        default=None,
        max_length=50,
        description="IANA timezone (defaults to UTC)",
    )

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Ensure username contains only alphanumerics and underscores."""
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username must contain only letters, digits, and underscores"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            ZoneInfo(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Unknown timezone: {v}") from exc
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce password complexity requirements."""
        errors: List[str] = []
        if not re.search(r"[A-Z]", v):
            errors.append("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("Password must contain at least one digit")
        if errors:
            raise ValueError("; ".join(errors))
        return v


class UserLogin(BaseModel):
    """
    Schema for email + password login.

    Attributes:
        email: The user's email address.
        password: The user's plain-text password.
    """

    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Plain-text password")


class UserUpdate(BaseModel):
    """
    Schema for updating the currently authenticated user's details.

    All fields are optional; only supplied fields are updated.

    Attributes:
        full_name: New display name.
        email: New email address.
    """

    full_name: Optional[str] = Field(
        None, max_length=255, description="Updated full name"
    )
    email: Optional[EmailStr] = Field(
        None, description="Updated email address"
    )


class AdminUserUpdate(BaseModel):
    """
    Schema for admin updates to any user account.

    Unlike ``UserUpdate`` (used for self-service updates), this schema also
    allows an admin to change a user's ``role`` and ``is_active`` state. It is
    only accepted by admin-guarded endpoints, so regular users cannot use it to
    escalate their own privileges.
    """

    full_name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """
    Public-facing user representation returned by the API.

    Attributes:
        id: User primary key.
        email: Email address.
        username: Username.
        full_name: Display name.
        role: User role.
        is_active: Whether the account is active.
        is_verified: Whether the email has been verified.
        created_at: Account creation timestamp.
    """

    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """
    Paginated list of users.

    Attributes:
        users: List of user records for the current page.
        total: Total number of users matching the query.
        page: Current page number (1-indexed).
        per_page: Number of records per page.
    """

    users: List[UserResponse]
    total: int
    page: int
    per_page: int


class UserProfileBundleResponse(AggregateResponse):
    """Account + profile bundle used by the Profile page.

    Returned by ``GET/PUT /users/profile`` and the sleep-schedule and goals
    updates, which all render the same view.
    """

    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    timezone: Optional[str] = None
    is_active: bool
    profile: Dict[str, Any] = Field(default_factory=dict)


class UserStatsResponse(AggregateResponse):
    """GET /users/profile/stats — headline figures for the profile header."""

    active_alarms: int
    current_habit_score: float
    current_streak: int
    success_streak: int
    failure_streak: int
    wakeup_success_rate: float
    preferred_wakeup_time: Optional[str] = None
    weekly_on_time: int
    weekly_total: int
    weekly_tracker: List[Dict[str, Any]] = Field(default_factory=list)
    last_successful_wake_date: Optional[str] = None
    best_streak: Optional[int] = None


class UserPreferencesResponse(AggregateResponse):
    """GET/PUT /users/profile/preferences."""

    preferred_challenge_types: List[str] = Field(default_factory=list)
    difficulty_preference: str
    productivity_goals: List[str] = Field(default_factory=list)
    habit_preferences: Dict[str, Any] = Field(default_factory=dict)
