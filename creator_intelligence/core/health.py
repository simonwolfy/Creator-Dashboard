from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass
class HealthCheck:
    name: str
    ok: bool
    message: str

class HealthService:
    REQUIRED_TABLES = {
        "app_settings",
        "content_items",
        "managed_assets",
        "schema_migrations",
    }

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def run(self):
        results = []
        results.append(HealthCheck(
            "Database file",
            self.db_path.exists(),
            str(self.db_path) if self.db_path.exists() else "Database file is missing."
        ))

        try:
            usage = shutil.disk_usage(self.db_path.parent)
            free_gb = usage.free / (1024**3)
            results.append(HealthCheck(
                "Free disk space",
                free_gb >= 1,
                f"{free_gb:.1f} GB free"
            ))
        except Exception as exc:
            results.append(HealthCheck("Free disk space", False, str(exc)))

        if self.db_path.exists():
            try:
                with closing(sqlite3.connect(self.db_path)) as con:
                    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
                    results.append(HealthCheck(
                        "SQLite integrity",
                        integrity == "ok",
                        integrity
                    ))
                    tables = {
                        r[0] for r in con.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    missing = sorted(self.REQUIRED_TABLES - tables)
                    results.append(HealthCheck(
                        "Required tables",
                        not missing,
                        "All required tables exist." if not missing else f"Missing: {', '.join(missing)}"
                    ))
            except Exception as exc:
                results.append(HealthCheck("SQLite connection", False, str(exc)))
        return results
