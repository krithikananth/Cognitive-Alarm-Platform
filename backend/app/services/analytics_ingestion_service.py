"""
Analytics Data Ingestion layer.

Stores generic product/behavioral events in ``analytics_events`` without
replacing domain audit tables (challenge logs, snooze events, wake events).

Server-side emitters call ``emit`` / convenience helpers from existing write
paths. Clients can also POST events via the dedicated ingestion API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analytics_event import AnalyticsEvent

logger = logging.getLogger(__name__)


class AnalyticsEventType:
    """Canonical event type strings used by server emitters."""

    ALARM_CREATED = "alarm.created"
    ALARM_UPDATED = "alarm.updated"
    ALARM_DELETED = "alarm.deleted"
    ALARM_TOGGLED = "alarm.toggled"
    ALARM_TRIGGERED = "alarm.triggered"
    ALARM_SNOOZED = "alarm.snoozed"
    ALARM_SNOOZE_BLOCKED = "alarm.snooze_blocked"
    ALARM_DISMISSED = "alarm.dismissed"
    ALARM_ABANDONED = "alarm.abandoned"
    CHALLENGE_ISSUED = "challenge.issued"
    CHALLENGE_ATTEMPTED = "challenge.attempted"
    WAKE_VERIFIED = "wake.verified"
    PROFILE_UPDATED = "profile.updated"
    RECOMMENDATION_VIEWED = "recommendation.viewed"
    RECOMMENDATION_ACTED = "recommendation.acted"


# Allow client ingestion of product events that the server does not emit yet.
ALLOWED_CLIENT_EVENT_PREFIXES = (
    "alarm.",
    "challenge.",
    "wake.",
    "profile.",
    "habit.",
    "recommendation.",
    "ui.",
    "session.",
)

MAX_EVENT_DATA_KEYS = 64
MAX_EVENT_DATA_DEPTH = 4


class AnalyticsIngestionService:
    """Write/read API for the analytics_events store."""

    # ── Normalization ──────────────────────────────────────────────

    @staticmethod
    def normalize_event_type(raw: Optional[str]) -> str:
        value = (raw or "").strip().lower().replace(" ", "_")
        if not value:
            raise ValueError("event_type is required")
        if len(value) > 100:
            raise ValueError("event_type must be at most 100 characters")
        return value

    @staticmethod
    def normalize_source(raw: Optional[str]) -> str:
        value = (raw or "server").strip().lower()
        if value not in {"server", "client", "system"}:
            return "server"
        return value

    @staticmethod
    def sanitize_event_data(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Keep payloads JSON-safe and bounded for future analytics pipelines."""
        if not data:
            return {}
        if not isinstance(data, dict):
            return {"_value": str(data)}

        def _clean(obj: Any, depth: int) -> Any:
            if depth > MAX_EVENT_DATA_DEPTH:
                return None
            if obj is None or isinstance(obj, (bool, int, float, str)):
                return obj
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, dict):
                out: Dict[str, Any] = {}
                for i, (k, v) in enumerate(obj.items()):
                    if i >= MAX_EVENT_DATA_KEYS:
                        break
                    cleaned = _clean(v, depth + 1)
                    if cleaned is not None or v is None:
                        out[str(k)[:64]] = cleaned
                return out
            if isinstance(obj, (list, tuple)):
                return [_clean(v, depth + 1) for v in list(obj)[:50]]
            return str(obj)

        return _clean(data, 0) or {}

    @staticmethod
    def is_allowed_client_event(event_type: str) -> bool:
        return any(
            event_type.startswith(prefix) for prefix in ALLOWED_CLIENT_EVENT_PREFIXES
        )

    # ── Write paths ────────────────────────────────────────────────

    @staticmethod
    def emit(
        db: Session,
        *,
        user_id: int,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        source: str = "server",
        occurred_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> AnalyticsEvent:
        """Persist one analytics event.

        When ``commit=False``, the row is flushed into the caller's transaction
        so domain logging and analytics stay atomic.
        """
        now = datetime.now(timezone.utc)
        created = occurred_at or now
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        row = AnalyticsEvent(
            user_id=user_id,
            event_type=AnalyticsIngestionService.normalize_event_type(event_type),
            entity_type=(entity_type or "").strip().lower() or None,
            entity_id=entity_id,
            source=AnalyticsIngestionService.normalize_source(source),
            event_data=AnalyticsIngestionService.sanitize_event_data(event_data),
            created_at=created,
        )
        db.add(row)
        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row

    @staticmethod
    def emit_safe(
        db: Session,
        *,
        user_id: int,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        source: str = "server",
        occurred_at: Optional[datetime] = None,
        commit: bool = False,
    ) -> Optional[AnalyticsEvent]:
        """Best-effort emit that never fails the caller's primary transaction.

        Uses a nested SAVEPOINT so a bad analytics write can roll back without
        aborting domain commits (attempt logs, snooze, dismiss).
        """
        try:
            with db.begin_nested():
                return AnalyticsIngestionService.emit(
                    db,
                    user_id=user_id,
                    event_type=event_type,
                    event_data=event_data,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    source=source,
                    occurred_at=occurred_at,
                    commit=False,
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Analytics emit skipped for user=%s type=%s: %s",
                user_id,
                event_type,
                exc,
            )
            return None
        finally:
            # Outer caller still owns commit when commit=False (default).
            if commit:
                try:
                    db.commit()
                except Exception as exc:  # pragma: no cover
                    logger.warning("Analytics commit failed: %s", exc)
                    db.rollback()

    @staticmethod
    def ingest_many(
        db: Session,
        *,
        user_id: int,
        events: Sequence[Dict[str, Any]],
        source: str = "client",
        commit: bool = True,
    ) -> List[AnalyticsEvent]:
        """Ingest a batch of client/server events; rejects disallowed types."""
        stored: List[AnalyticsEvent] = []
        for raw in events:
            event_type = AnalyticsIngestionService.normalize_event_type(
                raw.get("event_type")
            )
            if source == "client" and not AnalyticsIngestionService.is_allowed_client_event(
                event_type
            ):
                raise ValueError(f"Unsupported client event_type: {event_type}")

            stored.append(
                AnalyticsIngestionService.emit(
                    db,
                    user_id=user_id,
                    event_type=event_type,
                    event_data=raw.get("event_data") or {},
                    entity_type=raw.get("entity_type"),
                    entity_id=raw.get("entity_id"),
                    source=source,
                    occurred_at=raw.get("occurred_at"),
                    commit=False,
                )
            )

        if commit:
            db.commit()
            for row in stored:
                db.refresh(row)
        else:
            db.flush()
        return stored

    # ── Convenience emitters (domain side-effects) ─────────────────

    @staticmethod
    def emit_challenge_attempted(
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        challenge_log_id: Optional[int],
        challenge_type: str,
        difficulty: str,
        is_correct: bool,
        time_taken_seconds: int,
        points_earned: int,
        commit: bool = False,
    ) -> Optional[AnalyticsEvent]:
        return AnalyticsIngestionService.emit_safe(
            db,
            user_id=user_id,
            event_type=AnalyticsEventType.CHALLENGE_ATTEMPTED,
            entity_type="alarm",
            entity_id=alarm_id,
            event_data={
                "challenge_log_id": challenge_log_id,
                "challenge_type": challenge_type,
                "difficulty": difficulty,
                "is_correct": is_correct,
                "time_taken_seconds": time_taken_seconds,
                "points_earned": points_earned,
            },
            source="server",
            commit=commit,
        )

    @staticmethod
    def emit_alarm_snoozed(
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        snooze_event_id: Optional[int],
        snooze_number: int,
        snooze_limit: int,
        next_trigger_at: Optional[datetime],
        commit: bool = False,
    ) -> Optional[AnalyticsEvent]:
        return AnalyticsIngestionService.emit_safe(
            db,
            user_id=user_id,
            event_type=AnalyticsEventType.ALARM_SNOOZED,
            entity_type="alarm",
            entity_id=alarm_id,
            event_data={
                "snooze_event_id": snooze_event_id,
                "snooze_number": snooze_number,
                "snooze_limit": snooze_limit,
                "next_trigger_at": (
                    next_trigger_at.isoformat() if next_trigger_at else None
                ),
            },
            source="server",
            commit=commit,
        )

    @staticmethod
    def emit_alarm_dismissed(
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        wake_event_id: Optional[int],
        dismiss_method: str,
        snooze_count: int,
        wakefulness_score: Optional[float],
        wakefulness_level: Optional[str],
        time_to_dismiss_seconds: Optional[int],
        commit: bool = False,
    ) -> Optional[AnalyticsEvent]:
        return AnalyticsIngestionService.emit_safe(
            db,
            user_id=user_id,
            event_type=AnalyticsEventType.ALARM_DISMISSED,
            entity_type="alarm",
            entity_id=alarm_id,
            event_data={
                "wake_event_id": wake_event_id,
                "dismiss_method": dismiss_method,
                "snooze_count": snooze_count,
                "wakefulness_score": wakefulness_score,
                "wakefulness_level": wakefulness_level,
                "time_to_dismiss_seconds": time_to_dismiss_seconds,
            },
            source="server",
            commit=commit,
        )

    @staticmethod
    def emit_alarm_abandoned(
        db: Session,
        *,
        user_id: int,
        alarm_id: int,
        wake_event_id: Optional[int],
        dismiss_method: str,
        snooze_count: int,
        consecutive_correct: int,
        challenges_required: int,
        failed_attempts: int,
        time_to_fail_seconds: Optional[int],
        commit: bool = False,
    ) -> Optional[AnalyticsEvent]:
        """Emit a final failed-wake analytics event (not mid-cycle wrong)."""
        return AnalyticsIngestionService.emit_safe(
            db,
            user_id=user_id,
            event_type=AnalyticsEventType.ALARM_ABANDONED,
            entity_type="alarm",
            entity_id=alarm_id,
            event_data={
                "wake_event_id": wake_event_id,
                "dismiss_method": dismiss_method,
                "snooze_count": snooze_count,
                "consecutive_correct": consecutive_correct,
                "challenges_required": challenges_required,
                "failed_attempts": failed_attempts,
                "time_to_fail_seconds": time_to_fail_seconds,
                "verified": False,
            },
            source="server",
            commit=commit,
        )

    # ── Read paths ─────────────────────────────────────────────────

    @staticmethod
    def list_events(
        db: Session,
        *,
        user_id: int,
        event_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Dict[str, Any]:
        q = db.query(AnalyticsEvent).filter(AnalyticsEvent.user_id == user_id)
        if event_type:
            q = q.filter(
                AnalyticsEvent.event_type
                == AnalyticsIngestionService.normalize_event_type(event_type)
            )
        if entity_type:
            q = q.filter(AnalyticsEvent.entity_type == entity_type.strip().lower())
        if entity_id is not None:
            q = q.filter(AnalyticsEvent.entity_id == entity_id)

        total = q.count()
        rows = (
            q.order_by(AnalyticsEvent.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "events": rows,
        }

    @staticmethod
    def summarize(
        db: Session,
        *,
        user_id: int,
    ) -> Dict[str, Any]:
        rows = (
            db.query(AnalyticsEvent.event_type, func.count(AnalyticsEvent.id))
            .filter(AnalyticsEvent.user_id == user_id)
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count(AnalyticsEvent.id).desc())
            .all()
        )
        by_type = [{"event_type": t, "count": c} for t, c in rows]
        return {
            "total_events": sum(item["count"] for item in by_type),
            "by_event_type": by_type,
        }
