from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any
import json

@dataclass
class IntegrationStatus:
    name: str
    connected: bool
    message: str
    checked_at: str

class TwitchLiveAdapter:
    """
    Integration foundation.

    Network calls are intentionally isolated behind this adapter so credentials,
    token refresh, EventSub WebSocket handling, and Twitch API polling can be
    implemented without changing the live-session service or UI.
    """
    def __init__(self, live_service):
        self.live_service=live_service
        self.connected=False
        self.last_message=None

    def connect(self):
        settings=self.live_service.settings()
        if not settings.get("twitch_enabled"):
            return IntegrationStatus(
                "Twitch",False,"Twitch integration is disabled.",
                datetime.now().isoformat()
            )
        if not settings.get("twitch_client_id") or not settings.get("twitch_access_token"):
            return IntegrationStatus(
                "Twitch",False,
                "Client ID and OAuth access token are required.",
                datetime.now().isoformat()
            )
        self.connected=True
        return IntegrationStatus(
            "Twitch",True,
            "Credentials are configured. EventSub and polling transport are ready to initialize.",
            datetime.now().isoformat()
        )

    def ingest_eventsub(self, message: dict[str,Any]):
        metadata=message.get("metadata") or {}
        payload=message.get("payload") or {}
        subscription=payload.get("subscription") or {}
        event=payload.get("event") or {}
        event_type=subscription.get("type") or metadata.get("subscription_type")
        message_id=metadata.get("message_id")

        if event_type=="stream.online":
            return self.live_service.start_session(
                title=event.get("title"),game=event.get("category_name"),
                source_mode="twitch",twitch_stream_id=event.get("id")
            )
        if event_type=="stream.offline":
            return self.live_service.end_session()
        if event_type=="channel.raid":
            return self.live_service.add_raid(
                event.get("viewers",0),
                event.get("from_broadcaster_user_name") or "Unknown",
                message_id
            )
        if event_type=="channel.follow":
            return self.live_service.add_follow(
                event.get("user_name"),message_id
            )
        if event_type=="channel.update":
            return self.live_service.add_game_change(
                event.get("category_name") or "Unknown",
                event.get("title")
            )
        if event_type=="channel.chat.message":
            return self.live_service.add_event(
                self.live_service.active_session()["id"],
                "chat_message","Chat message received",None,
                "Twitch",message_id,
                {"chatter_user_name":event.get("chatter_user_name")}
            )
        return None

class OBSLiveAdapter:
    """
    OBS WebSocket transport foundation.

    The adapter accepts OBS event dictionaries today and maps them into the
    session timeline. A later dependency may supply the actual websocket-client
    implementation without changing the database or dashboard.
    """
    def __init__(self, live_service):
        self.live_service=live_service
        self.connected=False

    def connect(self):
        settings=self.live_service.settings()
        if not settings.get("obs_enabled"):
            return IntegrationStatus(
                "OBS",False,"OBS integration is disabled.",
                datetime.now().isoformat()
            )
        host=settings.get("obs_host") or "127.0.0.1"
        port=int(settings.get("obs_port") or 4455)
        self.connected=True
        return IntegrationStatus(
            "OBS",True,
            f"OBS WebSocket endpoint configured at {host}:{port}.",
            datetime.now().isoformat()
        )

    def ingest_event(self,event_type,event_data):
        session=self.live_service.active_session()
        if not session:
            return None
        if event_type=="CurrentProgramSceneChanged":
            return self.live_service.add_scene_change(
                event_data.get("sceneName") or "Unknown"
            )
        if event_type=="StreamStateChanged":
            active=bool(event_data.get("outputActive"))
            if active and not self.live_service.active_session():
                return self.live_service.start_session(source_mode="obs")
            if not active and self.live_service.active_session():
                return self.live_service.end_session()
        if event_type=="RecordStateChanged":
            return self.live_service.add_event(
                session["id"],"record_state","OBS recording state changed",
                f'Recording active: {bool(event_data.get("outputActive"))}.',
                "OBS",payload=event_data
            )
        return self.live_service.add_event(
            session["id"],"obs_event",event_type,
            json.dumps(event_data,default=str),"OBS",payload=event_data
        )
