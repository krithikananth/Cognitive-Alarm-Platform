"""
Coach-to-client assignment ORM model.

Defines the ``coach_assignments`` table, the link that scopes a wellness
coach's visibility to an explicit roster of clients.  Without a row here a
coach can see nothing about a user, which is what keeps the coach APIs from
becoming a cross-tenant data leak.

Assignments are created by admins.  Deactivating (``is_active = False``)
rather than deleting preserves the coaching history while immediately
revoking access.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class CoachAssignment(Base):
    """
    SQLAlchemy model linking a wellness coach to an assigned client.

    Attributes:
        id: Auto-incrementing primary key.
        coach_id: FK to the ``users`` row holding the ``wellness_coach`` role.
        client_id: FK to the ``users`` row being coached.
        assigned_by_user_id: Admin who created the assignment (audit pointer).
        is_active: Whether the assignment currently grants access.
        notes: Optional free-text coaching context.
        created_at: Timestamp of record creation (UTC).
        updated_at: Timestamp of last update (UTC).
    """

    __tablename__ = "coach_assignments"

    id = Column(Integer, primary_key=True, index=True)
    coach_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    notes = Column(String(500), nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # One row per coach/client pair — re-assigning flips is_active instead
        # of inserting a duplicate.
        UniqueConstraint("coach_id", "client_id", name="uq_coach_assignment_pair"),
        Index("ix_coach_assignments_coach_active", "coach_id", "is_active"),
        Index("ix_coach_assignments_client_active", "client_id", "is_active"),
    )

    # ── Relationships ─────────────────────────────────────────────────
    # Both point at ``users``, so foreign_keys is required to disambiguate.
    # Deliberately one-directional: no backref is added to ``User`` so that
    # importing the User model never depends on this module being loaded.
    coach = relationship("User", foreign_keys=[coach_id])
    client = relationship("User", foreign_keys=[client_id])

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return (
            f"<CoachAssignment(coach_id={self.coach_id}, "
            f"client_id={self.client_id}, is_active={self.is_active})>"
        )
