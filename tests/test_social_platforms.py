from __future__ import annotations

import sqlite3
import pandas as pd
from urllib.parse import parse_qs, urlparse

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


def test_youtube_api_key_mode_is_explicitly_limited(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "youtube-limited.db"))
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    status = service.connection_status("youtube")
    assert status["state"] == "limited"
    assert status["can_sync"] is True
    assert "private YouTube Analytics" in status["message"]
    assert status["capabilities"][1]["available"] is False


def test_youtube_revoked_refresh_token_requires_reconnect(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "youtube-revoked.db"))
    service.save_configuration("youtube", {
        "oauth_client_id": "client", "access_token": "expired", "refresh_token": "revoked",
        "channel_id": "channel", "granted_scopes": " ".join(service.YOUTUBE_SCOPES),
        "connection_state": "connected",
    })
    monkeypatch.setattr(
        service, "_post_form", lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("HTTP 400: invalid_grant token revoked")
        ),
    )
    try:
        service.refresh_access_token("youtube")
    except RuntimeError:
        pass
    else:
        raise AssertionError("A revoked refresh token should fail")
    assert service.connection_status("youtube")["state"] == "revoked"


def test_youtube_quota_error_enters_limited_state(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "youtube-quota.db"))
    service.save_configuration("youtube", {
        "access_token": "access", "refresh_token": "refresh", "channel_id": "channel",
        "granted_scopes": " ".join(service.YOUTUBE_SCOPES), "connection_state": "connected",
    })
    monkeypatch.setattr(
        service, "_fetch_records", lambda *_args: (_ for _ in ()).throw(
            RuntimeError("HTTP 403: quota exceeded (quotaExceeded)")
        ),
    )
    try:
        service.sync("youtube")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Quota exhaustion should fail this sync")
    assert service.connection_status("youtube")["state"] == "limited"


