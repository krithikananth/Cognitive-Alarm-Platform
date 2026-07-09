"""
Alarm scheduling service layer.

Encapsulates alarm creation, retrieval, update, deletion, and trigger
calculation logic, keeping endpoint handlers thin and testable.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.alarm import Alarm, AlarmType, ChallengeType
from app.schemas.alarm import AlarmCreate, AlarmUpdate


class AlarmService:
    """Service class for alarm scheduling operations."""

    @staticmethod
    def create_alarm(db: Session, user_id: int, data: AlarmCreate) -> Alarm:
        """Create a new alarm for the specified user.

        Provisions the alarm, calculates the initial next-trigger datetime,
        and persists to the database.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            data: Validated alarm creation payload.

        Returns:
            The newly created ``Alarm`` instance.
        """
        alarm = Alarm(
            user_id=user_id,
            title=data.title,
            description=data.description,
            alarm_time=data.alarm_time,
            alarm_type=data.alarm_type,
            days_of_week=data.days_of_week,
            snooze_limit=data.snooze_limit,
            snooze_interval_minutes=data.snooze_interval_minutes,
            challenge_type=data.challenge_type,
            challenge_count=data.challenge_count,
            volume=data.volume,
            vibrate=data.vibrate,
            label=data.label,
            is_active=True,
        )
        alarm.next_trigger_at = AlarmService.calculate_next_trigger(alarm)

        db.add(alarm)
        db.commit()
        db.refresh(alarm)
        return alarm

    @staticmethod
    def get_alarms(
        db: Session,
        user_id: int,
        page: int = 1,
        per_page: int = 20,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[Alarm], int]:
        """Retrieve a paginated list of alarms for a user.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            page: Page number (1-indexed).
            per_page: Number of items per page.
            is_active: Optional filter for active/inactive alarms.

        Returns:
            Tuple of (alarm list, total count).
        """
        query = db.query(Alarm).filter(Alarm.user_id == user_id)

        if is_active is not None:
            query = query.filter(Alarm.is_active == is_active)

        total = query.count()
        alarms = (
            query.order_by(Alarm.alarm_time)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return alarms, total

    @staticmethod
    def get_alarm(db: Session, alarm_id: int, user_id: int) -> Alarm:
        """Retrieve a single alarm by ID, scoped to the user.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.

        Returns:
            The ``Alarm`` instance.

        Raises:
            HTTPException: 404 if not found or not owned by user.
        """
        alarm = (
            db.query(Alarm)
            .filter(Alarm.id == alarm_id, Alarm.user_id == user_id)
            .first()
        )
        if not alarm:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alarm not found",
            )
        return alarm

    @staticmethod
    def update_alarm(
        db: Session, alarm_id: int, user_id: int, data: AlarmUpdate
    ) -> Alarm:
        """Update an existing alarm.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.
            data: Validated update payload.

        Returns:
            The updated ``Alarm`` instance.

        Raises:
            HTTPException: 404 if not found.
        """
        alarm = AlarmService.get_alarm(db, alarm_id, user_id)
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(alarm, field, value)

        if "alarm_time" in update_data or "alarm_type" in update_data:
            alarm.next_trigger_at = AlarmService.calculate_next_trigger(alarm)

        db.commit()
        db.refresh(alarm)
        return alarm

    @staticmethod
    def delete_alarm(db: Session, alarm_id: int, user_id: int) -> bool:
        """Delete an alarm.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.

        Returns:
            True on successful deletion.

        Raises:
            HTTPException: 404 if not found.
        """
        alarm = AlarmService.get_alarm(db, alarm_id, user_id)
        db.delete(alarm)
        db.commit()
        return True

    @staticmethod
    def toggle_alarm(
        db: Session, alarm_id: int, user_id: int, is_active: bool
    ) -> Alarm:
        """Toggle an alarm's active state.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.
            is_active: Desired active state.

        Returns:
            The updated ``Alarm`` instance.
        """
        alarm = AlarmService.get_alarm(db, alarm_id, user_id)
        alarm.is_active = is_active

        if is_active:
            alarm.next_trigger_at = AlarmService.calculate_next_trigger(alarm)

        db.commit()
        db.refresh(alarm)
        return alarm

    @staticmethod
    def get_upcoming_alarms(
        db: Session, user_id: int, hours_ahead: int = 24
    ) -> List[Alarm]:
        """Retrieve upcoming active alarms within a time window.

        Args:
            db: Active database session.
            user_id: Owning user's primary key.
            hours_ahead: Number of hours to look ahead.

        Returns:
            List of upcoming alarms sorted by trigger time.
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)

        return (
            db.query(Alarm)
            .filter(
                Alarm.user_id == user_id,
                Alarm.is_active == True,
                Alarm.next_trigger_at != None,
                Alarm.next_trigger_at >= now,
                Alarm.next_trigger_at <= cutoff,
            )
            .order_by(Alarm.next_trigger_at)
            .all()
        )

    @staticmethod
    def snooze_alarm(db: Session, alarm_id: int, user_id: int) -> Alarm:
        """Snooze an alarm.

        Increments the snooze counter and postpones the trigger time by
        the configured snooze interval.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.

        Returns:
            The updated ``Alarm`` instance.

        Raises:
            HTTPException: 400 if snooze limit reached.
        """
        alarm = AlarmService.get_alarm(db, alarm_id, user_id)

        if alarm.total_snoozes >= alarm.snooze_limit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum snooze limit reached",
            )

        alarm.total_snoozes += 1
        alarm.next_trigger_at = datetime.now(timezone.utc) + timedelta(
            minutes=alarm.snooze_interval_minutes
        )

        db.commit()
        db.refresh(alarm)
        return alarm

    @staticmethod
    def dismiss_alarm(db: Session, alarm_id: int, user_id: int) -> Alarm:
        """Dismiss an alarm after cognitive challenge completion.

        Records the dismissal, updates the last-triggered timestamp, and
        calculates the next trigger time.

        Args:
            db: Active database session.
            alarm_id: Alarm primary key.
            user_id: Owning user's primary key.

        Returns:
            The updated ``Alarm`` instance.
        """
        alarm = AlarmService.get_alarm(db, alarm_id, user_id)

        alarm.total_dismissals += 1
        alarm.last_triggered_at = datetime.now(timezone.utc)
        alarm.next_trigger_at = AlarmService.calculate_next_trigger(alarm)

        db.commit()
        db.refresh(alarm)
        return alarm

    @staticmethod
    def calculate_next_trigger(alarm: Alarm) -> Optional[datetime]:
        """Calculate the next trigger datetime for an alarm.

        Takes into account the alarm type and configured days of the week.

        Args:
            alarm: The alarm instance.

        Returns:
            Next trigger datetime in UTC, or None for expired one-time alarms.
        """
        now = datetime.now(timezone.utc)
        today = now.date()
        alarm_dt = datetime.combine(today, alarm.alarm_time, tzinfo=timezone.utc)

        if alarm.alarm_type == AlarmType.ONE_TIME:
            return alarm_dt if alarm_dt > now else alarm_dt + timedelta(days=1)

        if alarm.alarm_type == AlarmType.DAILY:
            return alarm_dt if alarm_dt > now else alarm_dt + timedelta(days=1)

        if alarm.alarm_type == AlarmType.WEEKDAY:
            for offset in range(7):
                candidate = alarm_dt + timedelta(days=offset)
                if candidate > now and candidate.weekday() < 5:
                    return candidate

        if alarm.alarm_type == AlarmType.WEEKEND:
            for offset in range(7):
                candidate = alarm_dt + timedelta(days=offset)
                if candidate > now and candidate.weekday() >= 5:
                    return candidate

        if alarm.alarm_type == AlarmType.SMART_ADAPTIVE:
            return alarm_dt if alarm_dt > now else alarm_dt + timedelta(days=1)

        return alarm_dt + timedelta(days=1)
