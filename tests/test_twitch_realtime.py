from __future__ import annotations

import sqlite3

import pandas as pd

from creator_intelligence.core.credential_vault import MemoryCredentialBackend
from creator_intelligence.services.live_integrations import TwitchLiveAdapter
from creator_intelligence.services.live_stream import LiveStreamService
from creator_intelligence.ui.pages.twitch import FrameModel


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


def test_empty_frame_model_ignores_stale_header_requests():
    model = FrameModel(pd.DataFrame())
    assert model.headerData(7, 1) is None
