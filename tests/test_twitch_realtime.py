from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from urllib.error import HTTPError

import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.live_integrations import TwitchLiveAdapter
from creator_intelligence.services.live_stream import LiveStreamService
from creator_intelligence.ui.pages.twitch import FrameModel
from creator_intelligence.ui.pages.live_stream import LiveStreamPage


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

    def scalar(self, sql, params=(), default=0):
        row = self.connection.execute(sql, tuple(params)).fetchone()
        return row[0] if row and row[0] is not None else default


def connected_service(tmp_path):
    service = LiveStreamService(DB(tmp_path / "twitch-live.db"))
    service.update_settings(
        twitch_enabled=1, twitch_client_id="client", twitch_broadcaster_id="123",
        twitch_access_token="token", twitch_refresh_token="refresh", simulation_mode=0,
    )
    return service


def test_real_twitch_poll_starts_session_and_records_api_metrics(tmp_path, monkeypatch):
    service = connected_service(tmp_path)

    def twitch_request(path, query=None, **kwargs):
        responses = {
            "streams": {"data": [{
                "id": "stream-1", "viewer_count": 37, "title": "Live now",
                "game_name": "RimWorld", "started_at": "2026-08-08T12:00:00Z",
            }]},
            "channels": {"data": [{"title": "Live now", "game_name": "RimWorld"}]},
            "channels/followers": {"total": 200, "data": []},
            "subscriptions": {"total": 12, "data": []},
        }
        return responses[path]

    monkeypatch.setattr(service, "_twitch_request", twitch_request)
    status = service.poll_twitch_live()

    assert status["is_live"] is True
    assert service.active_session()["source_mode"] == "twitch"
    latest = service.latest_snapshot()
    assert int(latest["viewers"]) == 37
    assert int(latest["followers_total"]) == 200
    assert int(latest["subscribers_total"]) == 12


def test_eventsub_chat_is_saved_for_chat_interface(tmp_path):
    service = connected_service(tmp_path)
    service.update_settings(store_raw_chat=1)
    service.start_session(source_mode="twitch")
    adapter = TwitchLiveAdapter(service)
    result = adapter.ingest_eventsub({
        "metadata": {"message_id": "event-1"},
        "payload": {
            "subscription": {"type": "channel.chat.message"},
            "event": {
                "message_id": "chat-1", "chatter_user_id": "viewer-1",
                "chatter_user_name": "Viewer", "message": {"text": "Hello chat"},
            },
        },
    })
    assert result["message_text"] == "Hello chat"
    messages = service.chat_messages()
    assert messages.iloc[0]["chatter_user_name"] == "Viewer"
    assert messages.iloc[0]["message_text"] == "Hello chat"


def test_live_chat_is_ephemeral_by_default_but_activity_is_counted(tmp_path):
    service = connected_service(tmp_path)
    service.start_session(source_mode="twitch")
    result = service.record_chat_message({
        "message_id": "private-chat",
        "chatter_user_id": "private-viewer",
        "chatter_user_name": "Viewer",
        "message": {"text": "Do not retain this message"},
    })

    assert result["message_text"] == "Do not retain this message"
    assert result["retained"] is False
    assert service.chat_messages().empty
    assert service.chat_activity() == {"messages_minute": 1, "unique_chatters_5m": 1}
    database_bytes = service.db.path.read_bytes()
    assert b"Do not retain this message" not in database_bytes
    assert b"private-viewer" not in database_bytes


def test_twitch_validation_records_scopes_account_and_expiry(tmp_path, monkeypatch):
    service = connected_service(tmp_path)
    monkeypatch.setattr(service, "_json_request", lambda _request: {
        "client_id": "client",
        "user_id": "123",
        "login": "example_creator",
        "scopes": list(service.TWITCH_SCOPES),
        "expires_in": 3600,
    })

    status = service.validate_twitch_connection()

    assert status["state"] == "connected"
    assert status["account_name"] == "example_creator"
    assert status["missing_scopes"] == []
    assert status["last_validated_at"]
    assert service.twitch_capabilities()


def test_revoked_twitch_token_requires_reconnect(tmp_path, monkeypatch):
    service = connected_service(tmp_path)

    def rejected(_request):
        raise HTTPError("https://id.twitch.tv/oauth2/validate", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(service, "_json_request", rejected)
    status = service.validate_twitch_connection()

    assert status["state"] == "revoked"
    assert status["can_sync"] is False
    assert "reconnect" in status["message"].lower()


def test_expired_twitch_token_refreshes_once_and_rotates_both_tokens(tmp_path, monkeypatch):
    service = connected_service(tmp_path)
    service.update_settings(
        twitch_token_expires_at=(datetime.now() - timedelta(minutes=1)).isoformat()
    )
    calls = []

    def refresh(_url, values):
        calls.append(dict(values))
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 14400,
            "scope": list(service.TWITCH_SCOPES),
        }

    monkeypatch.setattr(service, "_post_form", refresh)
    monkeypatch.setattr(service, "validate_twitch_connection", service.twitch_connection_status)

    status = service.ensure_twitch_connection()

    assert status["can_sync"] is True
    assert len(calls) == 1
    assert "client_secret" not in calls[0]
    assert service.settings()["twitch_access_token"] == "new-access"
    assert service.settings()["twitch_refresh_token"] == "new-refresh"


def test_eventsub_skips_features_without_granted_permissions(tmp_path, monkeypatch):
    service = connected_service(tmp_path)
    service._set_twitch_connection_metadata(
        twitch_connection_state="limited",
        twitch_granted_scopes_json="[]",
        twitch_last_validated_at=datetime.now().isoformat(),
    )
    calls = []
    monkeypatch.setattr(
        service,
        "_twitch_request",
        lambda path, **kwargs: calls.append(kwargs["payload"]["type"]) or {},
    )

    result = service.subscribe_twitch_eventsub("session")

    assert "stream.online" in result["subscribed"]
    assert "channel.chat.message" not in calls
    assert "channel.follow" not in calls
    assert any("Missing permission" in error["error"] for error in result["errors"])


def test_disconnect_clears_twitch_identity_but_keeps_public_client_id(tmp_path):
    service = connected_service(tmp_path)
    service._set_twitch_connection_metadata(
        twitch_account_name="Example Creator",
        twitch_granted_scopes_json='["user:read:chat"]',
    )

    service.disconnect_integration("twitch")

    settings = service.settings()
    status = service.twitch_connection_status()
    assert settings["twitch_client_id"] == "client"
    assert not settings.get("twitch_broadcaster_id")
    assert not settings.get("twitch_access_token")
    assert status["state"] == "disconnected"


def test_empty_frame_model_ignores_stale_header_requests():
    model = FrameModel(pd.DataFrame())
    assert model.headerData(7, 1) is None


def test_live_stream_page_explains_unavailable_twitch_actions(tmp_path):
    app = QApplication.instance() or QApplication([])
    service = LiveStreamService(DB(tmp_path / "twitch-ui.db"))
    page = LiveStreamPage(service)

    assert "Not Configured" in page.connection_panel.state.text()
    assert not page.start_twitch_button.isEnabled()
    assert "Connect Twitch" in page.start_twitch_button.toolTip()
    assert not page.stop_twitch_button.isEnabled()
    assert page.twitch_access_token.isReadOnly()
    assert not page.connect_twitch_button.isEnabled()
    assert page.connect_twitch_button.toolTip() == "Paste the Twitch Client ID first."

    page.close()
    app.processEvents()
