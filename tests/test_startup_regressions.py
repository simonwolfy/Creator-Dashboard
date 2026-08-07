from pathlib import Path
import sqlite3

from creator_intelligence.data.database import Database
from creator_intelligence.services.import_schema_compat import upgrade_legacy_import_jobs
from creator_intelligence.ui.charts import safe_numeric_values


def test_legacy_import_jobs_is_upgraded(tmp_path: Path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as con:
        con.execute(
            """CREATE TABLE import_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                importer_id TEXT,
                detected_type TEXT,
                status TEXT NOT NULL,
                rows_imported INTEGER DEFAULT 0,
                rows_skipped INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )"""
        )
        con.execute(
            """INSERT INTO import_jobs(
                source_path,file_name,file_hash,status,
                rows_imported,rows_skipped,started_at
            ) VALUES('old.csv','old.csv','abc','Completed',4,1,'2026-01-01')"""
        )

    db = Database(path)
    assert upgrade_legacy_import_jobs(db) is True
    assert upgrade_legacy_import_jobs(db) is False

    history = db.frame(
        """SELECT batch_id,rows_inserted,rows_skipped
           FROM import_jobs ORDER BY id"""
    )
    assert history.iloc[0]["batch_id"] == "legacy-1"
    assert int(history.iloc[0]["rows_inserted"]) == 4
    assert int(history.iloc[0]["rows_skipped"]) == 1


def test_chart_numeric_values_replace_invalid_data():
    values = safe_numeric_values([1, None, float("nan"), "2.5", "bad"])
    assert values == [1.0, 0.0, 0.0, 2.5, 0.0]
