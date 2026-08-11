HISTORICAL_STREAM_MIGRATIONS = [
    (
        13,
        "historical_stream_foundation",
        """
        CREATE TABLE IF NOT EXISTS historical_stream_days (
            date TEXT PRIMARY KEY,
            stream_day_id TEXT UNIQUE NOT NULL,
            minutes_streamed REAL,
            minutes_watched REAL,
            average_viewers REAL,
            peak_viewers INTEGER,
            unique_viewers INTEGER,
            follows INTEGER,
            chatters INTEGER,
            live_views INTEGER,
            raid_viewers_pct REAL,
            chat_messages INTEGER,
            clips_created INTEGER,
            clip_views INTEGER,
            new_engaged_viewers INTEGER,
            returning_engaged_viewers INTEGER,
            prime_subs INTEGER,
            total_paid_subs INTEGER,
            total_gifted_subs INTEGER,
            canonical_game_sequence TEXT,
            first_observed_game TEXT,
            last_observed_game TEXT,
            game_count INTEGER NOT NULL DEFAULT 0,
            observed_category_changes INTEGER NOT NULL DEFAULT 0,
            mapping_status TEXT NOT NULL DEFAULT 'Unresolved',
            mapping_confidence TEXT,
            evidence_coverage TEXT,
            mapping_source TEXT,
            original_game_sequence TEXT,
            original_mapping_status TEXT,
            original_confidence TEXT,
            quality_flags TEXT,
            source_file TEXT NOT NULL,
            import_batch_id TEXT,
            imported_at TEXT
        );

        CREATE TABLE IF NOT EXISTS historical_game_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_day_date TEXT NOT NULL,
            event_ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            game TEXT NOT NULL,
            changed_by TEXT,
            parse_method TEXT,
            next_distinct_game_ts TEXT,
            source_line INTEGER,
            raw_source_text TEXT,
            source_file TEXT NOT NULL,
            import_batch_id TEXT,
            FOREIGN KEY(stream_day_date) REFERENCES historical_stream_days(date),
            UNIQUE(event_ts, event_type, game, source_file)
        );

        CREATE TABLE IF NOT EXISTS historical_game_event_review (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_day_date TEXT,
            event_ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            game TEXT NOT NULL,
            changed_by TEXT,
            parse_method TEXT,
            next_distinct_game_ts TEXT,
            source_line INTEGER,
            raw_source_text TEXT,
            source_file TEXT NOT NULL,
            import_batch_id TEXT,
            review_reason TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(event_ts, event_type, game, source_file)
        );

        CREATE INDEX IF NOT EXISTS idx_historical_stream_mapping
            ON historical_stream_days(mapping_status, game_count);
        CREATE INDEX IF NOT EXISTS idx_historical_stream_confidence
            ON historical_stream_days(mapping_confidence);
        CREATE INDEX IF NOT EXISTS idx_historical_events_day
            ON historical_game_events(stream_day_date, event_ts);
        CREATE INDEX IF NOT EXISTS idx_historical_event_review_day
            ON historical_game_event_review(stream_day_date, event_ts);
        """,
    ),
]
