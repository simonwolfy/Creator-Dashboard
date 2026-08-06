from __future__ import annotations

import sqlite3
import pandas as pd

from creator_intelligence.services.social_platforms import SocialPlatformService


class DB:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params)); self.connection.commit(); return cursor.lastrowid
    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def test_platform_credentials_share_canonical_integration_store(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "social.db"))
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    service.save_configuration("instagram", {
        "app_id": "app", "app_secret": "secret", "access_token": "token", "account_id": "account"
    })
    assert service.configuration("youtube")["api_key"] == "key"
    assert service.connection_status("youtube")["configured"] is True
    assert service.connection_status("instagram")["configured"] is True


def test_social_summary_uses_published_performance_rows(tmp_path):
    db = DB(tmp_path / "stats.db"); service = SocialPlatformService(db)
    now = "2026-08-01T00:00:00"
    db.execute("""INSERT INTO creator_published_titles(
        platform,content_type,title,views,likes,comments,watch_time,created_at,updated_at)
        VALUES('tiktok','short','Clip',1000,100,25,300,?,?)""", (now, now))
    summary = service.summary("tiktok")
    assert summary["posts"] == 1
    assert summary["views"] == 1000
    assert summary["engagement_rate"] == 12.5


def test_incomplete_platform_setup_reports_missing_fields(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "missing.db"))
    service.save_configuration("tiktok", {"client_key": "key"})
    status = service.connection_status("tiktok")
    assert status["configured"] is False
    assert "access_token" in status["missing"]
