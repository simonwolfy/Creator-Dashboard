from __future__ import annotations

import sqlite3

import pandas as pd

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.platform_publishing import (
    HttpResponse,
    INSTAGRAM_PUBLISH_SCOPE,
    PlatformPublishingService,
    TIKTOK_PUBLISH_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
)
from creator_intelligence.services.publishing_planner import PublishingPlannerService
from creator_intelligence.services.social_platforms import SocialPlatformService


class DB:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.path = path
        self.credential_backend = MemoryCredentialBackend()

    def execute(self, sql, params=()):
        cursor = self.connection.execute(sql, tuple(params))
        self.connection.commit()
        return cursor.lastrowid

    def frame(self, sql, params=()):
        return pd.read_sql_query(sql, self.connection, params=tuple(params))


class FakeTransport:
    def __init__(self, requests=(), uploads=()):
        self.request_responses = list(requests)
        self.upload_responses = list(uploads)
        self.requests = []
        self.uploads = []

    def request(self, method, url, *, headers=None, payload=None, form=None):
        self.requests.append((method, url, headers or {}, payload, form))
        return self.request_responses.pop(0)

    def upload(self, method, url, path, *, offset=0, length=None, headers=None):
        self.uploads.append((method, url, path, offset, length, headers or {}))
        return self.upload_responses.pop(0)


def response(status=200, body=None, headers=None):
    return HttpResponse(status, headers or {}, body or {})


def services(tmp_path, platform, scope, transport):
    db = DB(tmp_path / f"{platform}.db")
    db.execute("""CREATE TABLE production_projects(
        id INTEGER PRIMARY KEY,title TEXT,status TEXT,editor_id INTEGER,
        expected_draft_at TEXT,actual_draft_at TEXT)""")
    social = SocialPlatformService(db)
    config = {
        "access_token": "access",
        "granted_scopes": scope,
        "connection_state": "connected",
    }
    if platform == "youtube":
        config.update(oauth_client_id="client", refresh_token="refresh", channel_id="channel")
    elif platform == "tiktok":
        config.update(client_key="key", client_secret="secret", refresh_token="refresh", user_id="user")
    else:
        config.update(app_id="app", app_secret="secret", account_id="account")
    social.save_configuration(platform, config)
    planner = PublishingPlannerService(db)
    publisher = PlatformPublishingService(db, social, planner, transport)
    return db, planner, publisher


def item(planner, platform):
    return planner.create_item({
        "title": "Approved clip",
        "platform": platform,
        "content_type": "Short",
        "status": "Ready",
        "upload_status": "Local file ready",
    })


def test_youtube_resumable_upload_is_durable_and_idempotent(tmp_path):
    transport = FakeTransport(
        requests=[response(headers={"location": "https://upload.youtube.test/session"})],
        uploads=[response(200, {"id": "youtube-video"})],
    )
    db, planner, publisher = services(
        tmp_path, "youtube", YOUTUBE_UPLOAD_SCOPE, transport
    )
    item_id = item(planner, "YouTube Shorts")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    first = publisher.dispatch(item_id, video, metadata={"privacy_status": "private"})
    second = publisher.dispatch(item_id, video)

    assert first["platform_post_id"] == "youtube-video"
    assert second["platform_post_id"] == "youtube-video"
    assert len(transport.requests) == 1
    assert len(transport.uploads) == 1
    row = db.frame("SELECT * FROM platform_publication_dispatches").iloc[0]
    assert not row["upload_session_key"]
    assert "https://upload.youtube.test/session" not in str(row.to_dict())
    assert row["platform_post_id"] == "youtube-video"
    assert planner.item(item_id)["status"] == "Published"


