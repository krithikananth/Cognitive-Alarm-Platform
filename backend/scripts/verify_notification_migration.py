"""Verify the notification delivery-tracking migration against a legacy schema.

Builds a database holding the *pre-migration* ``notifications`` and
``user_device_tokens`` tables, stamps Alembic at the preceding revision, then
upgrades and downgrades to prove the migration is additive, idempotent, and
reversible on databases created before the delivery-tracking columns existed.

Run from the backend directory:
    python scripts/verify_notification_migration.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

DB_PATH = BACKEND_DIR / "migration_check.db"
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DATABASE_URL"] = DB_URL

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

PREVIOUS_REVISION = "20260806_coach_assignments"

NEW_NOTIFICATION_COLUMNS = {
    "delivered_at",
    "push_attempts",
    "email_attempts",
    "next_retry_at",
    "last_error",
}
NEW_TOKEN_COLUMNS = {
    "last_success_at",
    "failure_count",
    "deactivated_at",
    "deactivated_reason",
}

LEGACY_SCHEMA = [
    """
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        notification_type VARCHAR(32) NOT NULL,
        title VARCHAR(255) NOT NULL,
        body TEXT NOT NULL,
        data JSON,
        channel VARCHAR(16) NOT NULL,
        status VARCHAR(16) NOT NULL,
        scheduled_at DATETIME,
        sent_at DATETIME,
        read_at DATETIME,
        related_alarm_id INTEGER,
        created_at DATETIME NOT NULL
    )
    """,
    """
    CREATE TABLE user_device_tokens (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        fcm_token VARCHAR(512) NOT NULL UNIQUE,
        device_type VARCHAR(16) NOT NULL,
        device_name VARCHAR(255),
        is_active BOOLEAN NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
    """
    INSERT INTO notifications
        (id, user_id, notification_type, title, body, channel, status,
         scheduled_at, created_at)
    VALUES
        (1, 1, 'WAKE_REMINDER', 'Legacy row', 'Predates delivery tracking',
         'PUSH', 'SENT', '2026-08-01 06:00:00', '2026-08-01 05:00:00')
    """,
    """
    INSERT INTO user_device_tokens
        (id, user_id, fcm_token, device_type, is_active, created_at, updated_at)
    VALUES
        (1, 1, 'legacy-token-0001', 'WEB', 1,
         '2026-08-01 05:00:00', '2026-08-01 05:00:00')
    """,
]


def columns(engine, table: str) -> set:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()

    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        for stmt in LEGACY_SCHEMA:
            conn.exec_driver_sql(stmt)

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)

    # Pretend this database was already up to date before the new revision.
    command.stamp(cfg, PREVIOUS_REVISION)

    before = columns(engine, "notifications")
    assert not (NEW_NOTIFICATION_COLUMNS & before), "fixture is not a legacy schema"

    command.upgrade(cfg, "head")

    notif_cols = columns(engine, "notifications")
    token_cols = columns(engine, "user_device_tokens")
    missing = (NEW_NOTIFICATION_COLUMNS - notif_cols) | (
        NEW_TOKEN_COLUMNS - token_cols
    )
    assert not missing, f"upgrade did not add: {sorted(missing)}"

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT title, push_attempts, email_attempts, delivered_at, "
                "next_retry_at, last_error FROM notifications WHERE id = 1"
            )
        ).one()
        assert row.title == "Legacy row", "existing data was altered"
        assert row.push_attempts == 0, f"expected 0 attempts, got {row.push_attempts}"
        assert row.email_attempts == 0
        assert row.delivered_at is None
        assert row.next_retry_at is None
        assert row.last_error is None

        token = conn.execute(
            text(
                "SELECT fcm_token, failure_count, last_success_at, "
                "deactivated_at, deactivated_reason FROM user_device_tokens "
                "WHERE id = 1"
            )
        ).one()
        assert token.fcm_token == "legacy-token-0001"
        assert token.failure_count == 0
        assert token.last_success_at is None

    print("upgrade: columns added, existing rows preserved and back-filled")

    # Re-running must be a no-op rather than an error.
    command.upgrade(cfg, "head")
    print("upgrade: re-run is idempotent")

    command.downgrade(cfg, PREVIOUS_REVISION)
    after = columns(engine, "notifications")
    assert not (NEW_NOTIFICATION_COLUMNS & after), "downgrade left columns behind"
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT COUNT(*) FROM notifications")
            ).scalar_one()
            == 1
        ), "downgrade lost rows"
    print("downgrade: columns removed, rows intact")

    engine.dispose()
    DB_PATH.unlink(missing_ok=True)
    print("\nnotification delivery-tracking migration verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
