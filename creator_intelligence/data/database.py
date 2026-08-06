from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from creator_intelligence.core.exceptions import DatabaseError, MigrationError
from creator_intelligence.data.google_drive_folder_migration import GOOGLE_DRIVE_FOLDER_MIGRATIONS
from creator_intelligence.data.google_drive_metadata_migration import GOOGLE_DRIVE_METADATA_MIGRATIONS
from creator_intelligence.data.google_drive_migrations import GOOGLE_DRIVE_MIGRATIONS
from creator_intelligence.data.migration_manager import MigrationManager, MigrationRecord
from creator_intelligence.data.migrations import MIGRATIONS
from creator_intelligence.data.video_metadata_migration import VIDEO_METADATA_MIGRATIONS

log = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_manager = MigrationManager(
            [
                *MIGRATIONS,
                *GOOGLE_DRIVE_MIGRATIONS,
                *GOOGLE_DRIVE_FOLDER_MIGRATIONS,
                *GOOGLE_DRIVE_METADATA_MIGRATIONS,
                *VIDEO_METADATA_MIGRATIONS,
            ]
        )
        self.last_applied_migrations: list[MigrationRecord] = []

    def _configure(self, con):
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=5000")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        self._configure(con)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def migrate(self) -> list[MigrationRecord]:
        try:
            with self.connect() as con:
                self.last_applied_migrations = self.migration_manager.apply(con)
                return list(self.last_applied_migrations)
        except Exception as exc:
            raise MigrationError(f"Migration failed: {exc}") from exc

    def migration_history(self) -> list[MigrationRecord]:
        with self.connect() as con:
            return self.migration_manager.history(con)

    def pending_migrations(self) -> list[tuple[int, str, str]]:
        with self.connect() as con:
            return self.migration_manager.pending(con)

    def frame(self, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
        try:
            with sqlite3.connect(self.path) as con:
                return pd.read_sql_query(sql, con, params=tuple(params))
        except Exception as exc:
            raise DatabaseError(str(exc)) from exc

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        try:
            with self.connect() as con:
                cur = con.execute(sql, tuple(params))
                return cur.lastrowid
        except Exception as exc:
            raise DatabaseError(str(exc)) from exc

    def executemany(self, sql: str, rows):
        try:
            with self.connect() as con:
                con.executemany(sql, rows)
        except Exception as exc:
            raise DatabaseError(str(exc)) from exc

    def scalar(self, sql: str, params: Iterable[Any] = (), default=0):
        try:
            with self.connect() as con:
                row = con.execute(sql, tuple(params)).fetchone()
                return row[0] if row and row[0] is not None else default
        except Exception as exc:
            raise DatabaseError(str(exc)) from exc

    def table_exists(self, table: str) -> bool:
        return bool(
            self.scalar(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
        )

    def integrity_check(self):
        return self.scalar("PRAGMA integrity_check", default="unknown")
