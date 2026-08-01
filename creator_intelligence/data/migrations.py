MIGRATIONS = [
    (
        1,
        "core_foundation",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS creator_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            metric TEXT NOT NULL,
            target REAL NOT NULL,
            platform TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(period, metric, platform)
        );
        CREATE TABLE IF NOT EXISTS content_metadata (
            content_id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            game_topic TEXT,
            series TEXT,
            episode TEXT,
            collaborator TEXT,
            thumbnail_style TEXT,
            hook_style TEXT,
            tags TEXT,
            notes TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS data_quality_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            category TEXT NOT NULL,
            table_name TEXT,
            record_key TEXT,
            description TEXT NOT NULL,
            resolved INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS prediction_actuals (
            prediction_id INTEGER PRIMARY KEY,
            actual_json TEXT NOT NULL,
            matched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recommendation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            objective TEXT NOT NULL,
            recommendations_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS raids (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_ts TEXT,
            raider TEXT,
            raid_size INTEGER,
            retained_5m REAL,
            retained_15m REAL,
            followers_after INTEGER,
            source TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            platform TEXT,
            deductible INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """
    ),
    (
        2,
        "indexes_and_audit",
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_ts TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id TEXT,
            details_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_content_metadata_platform ON content_metadata(platform);
        CREATE INDEX IF NOT EXISTS idx_goals_period ON creator_goals(period);
        CREATE INDEX IF NOT EXISTS idx_quality_open ON data_quality_issues(resolved, severity);
        CREATE INDEX IF NOT EXISTS idx_audit_event_ts ON audit_log(event_ts);
        """
    ),
]
