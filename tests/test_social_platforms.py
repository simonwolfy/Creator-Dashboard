from __future__ import annotations

import sqlite3
import pandas as pd

from creator_intelligence.services.social_platforms import SocialPlatformService
from creator_intelligence.core.credential_vault import MemoryCredentialBackend


class DB:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.path = path
        self.credential_backend = MemoryCredentialBackend()
    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params)); self.connection.commit(); return cursor.lastrowid
    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


def test_platform_credentials_share_canonical_integration_store(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "social.db"))
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    service.save_configuration("instagram", {
        "app_id": "app", "app_secret": "secret", "access_token": "token",
        "account_id": "account", "redirect_uri": "https://localhost/callback"
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


def test_instagram_sync_upserts_performance_and_is_idempotent(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "instagram.db"))
    service.save_configuration("instagram", {
        "app_id": "app", "app_secret": "secret", "access_token": "token",
        "account_id": "account", "redirect_uri": "https://localhost/callback",
    })
    records = [{"source_video_id": "ig-1", "title": "Can they wear pants?",
                "content_type": "reels", "published_at": "2026-08-01T00:00:00Z",
                "views": 1000, "likes": 100, "comments": 20, "shares": 5}]
    first = service.sync("instagram", fetcher=lambda platform, cursor: records)
    second = service.sync("instagram", fetcher=lambda platform, cursor: records)
    assert first["changed"] == 1
    assert second["changed"] == 0
    assert service.summary("instagram")["engagement_rate"] == 12.5


def test_tiktok_fetch_paginates_and_maps_statistics(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "tiktok.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "token",
        "refresh_token": "refresh", "user_id": "user", "redirect_uri": "https://localhost/callback",
    })
    responses = iter([
        {"data": {"videos": [{"id": "one", "title": "One", "create_time": 1,
                                "view_count": 10, "share_count": 2}], "has_more": True, "cursor": 2}},
        {"data": {"videos": [{"id": "two", "title": "Two", "create_time": 2,
                                "view_count": 20, "share_count": 3}], "has_more": False}},
    ])
    monkeypatch.setattr(service, "_json_request", lambda request: next(responses))
    records = service._fetch_tiktok(None)
    assert [row["source_video_id"] for row in records] == ["one", "two"]
    assert sum(row["shares"] for row in records) == 5


def test_oauth_urls_and_token_exchange_use_saved_configuration(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "oauth.db"))
    service.save_configuration("instagram", {
        "app_id": "app", "app_secret": "secret", "access_token": "old",
        "account_id": "account", "redirect_uri": "https://localhost/callback",
    })
    assert "instagram_business_manage_insights" in service.authorization_url("instagram")
    monkeypatch.setattr(service, "_post_form", lambda url, values: {"access_token": "new", "user_id": 7})
    service.exchange_authorization_code("instagram", "code")
    assert service.configuration("instagram")["access_token"] == "new"


def test_expired_token_refreshes_once_and_retries_sync(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "refresh.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "expired",
        "refresh_token": "refresh", "user_id": "user", "redirect_uri": "https://localhost/callback",
    })
    calls = []
    def fetch(platform, cursor):
        calls.append(service.configuration("tiktok")["access_token"])
        if len(calls) == 1:
            raise RuntimeError("401 expired token")
        return []
    monkeypatch.setattr(service, "_fetch_records", fetch)
    monkeypatch.setattr(service, "refresh_access_token", lambda platform: service.save_configuration(
        "tiktok", {**service.configuration("tiktok"), "access_token": "fresh"}, True
    ))
    result = service.sync("tiktok")
    assert result["seen"] == 0
    assert calls == ["expired", "fresh"]


def test_youtube_sync_mirrors_content_tab_table(tmp_path):
    db = DB(tmp_path / "youtube-mirror.db")
    db.execute("""CREATE TABLE youtube_content(
        content_id TEXT PRIMARY KEY,title TEXT,description TEXT,publish_time TEXT,
        duration_seconds REAL NOT NULL DEFAULT 0,views INTEGER NOT NULL DEFAULT 0,
        likes INTEGER NOT NULL DEFAULT 0,comments INTEGER NOT NULL DEFAULT 0,
        shares INTEGER NOT NULL DEFAULT 0)""")
    service = SocialPlatformService(db)
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    service.sync("youtube", fetcher=lambda platform, cursor: [{
        "source_video_id": "yt-1", "title": "A Better Clip Title", "description": "Description",
        "published_at": "2026-08-01T00:00:00Z", "duration_seconds": 45, "views": 1000,
    }])
    row = db.frame("SELECT * FROM youtube_content WHERE content_id='yt-1'").iloc[0]
    assert row["title"] == "A Better Clip Title"
    assert row["description"] == "Description"
    assert int(row["views"]) == 1000
    assert int(row["likes"]) == 0
    assert int(row["comments"]) == 0
    assert int(row["shares"]) == 0
