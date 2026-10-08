from pathlib import Path
from backend.services.failure_mapping import OperationalFailure, classify_failure


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def migration_sql() -> str:
    return (MIGRATIONS_DIR / "001_initial.sql").read_text(encoding="utf-8")


async def migrate(connection) -> None:
    try:
        await _migrate(connection)
    except Exception as error:
        raise OperationalFailure(classify_failure(error, context="migration"), "migration failed") from None


async def _migrate(connection) -> None:
    await connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        async with connection.transaction():
            applied = await connection.fetchval(
                "SELECT version FROM schema_migrations WHERE version = $1",
                migration.name,
            )
            if applied is not None:
                continue

            await connection.execute(migration.read_text(encoding="utf-8"))
            await connection.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1)",
                migration.name,
            )
