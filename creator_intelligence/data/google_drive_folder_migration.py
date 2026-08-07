GOOGLE_DRIVE_FOLDER_MIGRATIONS = [
    (
        8,
        "google_drive_folder_mapping",
        """
        CREATE TABLE IF NOT EXISTS google_drive_folder_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drive_folder_id TEXT NOT NULL UNIQUE,
            folder_name TEXT NOT NULL,
            folder_path TEXT,
            purpose TEXT NOT NULL DEFAULT 'Other',
            recursive INTEGER NOT NULL DEFAULT 1,
            metadata_only INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            estimated_files INTEGER,
            estimated_bytes INTEGER,
            last_validated_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_google_drive_folder_mappings_enabled
            ON google_drive_folder_mappings(enabled);
        CREATE INDEX IF NOT EXISTS idx_google_drive_folder_mappings_purpose
            ON google_drive_folder_mappings(purpose);
        """,
    ),
]
