"""
Alarm management API endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.alarm_service import AlarmService
from app.schemas.alarm_schema import (
    AlarmCreate, AlarmUpdate, AlarmResponse, AlarmToggle,
    AlarmListResponse, AlarmEventListResponse, AlarmEventResponse,
)
from app.middleware.auth_middleware import get_current_user
from app.models.user import User


router = APIRouter(prefix="/alarms", tags=["Alarms"])


# ═══════════════════════════════════════════
# Alarm CRUD
# ═══════════════════════════════════════════

@router.post("", response_model=AlarmResponse, status_code=201)
async def create_alarm(
    data: AlarmCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new alarm."""
    service = AlarmService(db)
    return await service.create_alarm(current_user.id, data)


@router.get("", response_model=AlarmListResponse)
async def list_alarms(
    active_only: bool = Query(False, description="Filter to active alarms only"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all alarms for the current user."""
    service = AlarmService(db)
    return await service.get_alarms(current_user.id, active_only=active_only)


@router.get("/upcoming")
async def get_upcoming_alarms(
    limit: int = Query(5, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the next upcoming active alarms."""
    service = AlarmService(db)
    return await service.get_upcoming_alarms(current_user.id, limit=limit)


@router.get("/history", response_model=AlarmEventListResponse)
async def get_alarm_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get alarm event history."""
    service = AlarmService(db)
    return await service.get_alarm_history(current_user.id, limit=limit, offset=offset)


@router.get("/{alarm_id}", response_model=AlarmResponse)
async def get_alarm(
    alarm_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific alarm by ID."""
    service = AlarmService(db)
    return await service.get_alarm(alarm_id, current_user.id)


@router.put("/{alarm_id}", response_model=AlarmResponse)
async def update_alarm(
    alarm_id: str,
    data: AlarmUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing alarm."""
    service = AlarmService(db)
    return await service.update_alarm(alarm_id, current_user.id, data)


@router.delete("/{alarm_id}")
async def delete_alarm(
    alarm_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an alarm."""
    service = AlarmService(db)
    return await service.delete_alarm(alarm_id, current_user.id)


@router.patch("/{alarm_id}/toggle", response_model=AlarmResponse)
async def toggle_alarm(
    alarm_id: str,
    data: AlarmToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable an alarm."""
    service = AlarmService(db)
    return await service.toggle_alarm(alarm_id, current_user.id, data)


# ═══════════════════════════════════════════
# Alarm Events (Trigger / Snooze / Dismiss)
# ═══════════════════════════════════════════

@router.post("/{alarm_id}/trigger", response_model=AlarmEventResponse)
async def trigger_alarm(
    alarm_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record an alarm trigger event."""
    service = AlarmService(db)
    return await service.trigger_alarm(alarm_id, current_user.id)


@router.post("/events/{event_id}/snooze")
async def snooze_alarm(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snooze an alarm (with anti-snooze limits)."""
    service = AlarmService(db)
    return await service.snooze_alarm(event_id, current_user.id)


@router.post("/events/{event_id}/dismiss", response_model=AlarmEventResponse)
async def dismiss_alarm(
    event_id: str,
    challenge_completed: bool = False,
    challenge_id: Optional[str] = None,
    response_time: Optional[float] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss an alarm after challenge completion."""
    service = AlarmService(db)
    return await service.dismiss_alarm(
        event_id, current_user.id,
        challenge_completed=challenge_completed,
        challenge_id=challenge_id,
        response_time=response_time,
    )
