RUNTIME_FOUNDATION_MIGRATIONS = [
    (
        11,
        "runtime_foundation",
        """
        CREATE TABLE IF NOT EXISTS twitch_daily (
            date TEXT PRIMARY KEY,
            average_viewers REAL NOT NULL DEFAULT 0,
            max_viewers INTEGER NOT NULL DEFAULT 0,
            unique_viewers INTEGER NOT NULL DEFAULT 0,
            follows INTEGER NOT NULL DEFAULT 0,
            minutes_streamed INTEGER NOT NULL DEFAULT 0,
            minutes_watched INTEGER NOT NULL DEFAULT 0,
            chat_messages INTEGER NOT NULL DEFAULT 0,
            total_revenue REAL NOT NULL DEFAULT 0,
            source_file TEXT,
            imported_at TEXT
        );

        CREATE TABLE IF NOT EXISTS game_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_start_ts TEXT,
            segment_start_ts TEXT NOT NULL,
            segment_end_ts TEXT,
            game TEXT,
            changed_by TEXT,
            source_file TEXT
        );

        CREATE TABLE IF NOT EXISTS twitch_session_minutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            game TEXT,
            average_viewers REAL,
            new_followers INTEGER NOT NULL DEFAULT 0,
            chat_messages INTEGER NOT NULL DEFAULT 0,
            UNIQUE(session_id, timestamp)
        );

        CREATE TABLE IF NOT EXISTS chat_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            event_ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            game TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS youtube_content (
            content_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            description TEXT,
            publish_time TEXT,
            duration_seconds REAL NOT NULL DEFAULT 0,
            views INTEGER NOT NULL DEFAULT 0,
            engaged_views INTEGER NOT NULL DEFAULT 0,
            watch_time_hours REAL NOT NULL DEFAULT 0,
            avg_percentage_viewed REAL NOT NULL DEFAULT 0,
            stayed_to_watch REAL NOT NULL DEFAULT 0,
            impressions INTEGER NOT NULL DEFAULT 0,
            ctr REAL NOT NULL DEFAULT 0,
            subscribers_gained INTEGER NOT NULL DEFAULT 0,
            subscribers_lost INTEGER NOT NULL DEFAULT 0,
            likes INTEGER NOT NULL DEFAULT 0,
            dislikes INTEGER NOT NULL DEFAULT 0,
            comments INTEGER NOT NULL DEFAULT 0,
            shares INTEGER NOT NULL DEFAULT 0,
            source_file TEXT,
            imported_at TEXT
        );

        CREATE TABLE IF NOT EXISTS youtube_audience_daily (
            date TEXT PRIMARY KEY,
            monthly_audience INTEGER NOT NULL DEFAULT 0,
            subscribers INTEGER NOT NULL DEFAULT 0,
            new_viewers INTEGER NOT NULL DEFAULT 0,
            returning_viewers INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS youtube_geography (
            geography TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS youtube_cities (
            city_id TEXT PRIMARY KEY,
            city_name TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS youtube_age (
            age_group TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS content_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twitch_stream_id TEXT,
            youtube_content_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL DEFAULT 'derived_from',
            source_start_seconds REAL,
            source_end_seconds REAL,
            notes TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS content_pipeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            platform TEXT,
            content_type TEXT,
            game_topic TEXT,
            status TEXT NOT NULL DEFAULT 'Ideas',
            priority TEXT NOT NULL DEFAULT 'Normal',
            assignee TEXT,
            due_date TEXT,
            progress_percent INTEGER NOT NULL DEFAULT 0,
            linked_stream_id TEXT,
            linked_content_id TEXT,
            planned_publish_date TEXT,
            actual_publish_date TEXT,
            editing_hours REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prediction_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            platform TEXT NOT NULL,
            model_name TEXT NOT NULL,
            inputs_json TEXT NOT NULL DEFAULT '{}',
            outputs_json TEXT NOT NULL DEFAULT '{}',
            validation_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_game_segments_start
            ON game_segments(segment_start_ts);
        CREATE INDEX IF NOT EXISTS idx_twitch_session_minutes_session
            ON twitch_session_minutes(session_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_chat_events_session
            ON chat_events(session_id, event_ts);
        CREATE INDEX IF NOT EXISTS idx_youtube_publish_time
            ON youtube_content(publish_time);
        CREATE INDEX IF NOT EXISTS idx_content_links_youtube
            ON content_links(youtube_content_id);
        CREATE INDEX IF NOT EXISTS idx_prediction_runs_platform_created
            ON prediction_runs(platform, created_at);
        """,
    ),
]
