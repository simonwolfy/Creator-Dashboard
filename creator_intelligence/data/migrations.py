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
    (
        3,
        "creator_goals_runtime_schema",
        """
        ALTER TABLE creator_goals ADD COLUMN name TEXT;
        ALTER TABLE creator_goals ADD COLUMN current_value REAL NOT NULL DEFAULT 0;
        ALTER TABLE creator_goals ADD COLUMN target_value REAL;
        ALTER TABLE creator_goals ADD COLUMN target_date TEXT;
        ALTER TABLE creator_goals ADD COLUMN notes TEXT;
        ALTER TABLE creator_goals ADD COLUMN updated_at TEXT;
        ALTER TABLE creator_goals ADD COLUMN status TEXT NOT NULL DEFAULT 'Active';

        UPDATE creator_goals
        SET name = COALESCE(name, metric),
            target_value = COALESCE(target_value, target),
            updated_at = COALESCE(updated_at, created_at)
        WHERE name IS NULL OR target_value IS NULL OR updated_at IS NULL;
        """
    ),
    (
        4,
        "unified_content_library",
        """
        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY,
            platform TEXT NOT NULL,
            external_id TEXT,
            content_type TEXT NOT NULL,
            title TEXT NOT NULL,
            game_topic TEXT,
            series_name TEXT,
            episode_number TEXT,
            status TEXT NOT NULL DEFAULT 'Planned',
            editor TEXT,
            collaborators_json TEXT NOT NULL DEFAULT '[]',
            tags_json TEXT NOT NULL DEFAULT '[]',
            thumbnail_url TEXT,
            source_url TEXT,
            local_path TEXT,
            recorded_at TEXT,
            published_at TEXT,
            duration_seconds REAL,
            views INTEGER NOT NULL DEFAULT 0,
            watch_hours REAL NOT NULL DEFAULT 0,
            engagement_rate REAL,
            retention_rate REAL,
            revenue REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(platform, external_id)
        );

        CREATE TABLE IF NOT EXISTS content_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_content_id TEXT NOT NULL,
            child_content_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL DEFAULT 'derived_from',
            start_seconds REAL,
            end_seconds REAL,
            notes TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(parent_content_id, child_content_id, relationship_type),
            FOREIGN KEY(parent_content_id) REFERENCES content_items(id) ON DELETE CASCADE,
            FOREIGN KEY(child_content_id) REFERENCES content_items(id) ON DELETE CASCADE,
            CHECK(parent_content_id <> child_content_id)
        );

        CREATE INDEX IF NOT EXISTS idx_content_items_platform_type
            ON content_items(platform, content_type);
        CREATE INDEX IF NOT EXISTS idx_content_items_game_series
            ON content_items(game_topic, series_name);
        CREATE INDEX IF NOT EXISTS idx_content_items_status
            ON content_items(status);
        CREATE INDEX IF NOT EXISTS idx_content_relationships_parent
            ON content_relationships(parent_content_id);
        CREATE INDEX IF NOT EXISTS idx_content_relationships_child
            ON content_relationships(child_content_id);
        """
    ),
]
