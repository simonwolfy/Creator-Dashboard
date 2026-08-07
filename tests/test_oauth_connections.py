from __future__ import annotations

import json
import sqlite3
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pandas as pd

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.desktop_oauth import LoopbackOAuthReceiver, pkce_pair
from creator_intelligence.services.live_stream import LiveStreamService
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


def test_loopback_receiver_collects_one_oauth_callback():
    receiver = LoopbackOAuthReceiver()
    receiver.start()
    try:
        with urlopen(f"{receiver.redirect_uri}?code=approved&state=expected", timeout=5) as response:
            assert response.status == 200
        assert receiver.wait(1) == {"code": "approved", "state": "expected"}
    finally:
        receiver.close()


def test_pkce_generates_provider_specific_challenges():
    verifier, google_challenge = pkce_pair()
    tiktok_verifier, tiktok_challenge = pkce_pair(hex_challenge=True)
    assert 43 <= len(verifier) <= 128
    assert 43 <= len(tiktok_verifier) <= 128
    assert "+" not in google_challenge and "/" not in google_challenge
    assert len(tiktok_challenge) == 64
    assert set(tiktok_challenge) <= set("0123456789abcdef")


def test_youtube_desktop_oauth_imports_client_and_discovers_channel(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "youtube-oauth.db"))
    client_file = tmp_path / "client.json"
    client_file.write_text(json.dumps({"installed": {
        "client_id": "desktop.apps.googleusercontent.com", "client_secret": "google-secret",
    }}), encoding="utf-8")
    service.import_youtube_oauth_client(client_file)
    flow = service.begin_oauth("youtube", "http://127.0.0.1:43210/callback/")
    query = parse_qs(urlparse(flow["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["https://www.googleapis.com/auth/youtube.readonly"]
    monkeypatch.setattr(service, "_post_form", lambda url, values: {
        "access_token": "youtube-access", "refresh_token": "youtube-refresh", "expires_in": 3600,
    })
    monkeypatch.setattr(service, "_json_request", lambda request: {"items": [{
        "id": "UC123", "snippet": {"title": "Simon's Channel"},
    }]})
    result = service.complete_oauth("youtube", {"code": "code", "state": flow["state"]}, flow)
    config = service.configuration("youtube")
    assert result["account_id"] == "UC123"
    assert config["channel_id"] == "UC123"
    assert config["access_token"] == "youtube-access"
    assert config["refresh_token"] == "youtube-refresh"
    assert service.connection_status("youtube")["configured"] is True


def test_tiktok_desktop_oauth_uses_pkce_and_discovers_user(tmp_path, monkeypatch):
    service = SocialPlatformService(DB(tmp_path / "tiktok-oauth.db"))
    service.save_configuration("tiktok", {
        "client_key": "tiktok-key", "client_secret": "tiktok-secret",
        "redirect_uri": "http://127.0.0.1:49152/callback/",
    })
    flow = service.begin_oauth("tiktok", "http://127.0.0.1:49152/callback/")
    query = parse_qs(urlparse(flow["authorization_url"]).query)
    assert len(query["code_challenge"][0]) == 64
    captured = {}

    def token_request(_url, values):
        captured.update(values)
        return {"access_token": "tt-access", "refresh_token": "tt-refresh", "expires_in": 86400}

    monkeypatch.setattr(service, "_post_form", token_request)
    monkeypatch.setattr(service, "_json_request", lambda request: {
        "data": {"user": {"open_id": "tt-user", "display_name": "Simon"}},
    })
    service.complete_oauth("tiktok", {"code": "code", "state": flow["state"]}, flow)
    assert captured["code_verifier"] == flow["code_verifier"]
    assert service.configuration("tiktok")["user_id"] == "tt-user"


def test_instagram_oauth_discovers_account_and_keeps_tokens_in_vault(tmp_path, monkeypatch):
    db = DB(tmp_path / "instagram-oauth.db")
    service = SocialPlatformService(db)
    service.save_configuration("instagram", {
        "app_id": "meta-app", "app_secret": "meta-secret",
        "redirect_uri": "http://127.0.0.1:49153/callback/",
    })
    flow = service.begin_oauth("instagram", "http://127.0.0.1:49153/callback/")
    monkeypatch.setattr(service, "_post_form", lambda url, values: {
        "access_token": "ig-short", "user_id": "ig-user", "expires_in": 3600,
    })

    def graph_request(request):
        if "access_token?" in request.full_url:
            return {"access_token": "ig-long", "expires_in": 5_000_000}
        return {"id": "ig-user", "username": "simonwolfy"}

    monkeypatch.setattr(service, "_json_request", graph_request)
    service.complete_oauth("instagram", {"code": "code", "state": flow["state"]}, flow)
    assert service.configuration("instagram")["access_token"] == "ig-long"
    assert service.configuration("instagram")["account_name"] == "simonwolfy"
    stored = db.frame("SELECT config_json FROM integration_settings WHERE integration_id='instagram_title_sync'").iloc[0, 0]
    assert "ig-long" not in stored and "meta-secret" not in stored


def test_twitch_device_sign_in_fills_broadcaster_and_tokens(tmp_path, monkeypatch):
    service = LiveStreamService(DB(tmp_path / "twitch-oauth.db"))

    def post_form(url, values):
        if url.endswith("/device"):
            return {
                "device_code": "device", "user_code": "ABCD1234",
                "verification_uri": "https://www.twitch.tv/activate", "interval": 1,
            }
        return {
            "access_token": "twitch-access", "refresh_token": "twitch-refresh", "expires_in": 14400,
        }

    monkeypatch.setattr(service, "_post_form", post_form)
    monkeypatch.setattr(service, "_json_request", lambda request: {"data": [{
        "id": "123456", "login": "simonwolfy", "display_name": "SimonWolfy",
    }]})
    connection = service.begin_twitch_connection("twitch-client")
    result = service.poll_twitch_connection(connection)
    settings = service.settings()
    assert result["broadcaster_id"] == "123456"
    assert settings["twitch_broadcaster_id"] == "123456"
    assert settings["twitch_access_token"] == "twitch-access"
    row = service.db.frame("SELECT twitch_access_token,twitch_refresh_token FROM live_integration_settings WHERE id=1").iloc[0]
    assert not row["twitch_access_token"] and not row["twitch_refresh_token"]