def test_youtube_reconcile_resumes_from_provider_range(tmp_path):
    transport = FakeTransport(
        uploads=[
            response(308, headers={"range": "bytes=0-1"}),
            response(200, {"id": "resumed-video"}),
        ]
    )
    db, planner, publisher = services(
        tmp_path, "youtube", YOUTUBE_UPLOAD_SCOPE, transport
    )
    item_id = item(planner, "YouTube")
    video = tmp_path / "resume.mp4"
    video.write_bytes(b"video")
    publisher._start_dispatch(item_id, "youtube", video, {"title": "Resume"})
    publisher._save_remote(item_id, upload_url="https://upload.youtube.test/resume", state="Uploading")
    stored = db.frame("SELECT * FROM platform_publication_dispatches").iloc[0]
    assert stored["upload_session_key"] == f"publishing_upload_session_{item_id}"
    assert "https://upload.youtube.test/resume" not in str(stored.to_dict())

    result = publisher.reconcile(item_id)

    assert result["platform_post_id"] == "resumed-video"
    assert transport.uploads[0][3:5] == (5, 0)
    assert transport.uploads[1][3] == 2
    assert transport.uploads[1][5]["Content-Range"] == "bytes 2-4/5"


def test_tiktok_reconcile_polls_existing_publish_without_reupload(tmp_path):
    transport = FakeTransport(
        requests=[
            response(body={"data": {"privacy_level_options": ["SELF_ONLY"]}}),
            response(body={"data": {
                "publish_id": "publish-1", "upload_url": "https://upload.tiktok.test/one"
            }}),
            response(body={"data": {"status": "PROCESSING_UPLOAD"}}),
            response(body={"data": {
                "status": "PUBLISH_COMPLETE", "publicly_available_post_id": ["post-1"]
            }}),
        ],
        uploads=[response(201)],
    )
    db, planner, publisher = services(tmp_path, "tiktok", TIKTOK_PUBLISH_SCOPE, transport)
    item_id = item(planner, "TikTok")
    video = tmp_path / "tiktok.mp4"
    video.write_bytes(b"video")

    first = publisher.dispatch(item_id, video)
    second = publisher.reconcile(item_id)

    assert first["state"] == "Processing"
    assert second["platform_post_id"] == "post-1"
    assert len(transport.uploads) == 1
    assert sum("video/init" in call[1] for call in transport.requests) == 1
    assert db.frame("SELECT COUNT(*) count FROM platform_publication_dispatches").iloc[0]["count"] == 1


def test_instagram_container_is_reused_while_processing(tmp_path):
    transport = FakeTransport(requests=[
        response(body={"id": "container-1"}),
        response(body={"status_code": "IN_PROGRESS"}),
        response(body={"status_code": "FINISHED"}),
        response(body={"id": "instagram-post"}),
        response(body={"id": "instagram-post", "permalink": "https://instagram.test/reel/one"}),
    ])
    db, planner, publisher = services(
        tmp_path, "instagram", INSTAGRAM_PUBLISH_SCOPE, transport
    )
    item_id = item(planner, "Instagram")
    video = tmp_path / "instagram.mp4"
    video.write_bytes(b"video")

    first = publisher.dispatch(
        item_id, video, instagram_video_url="https://cdn.example.test/instagram.mp4"
    )
    second = publisher.reconcile(item_id)

    assert first["state"] == "Processing"
    assert second["platform_post_id"] == "instagram-post"
    assert second["url"] == "https://instagram.test/reel/one"
    assert sum(call[1].endswith("/media") for call in transport.requests) == 1
    assert planner.item(item_id)["status"] == "Published"


def test_publish_permission_is_required_before_remote_session(tmp_path):
    transport = FakeTransport()
    _db, planner, publisher = services(tmp_path, "youtube", "", transport)
    item_id = item(planner, "YouTube Shorts")
    video = tmp_path / "no-scope.mp4"
    video.write_bytes(b"video")

    try:
        publisher.dispatch(item_id, video)
    except ValueError as exc:
        assert YOUTUBE_UPLOAD_SCOPE in str(exc)
    else:
        raise AssertionError("Publishing without upload permission should fail")
    assert transport.requests == []
    assert planner.item(item_id)["upload_status"] == "Failed"
