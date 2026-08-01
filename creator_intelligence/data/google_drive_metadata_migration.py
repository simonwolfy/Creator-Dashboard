GOOGLE_DRIVE_METADATA_MIGRATIONS = [
    (
        9,
        "google_drive_metadata_sync",
        """
        CREATE TABLE IF NOT EXISTS google_drive_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mapping_id INTEGER,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            files_scanned INTEGER NOT NULL DEFAULT 0,
            folders_scanned INTEGER NOT NULL DEFAULT 0,
            assets_created INTEGER NOT NULL DEFAULT 0,
            assets_updated INTEGER NOT NULL DEFAULT 0,
            assets_missing INTEGER NOT NULL DEFAULT 0,
            retries INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            FOREIGN KEY(mapping_id) REFERENCES google_drive_folder_mappings(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS google_drive_files (
            drive_file_id TEXT PRIMARY KEY,
            mapping_id INTEGER NOT NULL,
            asset_id TEXT,
            parent_drive_id TEXT,
            name TEXT NOT NULL,
            relative_path TEXT,
            mime_type TEXT,
            size_bytes INTEGER,
            md5_checksum TEXT,
            created_time TEXT,
            modified_time TEXT,
            web_view_link TEXT,
            owner_name TEXT,
            owner_email TEXT,
            trashed INTEGER NOT NULL DEFAULT 0,
            available INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            raw_json TEXT,
            FOREIGN KEY(mapping_id) REFERENCES google_drive_folder_mappings(id) ON DELETE CASCADE,
            FOREIGN KEY(asset_id) REFERENCES managed_assets(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_drive_files_mapping
            ON google_drive_files(mapping_id, available);
        CREATE INDEX IF NOT EXISTS idx_drive_files_asset
            ON google_drive_files(asset_id);
        CREATE INDEX IF NOT EXISTS idx_drive_sync_runs_mapping
            ON google_drive_sync_runs(mapping_id, started_at DESC);
        """,
    ),
]
