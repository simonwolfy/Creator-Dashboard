GOOGLE_DRIVE_MIGRATIONS = [
    (
        7,
        "google_drive_foundation",
        """
        CREATE TABLE IF NOT EXISTS google_drive_connections (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            client_secrets_path TEXT,
            account_email TEXT,
            display_name TEXT,
            status TEXT NOT NULL DEFAULT 'Not configured',
            scopes_json TEXT NOT NULL DEFAULT '[]',
            connected_at TEXT,
            last_tested_at TEXT,
            last_error TEXT,
            updated_at TEXT NOT NULL
        );

        INSERT OR IGNORE INTO google_drive_connections(id, status, scopes_json, updated_at)
        VALUES(1, 'Not configured', '[]', datetime('now'));
        """,
    ),
]
