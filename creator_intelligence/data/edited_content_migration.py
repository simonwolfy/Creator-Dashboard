EDITED_CONTENT_MIGRATIONS = [
    (
        14,
        "edited_content_intake",
        """
        CREATE TABLE IF NOT EXISTS edited_content_sources (
            folder_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            FOREIGN KEY(folder_id) REFERENCES watched_folders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS edited_content_intake (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL UNIQUE,
            source_folder_id INTEGER,
            publishing_item_id INTEGER UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            platform TEXT NOT NULL DEFAULT 'Multi-platform',
            content_type TEXT NOT NULL DEFAULT 'Short',
            state TEXT NOT NULL DEFAULT 'Needs review',
            learning_status TEXT NOT NULL DEFAULT 'Neutral',
            planned_publish_at TEXT,
            source_platform TEXT,
            source_content_id TEXT,
            sidecar_path TEXT,
            sidecar_json TEXT NOT NULL DEFAULT '{}',
            approved_at TEXT,
            scheduled_at TEXT,
            published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(asset_id) REFERENCES managed_assets(id) ON DELETE CASCADE,
            FOREIGN KEY(source_folder_id) REFERENCES watched_folders(id) ON DELETE SET NULL,
            FOREIGN KEY(publishing_item_id) REFERENCES publishing_items(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_edited_content_state
            ON edited_content_intake(state, planned_publish_at);
        CREATE INDEX IF NOT EXISTS idx_edited_content_source
            ON edited_content_intake(source_platform, source_content_id);
        """,
    ),
]
