from __future__ import annotations

from datetime import datetime
import json
from typing import Any


class SocialPlatformService:
    """Shared credentials, sync state, and published-content analytics."""

    FIELDS = {
        "youtube": ("api_key", "channel_id"),
        "instagram": ("app_id", "app_secret", "access_token", "account_id"),
        "tiktok": ("client_key", "client_secret", "access_token", "user_id"),
    }

    def __init__(self, db):
        self.db = db
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS integration_settings(
                integration_id TEXT PRIMARY KEY, enabled INTEGER DEFAULT 0,
                config_json TEXT NOT NULL DEFAULT '{}', last_connected_at TEXT,
                last_error TEXT, updated_at TEXT NOT NULL)"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_published_titles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'twitch',
                content_type TEXT NOT NULL DEFAULT 'clip', title TEXT NOT NULL,
                game TEXT, published_at TEXT, views INTEGER, likes INTEGER,
                comments INTEGER, watch_time REAL,
                example_type TEXT NOT NULL DEFAULT 'published',
                source_video_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(platform,content_type,title))"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS creator_title_sync_state(
                platform TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'Never synced',
                last_cursor TEXT, last_synced_at TEXT, last_error TEXT,
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_changed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)"""
        )

    def configuration(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        frame = self.db.frame(
            "SELECT enabled,config_json,last_connected_at,last_error FROM integration_settings WHERE integration_id=?",
            (f"{platform}_title_sync",),
        )
        if frame.empty:
            return {"enabled": False, **{field: "" for field in self.FIELDS[platform]}}
        row = frame.iloc[0]
        result = json.loads(row["config_json"] or "{}")
        result.update(enabled=bool(row["enabled"]), last_connected_at=row["last_connected_at"],
                      last_error=row["last_error"])
        return result

    def save_configuration(self, platform: str, values: dict[str, Any], enabled: bool = True) -> None:
        platform = self._platform(platform)
        clean = {field: str(values.get(field) or "").strip() for field in self.FIELDS[platform]}
        now = datetime.now().isoformat()
        self.db.execute(
            """INSERT INTO integration_settings(integration_id,enabled,config_json,updated_at)
               VALUES(?,?,?,?) ON CONFLICT(integration_id) DO UPDATE SET
               enabled=excluded.enabled,config_json=excluded.config_json,updated_at=excluded.updated_at""",
            (f"{platform}_title_sync", int(enabled), json.dumps(clean), now),
        )

    def connection_status(self, platform: str) -> dict[str, Any]:
        platform = self._platform(platform)
        config = self.configuration(platform)
        missing = [field for field in self.FIELDS[platform] if not config.get(field)]
        sync = self.db.frame(
            "SELECT * FROM creator_title_sync_state WHERE platform=?", (platform,)
        )
        sync_row = sync.iloc[0].to_dict() if not sync.empty else {}
        return {
            "platform": platform,
            "configured": not missing,
            "missing": missing,
            "sync_status": sync_row.get("status") or "Never synced",
            "last_synced_at": sync_row.get("last_synced_at"),
            "last_error": sync_row.get("last_error") or config.get("last_error"),
        }

    def content(self, platform: str):
        platform = self._platform(platform)
        return self.db.frame(
            """SELECT id,title,content_type,published_at,views,likes,comments,
               watch_time,source_video_id FROM creator_published_titles
               WHERE platform=? ORDER BY COALESCE(published_at,created_at) DESC""",
            (platform,),
        )

    def summary(self, platform: str) -> dict[str, Any]:
        frame = self.content(platform)
        if frame.empty:
            return {"posts": 0, "views": 0, "likes": 0, "comments": 0,
                    "watch_time": 0.0, "engagement_rate": 0.0}
        for column in ("views", "likes", "comments", "watch_time"):
            frame[column] = frame[column].fillna(0)
        views = int(frame["views"].sum())
        engagements = int(frame["likes"].sum() + frame["comments"].sum())
        return {"posts": len(frame), "views": views,
                "likes": int(frame["likes"].sum()),
                "comments": int(frame["comments"].sum()),
                "watch_time": float(frame["watch_time"].sum()),
                "engagement_rate": engagements / views * 100 if views else 0.0}

    def _platform(self, platform: str) -> str:
        clean = platform.strip().lower()
        if clean not in self.FIELDS:
            raise ValueError(f"Unsupported social platform: {platform}")
        return clean
