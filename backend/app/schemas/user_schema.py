"""
User and Auth Pydantic schemas for request/response validation.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ═══════════════════════════════════════════
# Auth Schemas
# ═══════════════════════════════════════════

class UserRegister(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = None
    timezone: Optional[str] = "UTC"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"


class TokenRefresh(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordReset(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ═══════════════════════════════════════════
# User Schemas
# ═══════════════════════════════════════════

class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    oauth_provider: Optional[str] = None
    avatar_url: Optional[str] = None
    timezone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
    timezone: Optional[str] = None
    avatar_url: Optional[str] = None


class UserRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(user|wellness_coach|admin)$")


# ═══════════════════════════════════════════
# Profile Schemas
# ═══════════════════════════════════════════

class ProfileResponse(BaseModel):
    id: str
    user_id: str
    preferred_wakeup_time: Optional[str] = None
    sleep_duration_hours: float
    difficulty_preference: str
    productivity_goals: Optional[str] = None
    habit_preferences: Any = {}
    notification_enabled: bool
    sound_preference: str
    preferred_challenge_types: Any = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    preferred_wakeup_time: Optional[str] = None
    sleep_duration_hours: Optional[float] = Field(None, ge=3.0, le=14.0)
    difficulty_preference: Optional[str] = Field(None, pattern="^(beginner|easy|medium|hard|expert)$")
    productivity_goals: Optional[str] = None
    habit_preferences: Optional[Dict[str, Any]] = None
    notification_enabled: Optional[bool] = None
    sound_preference: Optional[str] = None
    preferred_challenge_types: Optional[List[str]] = None


class SleepScheduleUpdate(BaseModel):
    preferred_wakeup_time: str  # "HH:MM"
    sleep_duration_hours: float = Field(..., ge=3.0, le=14.0)


class GoalsUpdate(BaseModel):
    productivity_goals: str
    difficulty_preference: Optional[str] = Field(None, pattern="^(beginner|easy|medium|hard|expert)$")


# ═══════════════════════════════════════════
# Full User + Profile Response
# ═══════════════════════════════════════════

class UserFullResponse(BaseModel):
    user: UserResponse
    profile: Optional[ProfileResponse] = None


TokenResponse.model_rebuild()