def test_youtube_analytics_rows_map_to_content_metrics(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "youtube-analytics.db"))
    monkeypatch.setattr(service, "_json_request", lambda _request: {
        "columnHeaders": [{"name": name} for name in (
            "video", "views", "engagedViews", "estimatedMinutesWatched",
            "averageViewPercentage", "subscribersGained", "subscribersLost",
            "likes", "comments", "shares",
        )],
        "rows": [["video-1", 100, 80, 240, 62.5, 5, 1, 12, 3, 2]],
    })
    metrics = service._fetch_youtube_analytics({"access_token": "safe"})["video-1"]
    assert metrics["watch_time_hours"] == 4
    assert metrics["avg_percentage_viewed"] == 62.5
    assert metrics["subscribers_gained"] == 5
    assert metrics["shares"] == 2


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
    monkeypatch.setattr(service, "_json_request", lambda request: {})
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
        engaged_views INTEGER NOT NULL DEFAULT 0,watch_time_hours REAL NOT NULL DEFAULT 0,
        avg_percentage_viewed REAL NOT NULL DEFAULT 0,
        subscribers_gained INTEGER NOT NULL DEFAULT 0,subscribers_lost INTEGER NOT NULL DEFAULT 0,
        likes INTEGER NOT NULL DEFAULT 0,comments INTEGER NOT NULL DEFAULT 0,
        shares INTEGER NOT NULL DEFAULT 0)""")
    service = SocialPlatformService(db)
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    service.sync("youtube", fetcher=lambda platform, cursor: [{
        "source_video_id": "yt-1", "title": "A Better Clip Title", "description": "Description",
        "published_at": "2026-08-01T00:00:00Z", "duration_seconds": 45, "views": 1000,
        "engaged_views": 750, "watch_time_hours": 12.5, "avg_percentage_viewed": 68.0,
        "subscribers_gained": 9, "subscribers_lost": 1, "shares": 4,
    }])
    row = db.frame("SELECT * FROM youtube_content WHERE content_id='yt-1'").iloc[0]
    assert row["title"] == "A Better Clip Title"
    assert row["description"] == "Description"
    assert int(row["views"]) == 1000
    assert int(row["likes"]) == 0
    assert int(row["comments"]) == 0
    assert int(row["shares"]) == 4
    assert int(row["engaged_views"]) == 750
    assert float(row["watch_time_hours"]) == 12.5
    assert float(row["avg_percentage_viewed"]) == 68.0
    assert int(row["subscribers_gained"]) == 9
    assert int(row["subscribers_lost"]) == 1


def test_youtube_sync_claims_legacy_title_without_duplicate_error(tmp_path):
    db = DB(tmp_path / "youtube-legacy-title.db")
    service = SocialPlatformService(db)
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    now = "2026-08-01T00:00:00Z"
    db.execute("""INSERT INTO creator_published_titles(
        platform,content_type,title,example_type,created_at,updated_at)
        VALUES('youtube','video','Already imported','published',?,?)""", (now, now))

    result = service.sync("youtube", fetcher=lambda platform, cursor: [{
        "source_video_id": "yt-legacy", "content_type": "video",
        "title": "Already imported", "published_at": now, "views": 42,
    }])

    rows = db.frame("SELECT * FROM creator_published_titles WHERE platform='youtube'")
    assert result["changed"] == 1
    assert len(rows) == 1
    assert rows.iloc[0]["source_video_id"] == "yt-legacy"
    assert int(rows.iloc[0]["views"]) == 42


def test_platform_ids_allow_two_posts_with_the_same_title(tmp_path):
    db = DB(tmp_path / "duplicate-visible-title.db")
    service = SocialPlatformService(db)
    service.save_configuration("youtube", {"api_key": "key", "channel_id": "channel"})
    records = [
        {"source_video_id": "yt-one", "content_type": "video", "title": "Weekly update"},
        {"source_video_id": "yt-two", "content_type": "video", "title": "Weekly update"},
    ]
    service.sync("youtube", fetcher=lambda platform, cursor: records)
    rows = db.frame(
        "SELECT source_video_id FROM creator_published_titles WHERE platform='youtube' ORDER BY source_video_id"
    )
    assert rows["source_video_id"].tolist() == ["yt-one", "yt-two"]


def test_legacy_unique_title_schema_is_upgraded_in_place(tmp_path):
    db = DB(tmp_path / "legacy-unique-schema.db")
    db.execute("""CREATE TABLE creator_published_titles(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL DEFAULT 'twitch',
        content_type TEXT NOT NULL DEFAULT 'clip', title TEXT NOT NULL,
        game TEXT, published_at TEXT, views INTEGER, likes INTEGER,
        comments INTEGER, watch_time REAL,
        example_type TEXT NOT NULL DEFAULT 'published', source_video_id TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(platform,content_type,title))""")
    db.execute("""INSERT INTO creator_published_titles(
        platform,content_type,title,created_at,updated_at)
        VALUES('youtube','video','Same title','2026-08-01','2026-08-01')""")

    SocialPlatformService(db)
    db.execute("""INSERT INTO creator_published_titles(
        platform,content_type,title,source_video_id,created_at,updated_at)
        VALUES('youtube','video','Same title','second','2026-08-02','2026-08-02')""")

    assert len(db.frame("SELECT id FROM creator_published_titles")) == 2
    schema = db.frame(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='creator_published_titles'"
    ).iloc[0]["sql"].lower()
    assert "unique(platform,content_type,title)" not in "".join(schema.split())


def test_instagram_partial_permissions_keep_basic_content_sync_available(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "instagram-partial.db"))
    service.save_configuration("instagram", {
        "app_id": "app", "app_secret": "secret", "access_token": "token",
        "account_id": "account", "granted_scopes": "instagram_business_basic",
        "connection_state": "connected",
    })

    status = service.connection_status("instagram")

    assert status["state"] == "limited"
    assert status["can_sync"] is True
    assert status["missing_scopes"] == ["instagram_business_manage_insights"]
    assert status["capabilities"][0]["available"] is True
    assert status["capabilities"][1]["available"] is False


def test_tiktok_without_video_permission_cannot_sync_videos(tmp_path):
    service = SocialPlatformService(DB(tmp_path / "tiktok-partial.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "token",
        "refresh_token": "refresh", "user_id": "user",
        "granted_scopes": "user.info.basic", "connection_state": "connected",
    })

    status = service.connection_status("tiktok")

    assert status["state"] == "limited"
    assert status["can_sync"] is False
    assert status["capabilities"][0]["available"] is True
    assert status["capabilities"][1]["available"] is False


def test_tiktok_refresh_persists_rotated_token_scope_and_refresh_expiry(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "tiktok-rotation.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "old-access",
        "refresh_token": "old-refresh", "user_id": "user",
        "granted_scopes": "user.info.basic video.list", "connection_state": "connected",
    })
    monkeypatch.setattr(service, "_post_form", lambda *_args, **_kwargs: {
        "access_token": "new-access", "refresh_token": "new-refresh",
        "expires_in": 86400, "refresh_expires_in": 31_536_000,
        "scope": "user.info.basic,video.list",
    })

    service.refresh_access_token("tiktok")
    config = service.configuration("tiktok")

    assert config["access_token"] == "new-access"
    assert config["refresh_token"] == "new-refresh"
    assert config["refresh_expires_at"]
    assert service.connection_status("tiktok")["state"] == "connected"


def test_tiktok_revoked_connection_is_classified_and_requires_reconnect(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "tiktok-revoked.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "access",
        "refresh_token": "refresh", "user_id": "user",
        "granted_scopes": "user.info.basic video.list", "connection_state": "connected",
    })
    monkeypatch.setattr(
        service, "_tiktok_identity",
        lambda _config: (_ for _ in ()).throw(RuntimeError("HTTP 400: invalid_grant token revoked")),
    )
    monkeypatch.setattr(
        service, "refresh_access_token",
        lambda _platform: (_ for _ in ()).throw(RuntimeError("HTTP 400: invalid_grant token revoked")),
    )

    status = service.validate_connection("tiktok")

    assert status["state"] == "revoked"
    assert status["can_sync"] is False
    assert "Reconnect" in status["message"]


def test_instagram_insights_fall_back_per_metric_and_report_partial_access(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "instagram-insights.db"))

    def graph_request(request):
        metrics = parse_qs(urlparse(request.full_url).query).get("metric", [""])[0]
        if "," in metrics:
            raise RuntimeError("Metric is not valid for this media type")
        if metrics == "views":
            return {"data": [{"name": "views", "values": [{"value": 125}]}]}
        if metrics == "shares":
            return {"data": [{"name": "shares", "total_value": {"value": 4}}]}
        raise RuntimeError(f"{metrics} is unavailable")

    monkeypatch.setattr(service, "_json_request", graph_request)
    service._last_sync_warnings = []

    insights = service._instagram_media_insights("media", "access")

    assert insights == {"views": 125, "shares": 4}
    assert len(service._last_sync_warnings) == 1
    assert "reach" in service._last_sync_warnings[0]


def test_tiktok_fetch_refreshes_existing_statistics_even_with_a_cursor(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "tiktok-current-stats.db"))
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "token",
        "refresh_token": "refresh", "user_id": "user",
    })
    monkeypatch.setattr(service, "_json_request", lambda _request: {
        "data": {"videos": [{
            "id": "existing", "title": "Existing", "create_time": 1,
            "view_count": 99, "like_count": 7,
        }], "has_more": False},
    })

    records = service._fetch_tiktok("2099-01-01T00:00:00+00:00")

    assert len(records) == 1
    assert records[0]["views"] == 99


def test_failed_tiktok_remote_revoke_still_clears_local_credentials(tmp_path, monkeypatch):
    db = DB(tmp_path / "tiktok-revoke-failure.db")
    service = SocialPlatformService(db)
    service.save_configuration("tiktok", {
        "client_key": "key", "client_secret": "secret", "access_token": "token",
        "refresh_token": "refresh", "user_id": "user",
    })
    monkeypatch.setattr(
        service, "_post_form",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 503 provider unavailable")),
    )

    status = service.revoke_and_disconnect("tiktok")

    assert status["configured"] is False
    assert status.get("revocation_warning")
    assert service.configuration("tiktok").get("access_token") in {None, ""}
