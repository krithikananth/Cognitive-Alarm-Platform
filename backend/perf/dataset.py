"""Deterministic synthetic dataset generator for dashboard benchmarking.

Produces a realistically shaped workload: users with profiles, several alarms
each, and 12 months of wake / snooze / challenge / analytics history. The
generator is seeded so repeated runs create byte-identical data, which is what
makes before/after index comparisons meaningful.

Bulk inserts go through ``Session.bulk_save_objects`` so seeding a
multi-hundred-thousand-row dataset stays in the tens of seconds range.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List

from sqlalchemy import create_engine, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.alarm import Alarm, AlarmChallengeLog, AlarmType, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.analytics_event import AnalyticsEvent
from app.models.coach_assignment import CoachAssignment
from app.models.profile import DifficultyPreference, UserProfile
from app.models.user import User, UserRole

# Every model module must be imported before ``create_all`` so the metadata is
# complete; these are referenced only for that side effect. A model missing
# here creates a database the app cannot serve from: the first request that
# touches the absent table fails with "no such table".
from app.models import challenge_delivery as _challenge_delivery  # noqa: F401
from app.models import challenge_session as _challenge_session  # noqa: F401
from app.models import notification as _notification  # noqa: F401
from app.models import recommendation_feedback as _recommendation_feedback  # noqa: F401
from app.models import revoked_token as _revoked_token  # noqa: F401
from app.models import system_settings as _system_settings  # noqa: F401

CHALLENGE_TYPES = ["math", "word_game", "memory", "pattern", "logic"]
DIFFICULTIES = ["easy", "medium", "hard"]
DISMISS_METHODS = ["challenge", "snooze_exhausted", "abandoned"]

# Shared credentials for every seeded account. The hash is computed once per
# seeding run (bcrypt is slow, and per-user hashing would dominate seed time).
# These accounts exist only in throwaway benchmark databases.
SEED_PASSWORD = "PerfTest#123"


def seed_password_hash() -> str:
    """Hash the shared benchmark password using the app's own hasher."""
    from app.utils.hashing import get_password_hash

    return get_password_hash(SEED_PASSWORD)


@dataclass(frozen=True)
class DatasetProfile:
    """Size parameters for a generated dataset."""

    name: str
    users: int
    history_days: int
    alarms_per_user: int
    wake_events_per_user_per_day: float
    challenge_attempts_per_wake: int
    snoozes_per_wake: float
    analytics_events_per_user_per_day: float


PROFILES: Dict[str, DatasetProfile] = {
    # Fast feedback loop while iterating on the harness itself.
    "small": DatasetProfile(
        name="small",
        users=50,
        history_days=90,
        alarms_per_user=3,
        wake_events_per_user_per_day=0.9,
        challenge_attempts_per_wake=2,
        snoozes_per_wake=0.6,
        analytics_events_per_user_per_day=1.5,
    ),
    # Default benchmark size — one year of history for a mid-size tenant.
    "medium": DatasetProfile(
        name="medium",
        users=500,
        history_days=365,
        alarms_per_user=4,
        wake_events_per_user_per_day=0.9,
        challenge_attempts_per_wake=2,
        snoozes_per_wake=0.6,
        analytics_events_per_user_per_day=1.5,
    ),
    # Stress size — surfaces sequential scans that "medium" can still hide.
    "large": DatasetProfile(
        name="large",
        users=2000,
        history_days=365,
        alarms_per_user=5,
        wake_events_per_user_per_day=1.0,
        challenge_attempts_per_wake=3,
        snoozes_per_wake=0.8,
        analytics_events_per_user_per_day=3.0,
    ),
}


@dataclass
class SeedResult:
    """Identifiers and row counts produced by a seeding run."""

    profile: DatasetProfile
    user_id: int
    admin_id: int
    coach_id: int
    row_counts: Dict[str, int]

    def total_rows(self) -> int:
        return sum(self.row_counts.values())


