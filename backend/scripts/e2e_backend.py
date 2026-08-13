"""
Backend runner for the browser end-to-end suite.

Provisions a disposable SQLite database with deterministic accounts and
history, then serves the real API so Playwright drives the same stack a user
would.  Seeding and serving live in one entry point so the database is always
ready before the first HTTP request, regardless of how the test runner
sequences its hooks.

Everything it touches (database file, log directory) is taken from the
environment, so it never disturbs the development database.

Run directly (Playwright's ``webServer`` does exactly this)::

    python scripts/e2e_backend.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ── Accounts the specs sign in as ─────────────────────────────────────
PASSWORD = "E2ePass123!"

USER_EMAIL = "e2e.user@example.com"
COACH_EMAIL = "e2e.coach@example.com"
ADMIN_EMAIL = "e2e.admin@example.com"
RESET_EMAIL = "e2e.reset@example.com"
UNVERIFIED_EMAIL = "e2e.unverified@example.com"
# Owned by the verified-wake journey alone. It starts with no history at all so
# the dashboard's empty state is a truthful "before" reading.
WAKER_EMAIL = "e2e.waker@example.com"


def _database_path() -> Path | None:
    """Return the SQLite file backing ``DATABASE_URL``, if it is SQLite."""
    url = os.environ.get("DATABASE_URL", "")
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    return Path(url[len(prefix):]).resolve()


def _reset_database() -> None:
    """Delete the previous run's database so every suite starts identical."""
    path = _database_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def _truncate_logs() -> None:
    """Empty the log directory so the mailbox reader only sees this run."""
    directory = Path(os.environ.get("LOG_DIR", "logs"))
    if not directory.is_absolute():
        directory = BACKEND_ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    for entry in directory.glob("*.log*"):
        try:
            entry.unlink()
        except OSError:
            pass


