"""
Pydantic schemas for password reset and email verification flows.
"""

import re
from typing import Any, Dict, List

from pydantic import BaseModel, EmailStr, Field, field_validator


class MessageResponse(BaseModel):
    """Generic success/ack payload for auth utility endpoints."""

    message: str = Field(..., description="Human-readable status message")


class ForgotPasswordRequest(BaseModel):
    """Request a password-reset email for the given address."""

    email: EmailStr = Field(..., description="Account email address")


class ResetPasswordRequest(BaseModel):
    """Complete a password reset using a one-time JWT."""

    token: str = Field(..., min_length=1, description="Password-reset JWT")
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="New strong password"
    )

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Enforce the same password complexity rules as registration."""
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


class VerifyEmailRequest(BaseModel):
    """Confirm an email address using a one-time JWT."""

    token: str = Field(..., min_length=1, description="Email-verification JWT")


class ResendVerificationRequest(BaseModel):
    """Request another email-verification message."""

    email: EmailStr = Field(..., description="Account email address")


class LoginResponse(BaseModel):
    """Token pair plus the signed-in account summary.

    The SPA authenticates by HttpOnly cookie; the tokens are also returned in
    the body for API and native clients.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: Dict[str, Any] = Field(default_factory=dict)


class SessionRevokedResponse(BaseModel):
    """Acknowledgement for logout and logout-all."""

    message: str
    user_id: int
