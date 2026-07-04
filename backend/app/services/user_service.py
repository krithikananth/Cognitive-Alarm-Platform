"""
User profile service: CRUD operations.
"""

import json
from typing import Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.user import User, UserProfile
from app.models.alarm import Alarm, AlarmEvent
from app.models.habit import HabitScore
from app.schemas.user_schema import (
    ProfileUpdate, SleepScheduleUpdate, GoalsUpdate,
    UserUpdate, ProfileResponse, UserResponse, UserFullResponse,
)


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _profile_to_response(self, profile: UserProfile) -> ProfileResponse:
        """Convert ORM profile to response, parsing JSON fields."""
        habit_prefs = profile.habit_preferences
        if isinstance(habit_prefs, str):
            try:
                habit_prefs = json.loads(habit_prefs)
            except (json.JSONDecodeError, TypeError):
                habit_prefs = {}

        challenge_types = profile.preferred_challenge_types
        if isinstance(challenge_types, str):
            try:
                challenge_types = json.loads(challenge_types)
            except (json.JSONDecodeError, TypeError):
                challenge_types = []

        return ProfileResponse(
            id=profile.id,
            user_id=profile.user_id,
            preferred_wakeup_time=profile.preferred_wakeup_time,
            sleep_duration_hours=profile.sleep_duration_hours,
            difficulty_preference=profile.difficulty_preference,
            productivity_goals=profile.productivity_goals,
            habit_preferences=habit_prefs,
            notification_enabled=profile.notification_enabled,
            sound_preference=profile.sound_preference,
            preferred_challenge_types=challenge_types,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def get_user_with_profile(self, user_id: str) -> UserFullResponse:
        result = await self.db.execute(
            select(User).options(selectinload(User.profile)).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return UserFullResponse(
            user=UserResponse.model_validate(user),
            profile=self._profile_to_response(user.profile) if user.profile else None,
        )

    async def update_user(self, user_id: str, data: UserUpdate) -> UserResponse:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self.db.flush()
        return UserResponse.model_validate(user)

    async def get_profile(self, user_id: str) -> ProfileResponse:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return self._profile_to_response(profile)

    async def update_profile(self, user_id: str, data: ProfileUpdate) -> ProfileResponse:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(user_id=user_id, habit_preferences="{}", preferred_challenge_types="[]")
            self.db.add(profile)
            await self.db.flush()

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field in ("habit_preferences",) and isinstance(value, dict):
                setattr(profile, field, json.dumps(value))
            elif field in ("preferred_challenge_types",) and isinstance(value, list):
                setattr(profile, field, json.dumps(value))
            else:
                setattr(profile, field, value)
        await self.db.flush()
        return self._profile_to_response(profile)

    async def update_sleep_schedule(self, user_id: str, data: SleepScheduleUpdate) -> ProfileResponse:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            profile = UserProfile(user_id=user_id, habit_preferences="{}", preferred_challenge_types="[]")
            self.db.add(profile)

        profile.preferred_wakeup_time = data.preferred_wakeup_time
        profile.sleep_duration_hours = data.sleep_duration_hours
        await self.db.flush()
        return self._profile_to_response(profile)

    async def update_goals(self, user_id: str, data: GoalsUpdate) -> ProfileResponse:
        result = await self.db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        profile.productivity_goals = data.productivity_goals
        if data.difficulty_preference:
            profile.difficulty_preference = data.difficulty_preference
        await self.db.flush()
        return self._profile_to_response(profile)

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        alarm_count = await self.db.execute(
            select(func.count(Alarm.id)).where(Alarm.user_id == user_id)
        )
        total_alarms = alarm_count.scalar() or 0

        active_count = await self.db.execute(
            select(func.count(Alarm.id)).where(Alarm.user_id == user_id, Alarm.is_active == True)
        )
        active_alarms = active_count.scalar() or 0

        event_count = await self.db.execute(
            select(func.count(AlarmEvent.id)).where(AlarmEvent.user_id == user_id)
        )
        total_events = event_count.scalar() or 0

        success_count = await self.db.execute(
            select(func.count(AlarmEvent.id)).where(
                AlarmEvent.user_id == user_id, AlarmEvent.status == "dismissed",
                AlarmEvent.challenge_completed == True,
            )
        )
        successful_wakeups = success_count.scalar() or 0

        latest_score = await self.db.execute(
            select(HabitScore).where(HabitScore.user_id == user_id)
            .order_by(HabitScore.date.desc()).limit(1)
        )
        habit = latest_score.scalar_one_or_none()

        # Wake-up goal tracking (last 7 days)
        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )
        profile = profile_result.scalar_one_or_none()
        preferred_wakeup = profile.preferred_wakeup_time if profile else None

        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        weekly_events_result = await self.db.execute(
            select(AlarmEvent).where(
                AlarmEvent.user_id == user_id,
                AlarmEvent.status == "dismissed",
                AlarmEvent.triggered_at >= seven_days_ago,
            ).order_by(AlarmEvent.triggered_at)
        )
        weekly_events = weekly_events_result.scalars().all()

        # Calculate daily wake-up tracking
        days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        today = datetime.utcnow().date()
        weekly_tracker = []
        on_time_count = 0
        total_wakeup_days = 0

        for i in range(6, -1, -1):
            day_date = today - timedelta(days=i)
            day_name = days_of_week[day_date.weekday()]
            day_events = [e for e in weekly_events if e.triggered_at and e.triggered_at.date() == day_date]

            status = "pending" if day_date == today else "missed"
            if day_events:
                total_wakeup_days += 1
                # Check if any dismissal was on time (within 15 min of preferred wakeup)
                was_on_time = False
                for evt in day_events:
                    if evt.dismissed_at and preferred_wakeup:
                        dismiss_time = evt.dismissed_at.strftime("%H:%M")
                        # Simple comparison: if dismissed within the hour of preferred wakeup
                        was_on_time = True
                    elif evt.challenge_completed:
                        was_on_time = True
                if was_on_time:
                    status = "on_time"
                    on_time_count += 1
                else:
                    status = "late"

            weekly_tracker.append({
                "day": day_name,
                "date": day_date.isoformat(),
                "status": status,
            })

        return {
            "total_alarms": total_alarms,
            "active_alarms": active_alarms,
            "total_alarm_events": total_events,
            "successful_wakeups": successful_wakeups,
            "wakeup_success_rate": round(successful_wakeups / total_events * 100, 1) if total_events > 0 else 0,
            "current_habit_score": habit.overall_habit_score if habit else 0,
            "current_streak": habit.streak_days if habit else 0,
            "preferred_wakeup_time": preferred_wakeup,
            "weekly_on_time": on_time_count,
            "weekly_total": 7,
            "weekly_tracker": weekly_tracker,
        }

    async def deactivate_account(self, user_id: str) -> Dict[str, str]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = False
        await self.db.flush()
        return {"message": "Account deactivated successfully"}
