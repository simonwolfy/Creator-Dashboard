from __future__ import annotations

import json
from collections import deque
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from creator_intelligence.services.live_integrations import TwitchLiveAdapter


class TwitchEventSubClient(QObject):
    """One resilient Twitch EventSub WebSocket for live events and chat."""

    status_changed = Signal(str)
    chat_received = Signal(object)
    data_changed = Signal()
    failed = Signal(str)

    def __init__(self, live_service, parent: QObject | None = None):
        super().__init__(parent)
        self.live_service = live_service
        self.adapter = TwitchLiveAdapter(live_service)
        self.socket: QWebSocket | None = None
        self.wanted = False
        self.url = "wss://eventsub.wss.twitch.tv/ws?keepalive_timeout_seconds=30"
        self._seen_order: deque[str] = deque()
        self._seen_ids: set[str] = set()
        self._recent_chat: deque[dict[str, Any]] = deque(maxlen=500)

    def recent_chat(self) -> list[dict[str, Any]]:
        return list(self._recent_chat)

    def start(self) -> None:
        if self.wanted and self.socket is not None:
            return
        if not self.wanted:
            self._recent_chat.clear()
        status = self.adapter.connect()
        if not status.connected:
            raise ValueError(status.message)
        self.wanted = True
        self._open(self.url)

    def stop(self) -> None:
        self.wanted = False
        if self.socket is not None:
            self.socket.close()
        self.status_changed.emit("Twitch EventSub stopped")

    def _open(self, url: str) -> None:
        if not self.wanted:
            return
        old = self.socket
        socket = QWebSocket()
        self.socket = socket
        socket.connected.connect(lambda: self._connected(socket))
        socket.disconnected.connect(lambda: self._disconnected(socket))
        socket.textMessageReceived.connect(lambda text: self._message(socket, text))
        socket.errorOccurred.connect(lambda _error: self._error(socket))
        socket.open(QUrl(url))
        if old is not None:
            old.close()
            old.deleteLater()
        self.status_changed.emit("Connecting to Twitch live events and chat...")

    def _connected(self, socket: QWebSocket) -> None:
        if socket is self.socket:
            self.status_changed.emit("Connected to Twitch; subscribing to live events...")

    def _disconnected(self, socket: QWebSocket) -> None:
        if socket is not self.socket or not self.wanted:
            return
        self.status_changed.emit("Twitch event connection lost; reconnecting...")
        QTimer.singleShot(3000, lambda: self._open(self.url))

    def _error(self, socket: QWebSocket) -> None:
        if socket is not self.socket:
            return
        message = self.live_service.vault.redact(socket.errorString())
        self.failed.emit(message)
        self.status_changed.emit(f"Twitch live-event error: {message}")

    def _message(self, socket: QWebSocket, text: str) -> None:
        if socket is not self.socket:
            return
        try:
            message: dict[str, Any] = json.loads(text)
        except (TypeError, ValueError):
            return
        metadata = message.get("metadata") or {}
        message_id = str(metadata.get("message_id") or "")
        if message_id and self._already_seen(message_id):
            return
        message_type = metadata.get("message_type")
        payload = message.get("payload") or {}
        if message_type == "session_welcome":
            session_id = str((payload.get("session") or {}).get("id") or "")
            if not session_id:
                self.failed.emit("Twitch did not return an EventSub session ID.")
                return
            result = self.live_service.subscribe_twitch_eventsub(session_id)
            subscribed = result.get("subscribed") or []
            errors = result.get("errors") or []
            if subscribed:
                suffix = f" ({len(errors)} unavailable)" if errors else ""
                self.status_changed.emit(
                    f"Twitch real-time tracking active: {len(subscribed)} event feeds{suffix}"
                )
            else:
                detail = errors[0]["error"] if errors else "No subscriptions were accepted."
                self.failed.emit(str(detail))
            return
        if message_type == "session_reconnect":
            reconnect_url = str((payload.get("session") or {}).get("reconnect_url") or "")
            if reconnect_url:
                self.url = reconnect_url
                self._open(reconnect_url)
            return
        if message_type != "notification":
            return
        try:
            result = self.adapter.ingest_eventsub(message)
        except Exception as exc:
            self.failed.emit(self.live_service.vault.redact(exc))
            return
        subscription = payload.get("subscription") or {}
        event = payload.get("event") or {}
        if subscription.get("type") == "channel.chat.message":
            if result:
                self._recent_chat.append({
                    "captured_at": result.get("captured_at"),
                    "chatter_user_name": result.get("chatter_user_name"),
                    "message_text": result.get("message_text"),
                })
            self.chat_received.emit(result or event)
        self.data_changed.emit()

    def _already_seen(self, message_id: str) -> bool:
        if message_id in self._seen_ids:
            return True
        self._seen_ids.add(message_id)
        self._seen_order.append(message_id)
        while len(self._seen_order) > 2000:
            self._seen_ids.discard(self._seen_order.popleft())
        return False
