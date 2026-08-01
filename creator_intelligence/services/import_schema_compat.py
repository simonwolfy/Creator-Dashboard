from __future__ import annotations


def upgrade_legacy_import_jobs(db) -> bool:
    """Upgrade the pre-Import-Center import_jobs schema in place.

    Older Creator Intelligence databases used a smaller import_jobs table.
    SQLite does not add columns when CREATE TABLE IF NOT EXISTS is executed,
    so the table must be rebuilt before the current Import Center queries
    fields such as batch_id, rows_inserted, and rollback_available.
    """
    if not db.table_exists("import_jobs"):
        return False

    with db.connect() as con:
        columns = {
            row["name"] for row in con.execute("PRAGMA table_info(import_jobs)")
        }
        if "batch_id" in columns:
            return False

        con.execute("ALTER TABLE import_jobs RENAME TO import_jobs_legacy")
        con.execute(
            """CREATE TABLE import_jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                archived_path TEXT,
                file_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                importer_id TEXT,
                platform TEXT,
                detected_type TEXT,
                destination_table TEXT,
                status TEXT NOT NULL,
                rows_detected INTEGER DEFAULT 0,
                rows_staged INTEGER DEFAULT 0,
                rows_inserted INTEGER DEFAULT 0,
                rows_updated INTEGER DEFAULT 0,
                rows_skipped INTEGER DEFAULT 0,
                rows_rejected INTEGER DEFAULT 0,
                warning_json TEXT DEFAULT '[]',
                error_message TEXT,
                backup_path TEXT,
                rollback_available INTEGER DEFAULT 0,
                rolled_back_at TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )"""
        )
        con.execute(
            """INSERT INTO import_jobs(
                id,batch_id,source_path,file_name,file_hash,importer_id,
                detected_type,status,rows_detected,rows_staged,
                rows_inserted,rows_updated,rows_skipped,rows_rejected,
                warning_json,error_message,rollback_available,
                started_at,finished_at
            )
            SELECT
                id,'legacy-' || id,source_path,file_name,file_hash,
                importer_id,detected_type,status,
                COALESCE(rows_imported,0),COALESCE(rows_imported,0),
                COALESCE(rows_imported,0),0,COALESCE(rows_skipped,0),0,
                '[]',error_message,0,started_at,finished_at
            FROM import_jobs_legacy"""
        )
        con.execute("DROP TABLE import_jobs_legacy")

    return True
