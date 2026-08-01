from __future__ import annotations
import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Any
from datetime import datetime
import pandas as pd
from creator_intelligence.data.migrations import MIGRATIONS
from creator_intelligence.core.exceptions import DatabaseError, MigrationError

log = logging.getLogger(__name__)

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

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

    def migrate(self):
        try:
            with self.connect() as con:
                con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )""")
                applied = {
                    row[0] for row in con.execute("SELECT version FROM schema_migrations")
                }
                for version, name, sql in MIGRATIONS:
                    if version in applied:
                        continue
                    log.info("Applying migration %s: %s", version, name)
                    con.executescript(sql)
                    con.execute(
                        "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                        (version, name, datetime.now().isoformat())
                    )
        except Exception as exc:
            raise MigrationError(f"Migration failed: {exc}") from exc

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
        return bool(self.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ))

    def integrity_check(self):
        return self.scalar("PRAGMA integrity_check", default="unknown")
