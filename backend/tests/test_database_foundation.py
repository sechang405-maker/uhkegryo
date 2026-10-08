from pathlib import Path

import pytest

from backend.db.migrate import MIGRATIONS_DIR, migrate, migration_sql
from backend.shared.config import Settings


class _FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        self.connection.transaction_count += 1
        self.connection.transaction_depth += 1
        self.applied = set(self.connection.applied)
        self.migration_statements = list(self.connection.migration_statements)
        self.history_writes = list(self.connection.history_writes)

    async def __aexit__(self, exc_type, exc, traceback):
        self.connection.transaction_depth -= 1
        if exc_type is not None:
            self.connection.applied = self.applied
            self.connection.migration_statements = self.migration_statements
            self.connection.history_writes = self.history_writes


class _FakeConnection:
    def __init__(self, fail_on=None):
        self.applied = set()
        self.migration_statements = []
        self.history_writes = []
        self.transaction_count = 0
        self.transaction_depth = 0
        self.fail_on = fail_on

    def transaction(self):
        return _FakeTransaction(self)

    async def fetchval(self, query, version):
        assert self.transaction_depth == 1
        assert "FROM schema_migrations" in query
        return version if version in self.applied else None

    async def execute(self, statement, *args):
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in statement:
            assert self.transaction_depth == 0
            return "CREATE TABLE"
        if statement.startswith("INSERT INTO schema_migrations"):
            assert self.transaction_depth == 1
            self.applied.add(args[0])
            self.history_writes.append(args[0])
            return "INSERT 0 1"
        assert self.transaction_depth == 1
        if statement == self.fail_on:
            raise RuntimeError("migration failed")
        self.migration_statements.append(statement)


def test_database_url_is_required():
    assert Settings.model_fields["database_url"].is_required()


def test_initial_migration_contains_session_and_job_tables():
    sql = migration_sql()

    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "user_id" not in sql
    assert "CREATE TABLE IF NOT EXISTS jobs" in sql
    assert "REFERENCES sessions(session_id) ON DELETE CASCADE" in sql
    assert "next_retry_at TIMESTAMPTZ DEFAULT NULL" in sql


def test_migration_file_is_in_repository():
    migration = Path(__file__).parents[1] / "db" / "migrations" / "001_initial.sql"

    assert migration.is_file()


def test_legacy_user_id_migration_is_in_repository():
    migration = MIGRATIONS_DIR / "002_remove_legacy_session_user_id.sql"

    assert "DROP COLUMN IF EXISTS user_id" in migration.read_text(encoding="utf-8")


def test_migrate_applies_sql_files_in_order():
    import asyncio

    connection = _FakeConnection()
    asyncio.run(migrate(connection))
    first_run = list(connection.migration_statements)
    asyncio.run(migrate(connection))

    expected = [
        path.read_text(encoding="utf-8")
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
    ]
    assert first_run == expected
    assert connection.migration_statements == expected
    assert connection.applied == {path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql"))}
    assert connection.history_writes == sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))
    assert connection.transaction_count == len(expected) * 2


def test_failed_migration_is_not_recorded():
    import asyncio

    migration = sorted(MIGRATIONS_DIR.glob("*.sql"))[0]
    connection = _FakeConnection(
        migration.read_text(encoding="utf-8")
    )

    with pytest.raises(RuntimeError, match="migration failed"):
        asyncio.run(migrate(connection))

    assert connection.applied == set()
    assert connection.history_writes == []
    assert connection.migration_statements == []
