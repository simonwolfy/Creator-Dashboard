from pathlib import Path
import sqlite3
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from creator_intelligence.core.application import CreatorIntelligenceApplication
from creator_intelligence.data.database import Database
from creator_intelligence.services.import_schema_compat import upgrade_legacy_import_jobs
from creator_intelligence.ui.charts import safe_numeric_values
from creator_intelligence.ui.main_window import MainWindow, ModuleFailurePage


FOUNDATIONAL_TABLES = {
    "chat_events",
    "content_links",
    "content_pipeline",
    "game_segments",
    "prediction_runs",
    "twitch_daily",
    "twitch_session_minutes",
    "youtube_age",
    "youtube_audience_daily",
    "youtube_cities",
    "youtube_content",
    "youtube_geography",
    "historical_stream_days",
    "historical_game_events",
    "historical_game_event_review",
}


def test_fresh_database_creates_runtime_foundation(tmp_path: Path):
    db = Database(tmp_path / "fresh.db")

    applied = db.migrate()

    assert applied[-1].name == "historical_stream_foundation"
    assert "runtime_foundation" in {migration.name for migration in applied}
    with db.connect() as con:
        tables = {
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert FOUNDATIONAL_TABLES <= tables


def test_runtime_foundation_migration_preserves_existing_data(tmp_path: Path):
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as con:
        con.execute(
            """CREATE TABLE content_pipeline(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                platform TEXT,
                content_type TEXT,
                game_topic TEXT,
                status TEXT NOT NULL DEFAULT 'Ideas',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        con.execute(
            """INSERT INTO content_pipeline(title,status,created_at,updated_at)
               VALUES('Keep me','Ideas','2026-08-07','2026-08-07')"""
        )

    db = Database(path)
    db.migrate()

    assert db.scalar("SELECT COUNT(*) FROM content_pipeline") == 1


def test_fresh_workspace_builds_every_page(tmp_path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt_app = QApplication.instance() or QApplication([])
    application = CreatorIntelligenceApplication(tmp_path / "workspace")
    window = None
    try:
        runtime = application.start()
        runtime.ui_settings = QSettings(
            str(tmp_path / "ui-settings.ini"),
            QSettings.Format.IniFormat,
        )
        window = MainWindow(runtime, application_core=application)
        failures = {
            key: page.error_message
            for key, page in window.pages_by_key.items()
            if isinstance(page, ModuleFailurePage)
        }
        assert failures == {}
    finally:
        if window is not None:
            window.close()
        application.stop()
        qt_app.processEvents()


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