def seed() -> None:
    """Create the schema and populate the fixed end-to-end dataset."""
    # Imported here so the environment overrides above are already in place.
    import app.main  # noqa: F401  (registers every model on Base.metadata)
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.models.alarm import (
        Alarm,
        AlarmChallengeLog,
        AlarmType,
        ChallengeType,
    )
    from app.models.alarm_wake_event import AlarmWakeEvent
    from app.models.coach_assignment import CoachAssignment
    from app.models.profile import DifficultyPreference, UserProfile
    from app.models.user import User, UserRole
    from app.utils.hashing import get_password_hash

    Base.metadata.create_all(bind=engine)

    hashed = get_password_hash(PASSWORD)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    def make_user(
        *,
        email: str,
        username: str,
        full_name: str,
        role: UserRole,
        verified: bool = True,
    ) -> User:
        return User(
            email=email,
            username=username,
            hashed_password=hashed,
            full_name=full_name,
            role=role,
            is_active=True,
            is_verified=verified,
        )

    with SessionLocal() as db:
        if db.query(User).filter(User.email == USER_EMAIL).first():
            return

        user = make_user(
            email=USER_EMAIL,
            username="e2euser",
            full_name="Eva Everyday",
            role=UserRole.USER,
        )
        coach = make_user(
            email=COACH_EMAIL,
            username="e2ecoach",
            full_name="Cody Coach",
            role=UserRole.WELLNESS_COACH,
        )
        admin = make_user(
            email=ADMIN_EMAIL,
            username="e2eadmin",
            full_name="Ada Admin",
            role=UserRole.ADMIN,
        )
        resetter = make_user(
            email=RESET_EMAIL,
            username="e2ereset",
            full_name="Rita Reset",
            role=UserRole.USER,
        )
        unverified = make_user(
            email=UNVERIFIED_EMAIL,
            username="e2eunverified",
            full_name="Uma Unverified",
            role=UserRole.USER,
            verified=False,
        )
        waker = make_user(
            email=WAKER_EMAIL,
            username="e2ewaker",
            full_name="Wes Waker",
            role=UserRole.USER,
        )
        db.add_all([user, coach, admin, resetter, unverified, waker])
        db.commit()

        for account in (user, coach, admin, resetter, unverified):
            db.refresh(account)
            db.add(
                UserProfile(
                    user_id=account.id,
                    preferred_wake_time=time(7, 0),
                    sleep_duration_hours=8.0,
                    timezone="UTC",
                    difficulty_preference=DifficultyPreference.MEDIUM,
                    adapted_difficulty=DifficultyPreference.MEDIUM,
                    wake_up_consistency_score=72.0,
                    total_alarms_dismissed=12,
                    streak_days=4,
                    best_streak=9,
                    last_successful_wake_date=date.today(),
                )
            )

        # Deliberately blank: the verified-wake journey asserts that the very
        # first completed wake is what moves these numbers off zero.
        db.refresh(waker)
        db.add(
            UserProfile(
                user_id=waker.id,
                preferred_wake_time=time(7, 0),
                sleep_duration_hours=8.0,
                timezone="UTC",
                difficulty_preference=DifficultyPreference.EASY,
                adapted_difficulty=DifficultyPreference.EASY,
                wake_up_consistency_score=0.0,
                total_alarms_dismissed=0,
                streak_days=0,
                best_streak=0,
            )
        )

        db.add(
            CoachAssignment(
                coach_id=coach.id,
                client_id=user.id,
                assigned_by_user_id=admin.id,
                is_active=True,
            )
        )

        # A ringable alarm for the snooze / fail-wake journey. MATH keeps the
        # served challenge answerable without guessing at generated content.
        alarm = Alarm(
            user_id=user.id,
            title="Seeded Morning Alarm",
            description="Ringing target for the end-to-end suite",
            alarm_time=time(7, 0),
            alarm_type=AlarmType.DAILY,
            is_active=True,
            snooze_limit=2,
            snooze_interval_minutes=5,
            challenge_type=ChallengeType.MATH,
            challenge_count=1,
            challenge_difficulty="easy",
            label="Seeded Morning Alarm",
        )
        db.add(alarm)
        db.commit()
        db.refresh(alarm)

        # Ringing target for the verified-wake journey, on its own account so
        # solving it cannot disturb the snooze counters the fail-wake journey
        # asserts on. MATH is the one generator whose prompt is machine
        # solvable ("Solve: <equation> = ?"), so the spec answers correctly
        # instead of guessing.
        db.add(
            Alarm(
                user_id=waker.id,
                title="Verified Wake Alarm",
                description="Solved correctly by the verified-wake journey",
                alarm_time=time(7, 0),
                alarm_type=AlarmType.DAILY,
                is_active=True,
                snooze_limit=2,
                snooze_interval_minutes=5,
                challenge_type=ChallengeType.MATH,
                challenge_count=1,
                challenge_difficulty="easy",
                label="Verified Wake Alarm",
            )
        )
        db.commit()

        # History so reports, analytics and the coach roster render real
        # numbers instead of empty states.
        for index in range(1, 15):
            triggered = now - timedelta(days=index, hours=1)
            dismissed = triggered + timedelta(minutes=3)
            correct = index % 4 != 0
            db.add(
                AlarmWakeEvent(
                    user_id=user.id,
                    alarm_id=alarm.id,
                    triggered_at=triggered,
                    dismissed_at=dismissed,
                    dismiss_method="challenge",
                    challenges_required=1,
                    challenges_completed=1,
                    consecutive_correct=1 if correct else 0,
                    failed_attempts=0 if correct else 1,
                    snooze_count_at_dismiss=index % 3,
                    time_to_dismiss_seconds=180,
                    wakefulness_score=78.0 if correct else 55.0,
                    wakefulness_level="alert" if correct else "groggy",
                    verified=True,
                )
            )
            db.add(
                AlarmChallengeLog(
                    alarm_id=alarm.id,
                    user_id=user.id,
                    challenge_type="MATH",
                    difficulty="medium",
                    challenge_prompt=f"{index} + {index}",
                    is_correct=correct,
                    time_taken_seconds=9 + index,
                    failed_attempts=0 if correct else 1,
                    points_earned=10 if correct else 0,
                    created_at=dismissed,
                )
            )

        db.commit()


def main() -> None:
    """Reset, seed and serve the API for the browser suite."""
    import uvicorn

    _reset_database()
    _truncate_logs()
    seed()

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("E2E_BACKEND_HOST", "localhost"),
        port=int(os.environ.get("E2E_BACKEND_PORT", "8100")),
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
