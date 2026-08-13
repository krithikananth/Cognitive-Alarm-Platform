"""Baseline core schema.

Before this revision the migration chain started at
``20260716_attempt_log_audit`` with ``down_revision = None``, and that
revision only *altered* tables it assumed already existed. The core schema
(users, alarms, wake events, challenge sessions, challenge logs, …) was
only ever provisioned by ``Base.metadata.create_all`` at app startup, so
``alembic upgrade head`` against an empty database produced a DB with no
application tables at all.

This revision is the missing root: it creates every core table so a clean
database can be provisioned from migrations alone.

Every block is guarded on table existence, so databases that were already
provisioned by ``create_all`` (and stamped at a later head) are untouched.
Column-level changes introduced by later revisions are already folded in
here; those revisions are individually idempotent and become no-ops on a
freshly migrated database.

Revision ID: 20260101_baseline
Revises:
Create Date: 2026-08-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260101_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Reverse-dependency order, used by downgrade()
_TABLES_IN_DROP_ORDER = (
    "notifications",
    "alarm_wake_events",
    "alarm_snooze_events",
    "alarm_challenge_logs",
    "challenge_sessions",
    "user_device_tokens",
    "notification_preferences",
    "user_profiles",
    "coach_assignments",
    "revoked_tokens",
    "system_settings",
    "analytics_events",
    "alarms",
    "users",
)


def _existing_tables() -> set:
    try:
        return set(inspect(op.get_bind()).get_table_names())
    except Exception:
        return set()


def _index(name: str, table: str, cols: list, *, unique: bool = False) -> None:
    op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    existing = _existing_tables()

    # ── users ────────────────────────────────────────────────────────
    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=255), nullable=True),
            sa.Column(
                "role",
                sa.Enum("USER", "WELLNESS_COACH", "ADMIN", name="userrole"),
                nullable=False,
            ),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("is_verified", sa.Boolean(), nullable=False),
            sa.Column("oauth_provider", sa.String(length=50), nullable=True),
            sa.Column("oauth_id", sa.String(length=255), nullable=True),
            sa.Column("tokens_valid_after", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_users_id", "users", ["id"])
        _index("ix_users_email", "users", ["email"], unique=True)
        _index("ix_users_username", "users", ["username"], unique=True)
        _index("ix_users_created_at", "users", ["created_at"])

    # ── user_profiles ────────────────────────────────────────────────
    if "user_profiles" not in existing:
        op.create_table(
            "user_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("preferred_wake_time", sa.Time(), nullable=True),
            sa.Column("sleep_duration_hours", sa.Float(), nullable=False),
            sa.Column("timezone", sa.String(length=50), nullable=False),
            sa.Column("productivity_goals", sa.JSON(), nullable=True),
            sa.Column(
                "difficulty_preference",
                sa.Enum(
                    "BEGINNER",
                    "EASY",
                    "MEDIUM",
                    "HARD",
                    "EXPERT",
                    name="difficultypreference",
                ),
                nullable=False,
            ),
            sa.Column(
                "adapted_difficulty",
                sa.Enum(
                    "BEGINNER",
                    "EASY",
                    "MEDIUM",
                    "HARD",
                    "EXPERT",
                    name="difficultypreference",
                ),
                nullable=False,
            ),
            sa.Column("habit_preferences", sa.JSON(), nullable=True),
            sa.Column("wake_up_consistency_score", sa.Float(), nullable=False),
            sa.Column("total_alarms_dismissed", sa.Integer(), nullable=False),
            sa.Column("total_snoozes", sa.Integer(), nullable=False),
            sa.Column("streak_days", sa.Integer(), nullable=False),
            sa.Column("best_streak", sa.Integer(), nullable=False),
            sa.Column("last_successful_wake_date", sa.Date(), nullable=True),
            sa.Column("consecutive_success_streak", sa.Integer(), nullable=False),
            sa.Column("consecutive_failure_streak", sa.Integer(), nullable=False),
            sa.Column("last_adapted_success_streak", sa.Integer(), nullable=False),
            sa.Column("last_adapted_failure_streak", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        _index("ix_user_profiles_id", "user_profiles", ["id"])

    # ── alarms ───────────────────────────────────────────────────────
    if "alarms" not in existing:
        op.create_table(
            "alarms",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("alarm_time", sa.Time(), nullable=False),
            sa.Column(
                "alarm_type",
                sa.Enum(
                    "DAILY",
                    "WEEKDAY",
                    "WEEKEND",
                    "ONE_TIME",
                    "SMART_ADAPTIVE",
                    name="alarmtype",
                ),
                nullable=False,
            ),
            sa.Column("days_of_week", sa.JSON(), nullable=True),
            sa.Column("one_time_date", sa.Date(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("snooze_limit", sa.Integer(), nullable=False),
            sa.Column("snooze_interval_minutes", sa.Integer(), nullable=False),
            sa.Column(
                "challenge_type",
                sa.Enum(
                    "MATH",
                    "LOGIC",
                    "MEMORY",
                    "WORD_GAME",
                    "WORD",
                    "PATTERN",
                    "RIDDLE",
                    "QUIZ",
                    "RANDOM",
                    name="challengetype",
                ),
                nullable=False,
            ),
            sa.Column("challenge_count", sa.Integer(), nullable=False),
            sa.Column("challenge_difficulty", sa.String(length=50), nullable=False),
            sa.Column("volume", sa.Integer(), nullable=False),
            sa.Column("vibrate", sa.Boolean(), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=True),
            sa.Column("next_trigger_at", sa.DateTime(), nullable=True),
            sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
            sa.Column("last_notified_trigger_at", sa.DateTime(), nullable=True),
            sa.Column("total_dismissals", sa.Integer(), nullable=False),
            sa.Column("total_snoozes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_alarms_id", "alarms", ["id"])
        _index("ix_alarms_user_active", "alarms", ["user_id", "is_active"])
        _index("ix_alarms_user_next_trigger", "alarms", ["user_id", "next_trigger_at"])
        _index(
            "ix_alarms_active_next_trigger",
            "alarms",
            ["is_active", "next_trigger_at"],
        )

    # ── challenge_sessions (wake-up verification state) ───────────────
    if "challenge_sessions" not in existing:
        op.create_table(
            "challenge_sessions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("alarm_id", sa.Integer(), nullable=False),
            sa.Column("answer", sa.String(length=255), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("challenge_type", sa.String(length=50), nullable=False),
            sa.Column("difficulty", sa.String(length=50), nullable=False),
            sa.Column("time_limit_seconds", sa.Integer(), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("consecutive_correct", sa.Integer(), nullable=False),
            sa.Column("required_correct", sa.Integer(), nullable=False),
            sa.Column("total_failed_attempts", sa.Integer(), nullable=False),
            sa.Column("escalation_level", sa.Integer(), nullable=False),
            sa.Column("verification_token", sa.String(length=64), nullable=True),
            sa.Column("wake_confirmed", sa.Boolean(), nullable=False),
            sa.Column("session_started_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "alarm_id", name="uq_challenge_session_user_alarm"
            ),
        )
        _index("ix_challenge_sessions_id", "challenge_sessions", ["id"])
        _index("ix_challenge_sessions_user_id", "challenge_sessions", ["user_id"])
        _index("ix_challenge_sessions_alarm_id", "challenge_sessions", ["alarm_id"])

    # ── alarm_challenge_logs (per-attempt audit) ──────────────────────
    if "alarm_challenge_logs" not in existing:
        op.create_table(
            "alarm_challenge_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("alarm_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("challenge_type", sa.String(length=50), nullable=False),
            sa.Column("difficulty", sa.String(length=50), nullable=False),
            sa.Column("challenge_prompt", sa.Text(), nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False),
            sa.Column("time_taken_seconds", sa.Integer(), nullable=False),
            sa.Column("failed_attempts", sa.Integer(), nullable=False),
            sa.Column("points_earned", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["alarm_id"], ["alarms.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_alarm_challenge_logs_id", "alarm_challenge_logs", ["id"])
        _index("ix_alarm_challenge_logs_user_id", "alarm_challenge_logs", ["user_id"])
        _index("ix_alarm_challenge_logs_alarm_id", "alarm_challenge_logs", ["alarm_id"])
        _index(
            "ix_alarm_challenge_logs_created_at", "alarm_challenge_logs", ["created_at"]
        )
        _index(
            "ix_alarm_challenge_logs_user_created",
            "alarm_challenge_logs",
            ["user_id", "created_at"],
        )
        _index(
            "ix_alarm_challenge_logs_alarm_created",
            "alarm_challenge_logs",
            ["alarm_id", "created_at"],
        )
        _index(
            "ix_alarm_challenge_logs_created_breakdown",
            "alarm_challenge_logs",
            ["created_at", "challenge_type", "difficulty", "is_correct", "points_earned"],
        )

    # ── alarm_snooze_events (anti-snooze audit) ───────────────────────
    if "alarm_snooze_events" not in existing:
        op.create_table(
            "alarm_snooze_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("alarm_id", sa.Integer(), nullable=False),
            sa.Column("snooze_number", sa.Integer(), nullable=False),
            sa.Column("snooze_limit_at_event", sa.Integer(), nullable=False),
            sa.Column("next_trigger_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["alarm_id"], ["alarms.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_alarm_snooze_events_id", "alarm_snooze_events", ["id"])
        _index("ix_alarm_snooze_events_user_id", "alarm_snooze_events", ["user_id"])
        _index("ix_alarm_snooze_events_alarm_id", "alarm_snooze_events", ["alarm_id"])
        _index(
            "ix_alarm_snooze_events_created_at", "alarm_snooze_events", ["created_at"]
        )
        _index(
            "ix_alarm_snooze_events_user_created",
            "alarm_snooze_events",
            ["user_id", "created_at"],
        )
        _index(
            "ix_alarm_snooze_events_alarm_created",
            "alarm_snooze_events",
            ["alarm_id", "created_at"],
        )

    # ── alarm_wake_events (wake-up confirmation tracking) ─────────────
    if "alarm_wake_events" not in existing:
        op.create_table(
            "alarm_wake_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("alarm_id", sa.Integer(), nullable=False),
            sa.Column("triggered_at", sa.DateTime(), nullable=False),
            sa.Column("dismissed_at", sa.DateTime(), nullable=True),
            sa.Column("dismiss_method", sa.String(length=50), nullable=True),
            sa.Column("challenges_required", sa.Integer(), nullable=False),
            sa.Column("challenges_completed", sa.Integer(), nullable=False),
            sa.Column("consecutive_correct", sa.Integer(), nullable=False),
            sa.Column("failed_attempts", sa.Integer(), nullable=False),
            sa.Column("snooze_count_at_dismiss", sa.Integer(), nullable=False),
            sa.Column("time_to_dismiss_seconds", sa.Integer(), nullable=True),
            sa.Column("wakefulness_score", sa.Float(), nullable=True),
            sa.Column("wakefulness_level", sa.String(length=20), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["alarm_id"], ["alarms.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_alarm_wake_events_id", "alarm_wake_events", ["id"])
        _index("ix_alarm_wake_events_user_id", "alarm_wake_events", ["user_id"])
        _index("ix_alarm_wake_events_alarm_id", "alarm_wake_events", ["alarm_id"])
        _index(
            "ix_alarm_wake_events_user_dismissed",
            "alarm_wake_events",
            ["user_id", "dismissed_at"],
        )
        _index(
            "ix_alarm_wake_events_user_verified_dismissed",
            "alarm_wake_events",
            ["user_id", "verified", "dismissed_at"],
        )
        _index("ix_alarm_wake_events_dismissed", "alarm_wake_events", ["dismissed_at"])
        _index(
            "ix_alarm_wake_events_dismissed_outcome",
            "alarm_wake_events",
            ["dismissed_at", "verified", "dismiss_method", "time_to_dismiss_seconds"],
        )

    # ── analytics_events ─────────────────────────────────────────────
    if "analytics_events" not in existing:
        op.create_table(
            "analytics_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=True),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("event_data", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_analytics_events_id", "analytics_events", ["id"])
        _index("ix_analytics_events_user_id", "analytics_events", ["user_id"])
        _index("ix_analytics_events_event_type", "analytics_events", ["event_type"])
        _index("ix_analytics_events_created_at", "analytics_events", ["created_at"])
        _index(
            "ix_analytics_user_created", "analytics_events", ["user_id", "created_at"]
        )
        _index("ix_analytics_event_type", "analytics_events", ["event_type"])
        _index(
            "ix_analytics_event_type_created",
            "analytics_events",
            ["event_type", "created_at"],
        )
        _index(
            "ix_analytics_entity", "analytics_events", ["entity_type", "entity_id"]
        )

    # ── coach_assignments ────────────────────────────────────────────
    if "coach_assignments" not in existing:
        op.create_table(
            "coach_assignments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("coach_id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("assigned_by_user_id", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("notes", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["client_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["coach_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("coach_id", "client_id", name="uq_coach_assignment_pair"),
        )
        _index("ix_coach_assignments_id", "coach_assignments", ["id"])
        _index("ix_coach_assignments_coach_id", "coach_assignments", ["coach_id"])
        _index("ix_coach_assignments_client_id", "coach_assignments", ["client_id"])
        _index(
            "ix_coach_assignments_coach_active",
            "coach_assignments",
            ["coach_id", "is_active"],
        )
        _index(
            "ix_coach_assignments_client_active",
            "coach_assignments",
            ["client_id", "is_active"],
        )

    # ── revoked_tokens ───────────────────────────────────────────────
    if "revoked_tokens" not in existing:
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("token_type", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_revoked_tokens_id", "revoked_tokens", ["id"])
        _index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
        _index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"])
        _index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])

    # ── system_settings ──────────────────────────────────────────────
    if "system_settings" not in existing:
        op.create_table(
            "system_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email_notifications_enabled", sa.Boolean(), nullable=False),
            sa.Column("push_notifications_enabled", sa.Boolean(), nullable=False),
            sa.Column("maintenance_mode", sa.Boolean(), nullable=False),
            sa.Column("maintenance_message", sa.String(length=500), nullable=False),
            sa.Column("habit_score_alert_threshold", sa.Float(), nullable=False),
            sa.Column("consistency_alert_threshold", sa.Float(), nullable=False),
            sa.Column("snooze_alert_threshold", sa.Float(), nullable=False),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # ── notification_preferences ─────────────────────────────────────
    if "notification_preferences" not in existing:
        op.create_table(
            "notification_preferences",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
            sa.Column("bedtime_reminder_enabled", sa.Boolean(), nullable=False),
            sa.Column("bedtime_reminder_minutes_before", sa.Integer(), nullable=False),
            sa.Column("wake_reminder_enabled", sa.Boolean(), nullable=False),
            sa.Column("wake_reminder_minutes_before", sa.Integer(), nullable=False),
            sa.Column("habit_alerts_enabled", sa.Boolean(), nullable=False),
            sa.Column("motivational_enabled", sa.Boolean(), nullable=False),
            sa.Column("motivational_time", sa.Time(), nullable=True),
            sa.Column("quiet_hours_start", sa.Time(), nullable=True),
            sa.Column("quiet_hours_end", sa.Time(), nullable=True),
            sa.Column("notification_sound", sa.String(length=32), nullable=False),
            sa.Column("notification_frequency", sa.String(length=32), nullable=False),
            sa.Column("push_enabled", sa.Boolean(), nullable=False),
            sa.Column("email_notifications_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )
        _index("ix_notification_preferences_id", "notification_preferences", ["id"])

    # ── user_device_tokens ───────────────────────────────────────────
    if "user_device_tokens" not in existing:
        op.create_table(
            "user_device_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("fcm_token", sa.String(length=512), nullable=False),
            sa.Column(
                "device_type",
                sa.Enum("WEB", "IOS", "ANDROID", name="devicetype"),
                nullable=False,
            ),
            sa.Column("device_name", sa.String(length=255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("failure_count", sa.Integer(), nullable=False),
            sa.Column("deactivated_at", sa.DateTime(), nullable=True),
            sa.Column("deactivated_reason", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("fcm_token"),
        )
        _index("ix_user_device_tokens_id", "user_device_tokens", ["id"])
        _index("ix_user_device_tokens_user_id", "user_device_tokens", ["user_id"])
        _index(
            "ix_device_tokens_user_active",
            "user_device_tokens",
            ["user_id", "is_active"],
        )

    # ── notifications ────────────────────────────────────────────────
    if "notifications" not in existing:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column(
                "notification_type",
                sa.Enum(
                    "BEDTIME_REMINDER",
                    "WAKE_REMINDER",
                    "ALARM_TRIGGER",
                    "HABIT_ALERT",
                    "MOTIVATIONAL",
                    "ANNOUNCEMENT",
                    name="notificationtype",
                ),
                nullable=False,
            ),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("data", sa.JSON(), nullable=True),
            sa.Column(
                "channel",
                sa.Enum("PUSH", "IN_APP", "EMAIL", name="notificationchannel"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "PENDING",
                    "SENT",
                    "DELIVERED",
                    "FAILED",
                    "READ",
                    name="notificationstatus",
                ),
                nullable=False,
            ),
            sa.Column("scheduled_at", sa.DateTime(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("push_attempts", sa.Integer(), nullable=False),
            sa.Column("email_attempts", sa.Integer(), nullable=False),
            sa.Column("next_retry_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.String(length=500), nullable=True),
            sa.Column("related_alarm_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["related_alarm_id"], ["alarms.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        _index("ix_notifications_id", "notifications", ["id"])
        _index("ix_notifications_user_id", "notifications", ["user_id"])
        _index("ix_notifications_user_status", "notifications", ["user_id", "status"])
        _index(
            "ix_notifications_user_type",
            "notifications",
            ["user_id", "notification_type"],
        )
        _index("ix_notifications_scheduled", "notifications", ["status", "scheduled_at"])
        _index("ix_notifications_retry", "notifications", ["next_retry_at"])


def downgrade() -> None:
    existing = _existing_tables()
    for table in _TABLES_IN_DROP_ORDER:
        if table in existing:
            op.drop_table(table)
