from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sqlite3
from typing import Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationRecord:
    version: int
    name: str
    applied_at: str


class MigrationManager:
    """Applies ordered SQLite migrations exactly once and exposes history."""

    def __init__(self, migrations: Iterable[tuple[int, str, str]]):
        self.migrations = tuple(sorted(migrations, key=lambda item: item[0]))
        versions = [version for version, _, _ in self.migrations]
        if len(versions) != len(set(versions)):
            raise ValueError("Migration versions must be unique.")
        if versions != sorted(versions):
            raise ValueError("Migrations must be ordered by version.")

    def ensure_table(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations(
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )"""
        )

    def history(self, connection: sqlite3.Connection) -> list[MigrationRecord]:
        self.ensure_table(connection)
        rows = connection.execute(
            "SELECT version,name,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        return [MigrationRecord(int(row[0]), str(row[1]), str(row[2])) for row in rows]

    def pending(self, connection: sqlite3.Connection) -> list[tuple[int, str, str]]:
        applied = {record.version for record in self.history(connection)}
        return [migration for migration in self.migrations if migration[0] not in applied]

    def apply(self, connection: sqlite3.Connection) -> list[MigrationRecord]:
        applied_now: list[MigrationRecord] = []
        for version, name, sql in self.pending(connection):
            log.info("Applying migration %s: %s", version, name)
            connection.executescript(sql)
            timestamp = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (version, name, timestamp),
            )
            applied_now.append(MigrationRecord(version, name, timestamp))
        return applied_now
