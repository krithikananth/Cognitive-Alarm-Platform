"""
Generic analytics event store for product / behavioral telemetry.

Domain tables (challenge logs, snooze events, wake events) remain the
source of truth for adaptive difficulty and habit scoring. This table is
an additive ingestion layer for future analytics features.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base


class AnalyticsEvent(Base):
    """One row per analytics event (server-emitted or client-ingested)."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_user_created", "user_id", "created_at"),
        Index("ix_analytics_event_type", "event_type"),
        Index("ix_analytics_event_type_created", "event_type", "created_at"),
        Index("ix_analytics_entity", "entity_type", "entity_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Dotted event name, e.g. "challenge.attempted", "alarm.snoozed"
    event_type = Column(String(100), nullable=False, index=True)

    # Optional entity pointer for joins / filtering
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)

    # Where the event originated: server | client | system
    source = Column(String(20), nullable=False, default="server")

    # Flexible payload for future analytics features
    event_data = Column(JSON, nullable=False, default=dict)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    user = relationship("User", backref="analytics_events")
