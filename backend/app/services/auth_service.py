"""
Authentication service: registration, login, token management, OAuth2.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from fastapi import HTTPException, status

from app.models.user import User, UserProfile
from app.schemas.user_schema import UserRegister, UserLogin, UserResponse
from app.utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    create_password_reset_token, verify_password_reset_token,
)
from app.config import settings


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, data: UserRegister) -> Dict[str, Any]:
        existing = await self.db.execute(
            select(User).where(or_(User.email == data.email, User.username == data.username))
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="A user with this email or username already exists")

        user = User(
            email=data.email, username=data.username,
            hashed_password=hash_password(data.password),
            full_name=data.full_name, timezone=data.timezone or "UTC",
            role="user", is_active=True, is_verified=False,
        )
        self.db.add(user)
        await self.db.flush()

        profile = UserProfile(
            user_id=user.id, difficulty_preference="medium",
            sleep_duration_hours=8.0, notification_enabled=True,
            sound_preference="default",
            preferred_challenge_types=json.dumps(["math", "logic"]),
            habit_preferences="{}",
        )
        self.db.add(profile)
        await self.db.flush()

        token_data = {"sub": str(user.id), "role": user.role}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": UserResponse.model_validate(user),
        }

    async def login(self, data: UserLogin) -> Dict[str, Any]:
        result = await self.db.execute(select(User).where(User.email == data.email))
        user = result.scalar_one_or_none()

        if not user or not user.hashed_password:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not verify_password(data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account is deactivated")

        token_data = {"sub": str(user.id), "role": user.role}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": UserResponse.model_validate(user),
        }

    async def refresh_token(self, refresh_token_str: str) -> Dict[str, Any]:
        payload = decode_token(refresh_token_str)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=400, detail="Invalid token type")

        user_id = payload.get("sub")
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        token_data = {"sub": str(user.id), "role": user.role}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": UserResponse.model_validate(user),
        }

    async def oauth_login_or_register(
        self, provider: str, oauth_id: str, email: str,
        full_name: Optional[str] = None, avatar_url: Optional[str] = None
    ) -> Dict[str, Any]:
        result = await self.db.execute(
            select(User).where(User.oauth_provider == provider, User.oauth_id == oauth_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            result = await self.db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user:
                user.oauth_provider = provider
                user.oauth_id = oauth_id
                if avatar_url:
                    user.avatar_url = avatar_url
            else:
                username = email.split("@")[0]
                base_username = username
                counter = 1
                while True:
                    existing = await self.db.execute(select(User).where(User.username == username))
                    if not existing.scalar_one_or_none():
                        break
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User(
                    email=email, username=username, full_name=full_name,
                    oauth_provider=provider, oauth_id=oauth_id,
                    avatar_url=avatar_url, is_verified=True, role="user",
                )
                self.db.add(user)
                await self.db.flush()

                profile = UserProfile(
                    user_id=user.id, difficulty_preference="medium",
                    sleep_duration_hours=8.0,
                    preferred_challenge_types=json.dumps(["math", "logic"]),
                    habit_preferences="{}",
                )
                self.db.add(profile)
                await self.db.flush()

        token_data = {"sub": str(user.id), "role": user.role}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": UserResponse.model_validate(user),
        }

    async def request_password_reset(self, email: str) -> Dict[str, str]:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            return {"message": "If an account exists with this email, a reset link will be sent."}
        reset_token = create_password_reset_token(email)
        return {"message": "Password reset token generated", "reset_token": reset_token}

    async def reset_password(self, token: str, new_password: str) -> Dict[str, str]:
        email = verify_password_reset_token(token)
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.hashed_password = hash_password(new_password)
        return {"message": "Password reset successfully"}
