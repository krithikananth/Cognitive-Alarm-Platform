"""
Database initialisation helpers.

Provides functions to create all tables from the ORM metadata and to seed the
database with a default admin account.
"""

import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base  # noqa: F401 – ensures all models are imported
from app.db.session import SessionLocal, engine
from app.models.user import User, UserRole
from app.models.profile import UserProfile, DifficultyPreference
from app.utils.hashing import get_password_hash

logger = logging.getLogger(__name__)


def init_db() -> None:
    """
    Create all database tables defined by the ORM metadata.

    This is safe to call multiple times — existing tables are not dropped
    or recreated.
    """
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created / verified successfully.")


def create_default_admin() -> None:
    """
    Seed the database with a default admin user if one does not already exist.

    The admin account uses the following credentials:
        - Email: ``admin@icap.com``
        - Username: ``admin``
        - Password: ``Admin123!``

    A corresponding default ``UserProfile`` is also created.
    """
    db: Session = SessionLocal()
    try:
        existing_admin: User | None = (
            db.query(User)
            .filter(User.email == "admin@icap.com")
            .first()
        )
        if existing_admin is not None:
            logger.info("Default admin user already exists — skipping seed.")
            return

        admin_user = User(
            email="admin@icap.com",
            username="admin",
            hashed_password=get_password_hash("Admin123!"),
            full_name="System Administrator",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(admin_user)
        db.flush()  # populate admin_user.id before creating the profile

        admin_profile = UserProfile(
            user_id=admin_user.id,
            sleep_duration_hours=8.0,
            timezone="UTC",
            difficulty_preference=DifficultyPreference.MEDIUM,
        )
        db.add(admin_profile)
        db.commit()

        logger.info(
            "Default admin user created (email=admin@icap.com, password=Admin123!)."
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to create default admin user.")
        raise
    finally:
        db.close()
