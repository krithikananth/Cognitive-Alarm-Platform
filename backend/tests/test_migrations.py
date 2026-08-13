"""Migration chain verification.

The chain must be able to provision a database on its own. Before the
``20260101_baseline`` revision existed the earliest migration only *altered*
tables it assumed were already present, so ``alembic upgrade head`` against an
empty database produced a schema with none of the application tables — the
Wake-Up Verification module in particular (``alarm_wake_events``,
``challenge_sessions``, ``alarm_challenge_logs``) only existed because
``Base.metadata.create_all`` ran at app startup.

These tests build a real database from migrations alone and compare it against
the schema the ORM models describe.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.db.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Tables the Wake-Up Verification module cannot work without
WAKE_VERIFICATION_TABLES = {
    "alarm_wake_events",
    "challenge_sessions",
    "alarm_challenge_logs",
    "alarm_snooze_events",
    "alarms",
    "users",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture
def migrated_database(tmp_path, monkeypatch):
    """Provision a brand-new SQLite database using only ``alembic upgrade head``."""
    db_path = tmp_path / "migrated.db"
    url = f"sqlite:///{db_path.as_posix()}"
    # env.py prefers DATABASE_URL over the ini value
    monkeypatch.setenv("DATABASE_URL", url)

    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def model_database():
    """The schema the ORM models describe, for comparison."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


class TestMigrationChainStructure:
    def test_single_head(self):
        script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
        assert len(script.get_heads()) == 1

    def test_exactly_one_root_revision(self):
        script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
        roots = [rev for rev in script.walk_revisions() if rev.down_revision is None]
        assert [rev.revision for rev in roots] == ["20260101_baseline"]

    def test_chain_is_linear_from_baseline_to_head(self):
        script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
        revisions = list(script.walk_revisions())
        assert revisions[-1].revision == "20260101_baseline"
        for revision in revisions:
            assert not isinstance(revision.down_revision, tuple), (
                f"{revision.revision} is a merge point"
            )


class TestCleanDatabaseProvisioning:
    def test_upgrade_head_creates_wake_verification_tables(self, migrated_database):
        tables = set(inspect(migrated_database).get_table_names())

        missing = WAKE_VERIFICATION_TABLES - tables
        assert not missing, f"migrations did not create: {sorted(missing)}"

    def test_migrated_schema_matches_the_models(
        self, migrated_database, model_database
    ):
        migrated = inspect(migrated_database)
        expected = inspect(model_database)

        migrated_tables = set(migrated.get_table_names()) - {"alembic_version"}
        expected_tables = set(expected.get_table_names())

        assert migrated_tables == expected_tables

    def test_every_table_has_the_expected_columns(
        self, migrated_database, model_database
    ):
        migrated = inspect(migrated_database)
        expected = inspect(model_database)

        for table in sorted(set(expected.get_table_names())):
            migrated_columns = {c["name"] for c in migrated.get_columns(table)}
            expected_columns = {c["name"] for c in expected.get_columns(table)}
            assert migrated_columns == expected_columns, f"column drift in {table}"

    def test_every_table_has_the_expected_indexes(
        self, migrated_database, model_database
    ):
        migrated = inspect(migrated_database)
        expected = inspect(model_database)

        for table in sorted(set(expected.get_table_names())):
            migrated_indexes = {i["name"] for i in migrated.get_indexes(table)}
            expected_indexes = {i["name"] for i in expected.get_indexes(table)}
            assert migrated_indexes == expected_indexes, f"index drift in {table}"

    def test_wake_event_columns_support_verification_tracking(self, migrated_database):
        columns = {
            c["name"] for c in inspect(migrated_database).get_columns("alarm_wake_events")
        }

        assert {
            "verified",
            "dismiss_method",
            "challenges_required",
            "consecutive_correct",
            "failed_attempts",
            "snooze_count_at_dismiss",
            "wakefulness_score",
            "wakefulness_level",
            "time_to_dismiss_seconds",
        } <= columns

    def test_challenge_session_columns_support_multi_step_verification(
        self, migrated_database
    ):
        columns = {
            c["name"] for c in inspect(migrated_database).get_columns("challenge_sessions")
        }

        assert {
            "consecutive_correct",
            "required_correct",
            "verification_token",
            "wake_confirmed",
            "escalation_level",
            "time_limit_seconds",
        } <= columns

    def test_upgrade_is_repeatable(self, migrated_database, tmp_path, monkeypatch):
        """Re-running upgrade head on an already-migrated DB is a no-op."""
        url = str(migrated_database.url)
        monkeypatch.setenv("DATABASE_URL", url)

        command.upgrade(_alembic_config(url), "head")

        tables = set(inspect(migrated_database).get_table_names())
        assert WAKE_VERIFICATION_TABLES <= tables


class TestBaselineIsIdempotent:
    def test_baseline_skips_tables_that_already_exist(self, tmp_path, monkeypatch):
        """A legacy database provisioned by create_all must survive the baseline."""
        db_path = tmp_path / "legacy.db"
        url = f"sqlite:///{db_path.as_posix()}"

        legacy = create_engine(url)
        Base.metadata.create_all(legacy)
        before = {
            table: {c["name"] for c in inspect(legacy).get_columns(table)}
            for table in inspect(legacy).get_table_names()
        }

        monkeypatch.setenv("DATABASE_URL", url)
        command.upgrade(_alembic_config(url), "head")

        after = {
            table: {c["name"] for c in inspect(legacy).get_columns(table)}
            for table in inspect(legacy).get_table_names()
            if table != "alembic_version"
        }
        legacy.dispose()

        assert after == before
