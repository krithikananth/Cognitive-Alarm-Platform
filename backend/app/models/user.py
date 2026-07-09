"""
User ORM model.

Defines the ``users`` table with authentication fields, role-based access
control, optional OAuth provider details, and relationships to dependent
models (profile, alarms).
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    """Enumeration of supported user roles for RBAC."""

    USER = "user"
    WELLNESS_COACH = "wellness_coach"
    ADMIN = "admin"


class User(Base):
    """
    SQLAlchemy model representing an application user.

    Attributes:
        id: Auto-incrementing primary key.
        email: Unique, indexed email address used for authentication.
        username: Unique, indexed display name.
        hashed_password: Bcrypt-hashed password string.
        full_name: Optional full name for display purposes.
        role: RBAC role (user, wellness_coach, admin).
        is_active: Soft-delete / deactivation flag.
        is_verified: Whether the user's email has been verified.
        oauth_provider: Name of the OAuth provider (e.g. 'google').
        oauth_id: External user ID from the OAuth provider.
        created_at: Timestamp of record creation (UTC).
        updated_at: Timestamp of last update (UTC).
        profile: One-to-one relationship with ``UserProfile``.
        alarms: One-to-many relationship with ``Alarm``.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    oauth_provider = Column(String(50), nullable=True)
    oauth_id = Column(String(255), nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────
    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    alarms = relationship(
        "Alarm",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """Return a developer-friendly string representation."""
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