def make_engine(database_url: str) -> Engine:
    """Create an engine tuned for bulk seeding and benchmarking."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


def _naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo — all datetime columns in this schema are naive UTC."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def seed(
    engine: Engine,
    profile: DatasetProfile,
    *,
    seed_value: int = 20260807,
    batch_size: int = 5000,
) -> SeedResult:
    """Drop, recreate, and populate the schema with a deterministic dataset.

    Returns the ids of the three principals used by the benchmark
    (regular user, admin, wellness coach) plus per-table row counts.
    """
    rng = random.Random(seed_value)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session: Session = factory()

    now = _naive_utc(datetime.now(timezone.utc))
    history_start = now - timedelta(days=profile.history_days)

    try:
        users = _build_users(profile, history_start, now, rng)
        session.bulk_save_objects(users)
        session.commit()

        user_rows = session.query(User.id, User.role).order_by(User.id).all()
        user_ids = [row.id for row in user_rows]
        admin_id = next(r.id for r in user_rows if r.role == UserRole.ADMIN)
        coach_id = next(r.id for r in user_rows if r.role == UserRole.WELLNESS_COACH)
        benchmark_user_id = next(
            r.id
            for r in user_rows
            if r.role == UserRole.USER
        )

        session.bulk_save_objects(
            _build_profiles(user_ids, history_start, now, rng)
        )
        session.commit()

        session.bulk_save_objects(
            _build_coach_assignments(coach_id, admin_id, user_ids, now)
        )
        session.commit()

        session.bulk_save_objects(
            _build_alarms(user_ids, profile, history_start, now, rng)
        )
        session.commit()

        alarm_rows = session.query(Alarm.id, Alarm.user_id).all()
        alarms_by_user: Dict[int, List[int]] = {}
        for alarm_id, owner_id in alarm_rows:
            alarms_by_user.setdefault(owner_id, []).append(alarm_id)

        _bulk_stream(
            session,
            _iter_activity(profile, alarms_by_user, history_start, rng),
            batch_size,
        )
        session.commit()

        row_counts = count_rows(session)
    finally:
        session.close()

    _post_seed_optimize(engine)

    return SeedResult(
        profile=profile,
        user_id=benchmark_user_id,
        admin_id=admin_id,
        coach_id=coach_id,
        row_counts=row_counts,
    )


def count_rows(session: Session) -> Dict[str, int]:
    """Return row counts for every table the dashboards read from."""
    models = {
        "users": User,
        "user_profiles": UserProfile,
        "coach_assignments": CoachAssignment,
        "alarms": Alarm,
        "alarm_wake_events": AlarmWakeEvent,
        "alarm_snooze_events": AlarmSnoozeEvent,
        "alarm_challenge_logs": AlarmChallengeLog,
        "analytics_events": AnalyticsEvent,
    }
    return {
        name: session.query(func.count(model.id)).scalar() or 0
        for name, model in models.items()
    }


def _post_seed_optimize(engine: Engine) -> None:
    """Refresh planner statistics so EXPLAIN reflects the seeded distribution."""
    with engine.begin() as conn:
        if engine.dialect.name in ("postgresql", "sqlite"):
            conn.exec_driver_sql("ANALYZE")


def _bulk_stream(session: Session, iterator, batch_size: int) -> None:
    """Flush generated ORM objects in fixed-size batches to bound memory."""
    batch: List[object] = []
    for obj in iterator:
        batch.append(obj)
        if len(batch) >= batch_size:
            session.bulk_save_objects(batch)
            session.flush()
            batch = []
    if batch:
        session.bulk_save_objects(batch)
        session.flush()


def _build_users(
    profile: DatasetProfile,
    history_start: datetime,
    now: datetime,
    rng: random.Random,
) -> List[User]:
    """Build the user population: 1 admin, 1 coach, and N regular users."""
    password_hash = seed_password_hash()
    users: List[User] = [
        User(
            email="perf-admin@perf.example.com",
            username="perf_admin",
            hashed_password=password_hash,
            full_name="Perf Admin",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
            created_at=history_start,
            updated_at=history_start,
        ),
        User(
            email="perf-coach@perf.example.com",
            username="perf_coach",
            hashed_password=password_hash,
            full_name="Perf Coach",
            role=UserRole.WELLNESS_COACH,
            is_active=True,
            is_verified=True,
            created_at=history_start,
            updated_at=history_start,
        ),
    ]

    span_seconds = max(int((now - history_start).total_seconds()), 1)
    for i in range(profile.users):
        created = history_start + timedelta(
            seconds=rng.randrange(span_seconds)
        )
        users.append(
            User(
                email=f"perf-user-{i:05d}@perf.example.com",
                username=f"perf_user_{i:05d}",
                hashed_password=password_hash,
                full_name=f"Perf User {i:05d}",
                role=UserRole.USER,
                is_active=rng.random() > 0.05,
                is_verified=rng.random() > 0.15,
                created_at=created,
                updated_at=created,
            )
        )
    return users


def _build_profiles(
    user_ids: List[int],
    history_start: datetime,
    now: datetime,
    rng: random.Random,
) -> List[UserProfile]:
    """One profile per user with plausible streak and consistency values."""
    profiles = []
    for user_id in user_ids:
        streak = rng.randint(0, 40)
        profiles.append(
            UserProfile(
                user_id=user_id,
                preferred_wake_time=time(hour=rng.randint(5, 8), minute=rng.choice([0, 15, 30, 45])),
                sleep_duration_hours=round(rng.uniform(5.5, 9.0), 1),
                timezone="UTC",
                productivity_goals={"focus_hours": rng.randint(2, 8)},
                difficulty_preference=rng.choice(list(DifficultyPreference)),
                adapted_difficulty=rng.choice(list(DifficultyPreference)),
                habit_preferences={"reminder": True},
                wake_up_consistency_score=round(rng.uniform(0, 100), 1),
                total_alarms_dismissed=rng.randint(0, 400),
                total_snoozes=rng.randint(0, 300),
                streak_days=streak,
                best_streak=streak + rng.randint(0, 20),
                last_successful_wake_date=(
                    date.today() - timedelta(days=rng.randint(0, 3))
                ),
                consecutive_success_streak=rng.randint(0, 15),
                consecutive_failure_streak=rng.randint(0, 4),
                last_adapted_success_streak=0,
                last_adapted_failure_streak=0,
                created_at=history_start,
                updated_at=now,
            )
        )
    return profiles


def _build_coach_assignments(
    coach_id: int,
    admin_id: int,
    user_ids: List[int],
    now: datetime,
) -> List[CoachAssignment]:
    """Assign the first 25 regular users to the benchmark coach."""
    client_ids = [uid for uid in user_ids if uid not in (coach_id, admin_id)][:25]
    return [
        CoachAssignment(
            coach_id=coach_id,
            client_id=client_id,
            assigned_by_user_id=admin_id,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        for client_id in client_ids
    ]


def _build_alarms(
    user_ids: List[int],
    profile: DatasetProfile,
    history_start: datetime,
    now: datetime,
    rng: random.Random,
) -> List[Alarm]:
    """Build alarms per user, some scheduled inside the next 24h window."""
    alarms = []
    alarm_types = list(AlarmType)
    challenge_types = list(ChallengeType)
    for user_id in user_ids:
        for slot in range(profile.alarms_per_user):
            next_trigger = now + timedelta(hours=rng.uniform(0.5, 48))
            alarms.append(
                Alarm(
                    user_id=user_id,
                    title=f"Alarm {slot + 1}",
                    description="Benchmark alarm",
                    alarm_time=time(hour=rng.randint(5, 9), minute=rng.choice([0, 15, 30, 45])),
                    alarm_type=rng.choice(alarm_types),
                    days_of_week=[0, 1, 2, 3, 4],
                    is_active=rng.random() > 0.2,
                    snooze_limit=rng.randint(1, 5),
                    snooze_interval_minutes=rng.choice([5, 10, 15]),
                    challenge_type=rng.choice(challenge_types),
                    challenge_count=rng.randint(1, 3),
                    challenge_difficulty=rng.choice(DIFFICULTIES),
                    volume=rng.randint(50, 100),
                    vibrate=True,
                    label=f"label-{slot}",
                    next_trigger_at=next_trigger,
                    last_triggered_at=now - timedelta(hours=rng.uniform(1, 72)),
                    total_dismissals=rng.randint(0, 200),
                    total_snoozes=rng.randint(0, 150),
                    created_at=history_start,
                    updated_at=now,
                )
            )
    return alarms


def _iter_activity(
    profile: DatasetProfile,
    alarms_by_user: Dict[int, List[int]],
    history_start: datetime,
    rng: random.Random,
):
    """Yield wake, snooze, challenge, and analytics rows day by day."""
    for user_id, alarm_ids in alarms_by_user.items():
        if not alarm_ids:
            continue
        for day in range(profile.history_days):
            day_start = history_start + timedelta(days=day)

            if rng.random() > profile.wake_events_per_user_per_day:
                continue

            alarm_id = rng.choice(alarm_ids)
            wake_hour = rng.randint(5, 9)
            triggered_at = day_start.replace(
                hour=wake_hour, minute=rng.randrange(60), second=0, microsecond=0
            )
            time_to_dismiss = rng.randint(20, 900)
            dismissed_at = triggered_at + timedelta(seconds=time_to_dismiss)
            verified = rng.random() > 0.18
            snooze_count = int(rng.random() < profile.snoozes_per_wake) * rng.randint(0, 3)
            failed_attempts = rng.randint(0, 2)
            challenges_required = rng.randint(1, 3)

            yield AlarmWakeEvent(
                user_id=user_id,
                alarm_id=alarm_id,
                triggered_at=triggered_at,
                dismissed_at=dismissed_at,
                dismiss_method=(
                    rng.choice(DISMISS_METHODS[:2]) if verified else "abandoned"
                ),
                challenges_required=challenges_required,
                challenges_completed=challenges_required if verified else 0,
                consecutive_correct=challenges_required if verified else 0,
                failed_attempts=failed_attempts,
                snooze_count_at_dismiss=snooze_count,
                time_to_dismiss_seconds=time_to_dismiss,
                wakefulness_score=round(rng.uniform(20, 100), 1),
                wakefulness_level=rng.choice(["low", "moderate", "high"]),
                verified=verified,
            )

            for n in range(snooze_count):
                yield AlarmSnoozeEvent(
                    user_id=user_id,
                    alarm_id=alarm_id,
                    snooze_number=n + 1,
                    snooze_limit_at_event=3,
                    next_trigger_at=triggered_at + timedelta(minutes=5 * (n + 1)),
                    created_at=triggered_at + timedelta(minutes=5 * n),
                )

            for attempt in range(profile.challenge_attempts_per_wake):
                yield AlarmChallengeLog(
                    alarm_id=alarm_id,
                    user_id=user_id,
                    challenge_type=rng.choice(CHALLENGE_TYPES),
                    difficulty=rng.choice(DIFFICULTIES),
                    challenge_prompt="What is 7 x 8?",
                    is_correct=rng.random() > 0.25,
                    time_taken_seconds=rng.randint(2, 90),
                    failed_attempts=failed_attempts,
                    points_earned=rng.randint(0, 30),
                    created_at=triggered_at + timedelta(seconds=30 * (attempt + 1)),
                )

            analytics_today = int(profile.analytics_events_per_user_per_day)
            if rng.random() < profile.analytics_events_per_user_per_day % 1:
                analytics_today += 1
            for _ in range(analytics_today):
                yield AnalyticsEvent(
                    user_id=user_id,
                    event_type=rng.choice(
                        [
                            "challenge.attempted",
                            "alarm.snoozed",
                            "alarm.dismissed",
                            "dashboard.viewed",
                            "recommendation.served",
                        ]
                    ),
                    entity_type="alarm",
                    entity_id=alarm_id,
                    source=rng.choice(["server", "client"]),
                    event_data={"day": day},
                    created_at=day_start + timedelta(minutes=rng.randrange(1440)),
                )
