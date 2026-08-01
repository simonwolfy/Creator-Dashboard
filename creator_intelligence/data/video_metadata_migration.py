VIDEO_METADATA_MIGRATIONS = [
    (
        10,
        "video_metadata_engine",
        """
        CREATE TABLE IF NOT EXISTS video_asset_metadata (
            managed_asset_id TEXT PRIMARY KEY,
            duration_seconds REAL,
            width INTEGER,
            height INTEGER,
            frame_rate REAL,
            video_codec TEXT,
            video_profile TEXT,
            pixel_format TEXT,
            color_space TEXT,
            color_transfer TEXT,
            color_primaries TEXT,
            hdr_format TEXT,
            audio_codec TEXT,
            audio_tracks INTEGER,
            audio_channels INTEGER,
            audio_sample_rate INTEGER,
            container_format TEXT,
            bit_rate INTEGER,
            rotation INTEGER,
            probe_status TEXT NOT NULL DEFAULT 'Pending',
            probe_error TEXT,
            probed_at TEXT,
            probe_json TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(managed_asset_id) REFERENCES managed_assets(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_video_metadata_status
            ON video_asset_metadata(probe_status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_video_metadata_dimensions
            ON video_asset_metadata(width, height, frame_rate);
        CREATE INDEX IF NOT EXISTS idx_video_metadata_duration
            ON video_asset_metadata(duration_seconds);
        """,
    ),
]
