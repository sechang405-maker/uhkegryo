"""One-shot database migration entry point used by Docker Compose."""

from backend.db.run_migrations import run_migrations


def test_run_migrations_uses_configured_database_and_closes_connection():
    events: list[object] = []

    class Connection:
        async def close(self):
            events.append("closed")

    connection = Connection()

    async def connect(url: str):
        events.append(("connect", url))
        return connection

    async def migrate(candidate):
        events.append(("migrate", candidate))

    operation = run_migrations(
        "postgresql://user:password@app-db:5432/uhkegryo",
        connect=connect,
        migrate_schema=migrate,
    )
    try:
        operation.send(None)
    except StopIteration:
        pass

    assert events == [
        ("connect", "postgresql://user:password@app-db:5432/uhkegryo"),
        ("migrate", connection),
        "closed",
    ]

