"""
Pydantic schemas for JWT token payloads and responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Token(BaseModel):
    """
    Response schema returned after successful authentication.

    Attributes:
        access_token: Short-lived JWT access token.
        refresh_token: Longer-lived JWT refresh token.
        token_type: Token type indicator (always ``bearer``).
    """

    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class TokenPayload(BaseModel):
    """
    Internal representation of a decoded JWT payload.

    Attributes:
        sub: Subject claim — typically the user ID as a string.
        exp: Expiration timestamp.
        role: User role extracted from the token.
    """

    sub: Optional[str] = Field(None, description="Subject (user ID)")
    exp: Optional[datetime] = Field(None, description="Expiration time")
    role: Optional[str] = Field(None, description="User role")
