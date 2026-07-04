"""
Alarm service: CRUD operations, scheduling, snooze, dismissal.
Works with both PostgreSQL and SQLite.
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models.alarm import Alarm, AlarmEvent
from app.schemas.alarm_schema import (
    AlarmCreate, AlarmUpdate, AlarmResponse, AlarmToggle,
    AlarmEventResponse, AlarmListResponse, AlarmEventListResponse,
)


class AlarmService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _alarm_to_response(self, alarm: Alarm) -> AlarmResponse:
        """Convert ORM alarm to response, parsing JSON fields."""
        days = alarm.days_of_week
        if isinstance(days, str):
            try:
                days = json.loads(days)
            except (json.JSONDecodeError, TypeError):
                days = []
        elif days is None:
            days = []

        return AlarmResponse(
            id=alarm.id,
            user_id=alarm.user_id,
            label=alarm.label,
            alarm_time=alarm.alarm_time,
            alarm_type=alarm.alarm_type,
            is_active=alarm.is_active,
            days_of_week=days,
            challenge_type=alarm.challenge_type,
            challenge_difficulty=alarm.challenge_difficulty,
            snooze_limit=alarm.snooze_limit,
            snooze_interval_minutes=alarm.snooze_interval_minutes,
            sound=alarm.sound,
            vibration=alarm.vibration,
            smart_wakeup_window_minutes=alarm.smart_wakeup_window_minutes,
            one_time_date=alarm.one_time_date,
            created_at=alarm.created_at,
            updated_at=alarm.updated_at,
        )

    async def create_alarm(self, user_id: str, data: AlarmCreate) -> AlarmResponse:
        if data.alarm_type == "one_time" and not data.one_time_date:
            raise HTTPException(status_code=400, detail="one_time alarms require a one_time_date")

        days = data.days_of_week
        if data.alarm_type == "daily":
            days = [0, 1, 2, 3, 4, 5, 6]
        elif data.alarm_type == "weekday":
            days = [0, 1, 2, 3, 4]
        elif data.alarm_type == "weekend":
            days = [5, 6]

        alarm = Alarm(
            user_id=user_id,
            label=data.label,
            alarm_time=data.alarm_time,
            alarm_type=data.alarm_type,
            is_active=True,
            days_of_week=json.dumps(days),
            challenge_type=data.challenge_type,
            challenge_difficulty=data.challenge_difficulty,
            snooze_limit=data.snooze_limit,
            snooze_interval_minutes=data.snooze_interval_minutes,
            sound=data.sound,
            vibration=data.vibration,
            smart_wakeup_window_minutes=data.smart_wakeup_window_minutes,
            one_time_date=data.one_time_date,
        )
        self.db.add(alarm)
        await self.db.commit()
        return self._alarm_to_response(alarm)

    async def get_alarms(self, user_id: str, active_only: bool = False) -> AlarmListResponse:
        query = select(Alarm).where(Alarm.user_id == user_id)
        if active_only:
            query = query.where(Alarm.is_active == True)
        query = query.order_by(Alarm.alarm_time)

        result = await self.db.execute(query)
        alarms = result.scalars().all()

        return AlarmListResponse(
            alarms=[self._alarm_to_response(a) for a in alarms],
            total=len(alarms),
        )

    async def get_alarm(self, alarm_id: str, user_id: str) -> AlarmResponse:
        alarm = await self._get_alarm_or_404(alarm_id, user_id)
        return self._alarm_to_response(alarm)

    async def update_alarm(self, alarm_id: str, user_id: str, data: AlarmUpdate) -> AlarmResponse:
        alarm = await self._get_alarm_or_404(alarm_id, user_id)
        update_data = data.model_dump(exclude_unset=True)

        if "alarm_type" in update_data:
            t = update_data["alarm_type"]
            if t == "daily":
                update_data["days_of_week"] = [0, 1, 2, 3, 4, 5, 6]
            elif t == "weekday":
                update_data["days_of_week"] = [0, 1, 2, 3, 4]
            elif t == "weekend":
                update_data["days_of_week"] = [5, 6]

        for field, value in update_data.items():
            if field == "days_of_week":
                setattr(alarm, field, json.dumps(value))
            else:
                setattr(alarm, field, value)

        await self.db.commit()
        return self._alarm_to_response(alarm)

    async def delete_alarm(self, alarm_id: str, user_id: str) -> Dict[str, str]:
        alarm = await self._get_alarm_or_404(alarm_id, user_id)
        await self.db.delete(alarm)
        await self.db.commit()
        return {"message": "Alarm deleted successfully"}

    async def toggle_alarm(self, alarm_id: str, user_id: str, data: AlarmToggle) -> AlarmResponse:
        alarm = await self._get_alarm_or_404(alarm_id, user_id)
        alarm.is_active = data.is_active
        await self.db.commit()
        return self._alarm_to_response(alarm)

    async def get_upcoming_alarms(self, user_id: str, limit: int = 5) -> List[AlarmResponse]:
        result = await self.db.execute(
            select(Alarm).where(Alarm.user_id == user_id, Alarm.is_active == True)
            .order_by(Alarm.alarm_time).limit(limit)
        )
        alarms = result.scalars().all()
        return [self._alarm_to_response(a) for a in alarms]

    # ─── Alarm Events ───

    async def trigger_alarm(self, alarm_id: str, user_id: str) -> AlarmEventResponse:
        await self._get_alarm_or_404(alarm_id, user_id)
        event = AlarmEvent(
            alarm_id=alarm_id, user_id=user_id,
            triggered_at=datetime.utcnow(), status="triggered",
        )
        self.db.add(event)
        await self.db.commit()
        return AlarmEventResponse.model_validate(event)

    async def snooze_alarm(self, event_id: str, user_id: str) -> Dict[str, Any]:
        result = await self.db.execute(
            select(AlarmEvent).where(AlarmEvent.id == event_id, AlarmEvent.user_id == user_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Alarm event not found")

        alarm_result = await self.db.execute(select(Alarm).where(Alarm.id == event.alarm_id))
        alarm = alarm_result.scalar_one_or_none()

        if event.snooze_count >= alarm.snooze_limit:
            return {
                "action": "force_challenge",
                "message": "Maximum snoozes reached. Solve a challenge to dismiss.",
                "snooze_count": event.snooze_count,
                "remaining_snoozes": 0,
            }

        event.snooze_count += 1
        event.status = "snoozed"
        await self.db.commit()

        levels = ["beginner", "easy", "medium", "hard", "expert"]
        current_idx = levels.index(alarm.challenge_difficulty) if alarm.challenge_difficulty in levels else 2
        escalated_idx = min(current_idx + event.snooze_count, len(levels) - 1)

        return {
            "action": "snoozed",
            "message": f"Alarm snoozed for {alarm.snooze_interval_minutes} minutes",
            "snooze_count": event.snooze_count,
            "remaining_snoozes": alarm.snooze_limit - event.snooze_count,
            "next_challenge_difficulty": levels[escalated_idx],
            "next_trigger": (datetime.utcnow() + timedelta(minutes=alarm.snooze_interval_minutes)).isoformat(),
        }

    async def dismiss_alarm(
        self, event_id: str, user_id: str,
        challenge_completed: bool = False, challenge_id: Optional[str] = None,
        response_time: Optional[float] = None,
    ) -> AlarmEventResponse:
        result = await self.db.execute(
            select(AlarmEvent).where(AlarmEvent.id == event_id, AlarmEvent.user_id == user_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Alarm event not found")

        event.dismissed_at = datetime.utcnow()
        event.challenge_completed = challenge_completed
        event.challenge_id = challenge_id
        event.wake_up_verified = challenge_completed
        event.response_time_seconds = response_time
        event.status = "dismissed"
        await self.db.commit()

        # Deactivate one-time alarms
        alarm_result = await self.db.execute(select(Alarm).where(Alarm.id == event.alarm_id))
        alarm = alarm_result.scalar_one_or_none()
        if alarm and alarm.alarm_type == "one_time":
            alarm.is_active = False
            await self.db.commit()

        return AlarmEventResponse.model_validate(event)

    async def get_alarm_history(self, user_id: str, limit: int = 50, offset: int = 0) -> AlarmEventListResponse:
        count_result = await self.db.execute(
            select(func.count(AlarmEvent.id)).where(AlarmEvent.user_id == user_id)
        )
        total = count_result.scalar() or 0

        result = await self.db.execute(
            select(AlarmEvent).where(AlarmEvent.user_id == user_id)
            .order_by(AlarmEvent.created_at.desc()).offset(offset).limit(limit)
        )
        events = result.scalars().all()

        return AlarmEventListResponse(
            events=[AlarmEventResponse.model_validate(e) for e in events],
            total=total,
        )

    async def _get_alarm_or_404(self, alarm_id: str, user_id: str) -> Alarm:
        result = await self.db.execute(
            select(Alarm).where(Alarm.id == alarm_id, Alarm.user_id == user_id)
        )
        alarm = result.scalar_one_or_none()
        if not alarm:
            raise HTTPException(status_code=404, detail="Alarm not found")
        return alarm
